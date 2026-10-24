# TripPilot (трек «О!дин запрос»)

AI-агент для путешествий: превращает одно сообщение путешественника («к тёплому морю в ноябре, недорого, с ребёнком») в готовый план поездки и ведёт до оформления (оплата имитируется).

**Статус: этап 0, каркас.** Работает вся инфраструктура: шлюз, API, UI, БД с pgvector, миграции и сидирование. Агент пока заглушка, которая отвечает эхом.

- Видео-скринкаст: _будет добавлено перед сдачей_
- Развёрнутый сервис: нет

## Быстрый старт

```bash
git clone https://github.com/ostrovok-hackathon-2026/gradient-descent.git
cd gradient-descent
cp .env.example .env   # необязательно: без .env используются значения по умолчанию
docker compose up --build
# открыть http://localhost:8080
```

Первый запуск занимает 2–4 минуты (в основном скачивание образов и пакетов), повторный меньше минуты.

## Зависимости и переменные окружения

Рекомендованные ресурсы: 2 CPU, 4 GB RAM, ~3 GB диска.

| Сервис | Образ | Назначение |
|---|---|---|
| `gateway` | `nginxinc/nginx-unprivileged:1.28-alpine` | единственный порт наружу, **8080**: `/` → UI, `/api` и `/health` → API |
| `ui` | собирается из `docker/app.Dockerfile` | Streamlit (внутри сети: 8501) |
| `api` | тот же образ | FastAPI (внутри сети: 8000) |
| `bootstrap` | тот же образ | одноразово: миграции → сид → RAG-индекс, затем завершается |
| `db` | `pgvector/pgvector:0.8.1-pg16` | PostgreSQL 16 + `vector`, `pg_trgm`, `unaccent` |
| `pgadmin` | `dpage/pgadmin4:9.8` | только для разработки, профиль `tools` |

| Переменная | По умолчанию | Описание |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `trip` / `trip` / `trip` | учётные данные БД; `DATABASE_URL` для контейнеров собирается из них |
| `LOG_LEVEL` | `INFO` | уровень логов (логи идут в stdout: `docker compose logs api`) |
| `LLM_BASE_URL` | пусто | адрес OpenAI-совместимого API |
| `LLM_API_KEY` | пусто | ключ; если пусто, агент работает без LLM (с этапа 1) |
| `LLM_MODEL` / `EMBEDDINGS_MODEL` | пусто | модели генерации и эмбеддингов |
| `LLM_MAX_CONCURRENCY` | `8` | одновременных запросов к LLM на процесс |
| `DEMO_MODE` | `auto` | `auto`: без ключа включается режим без LLM |

## Сидирование

Выполняется автоматически при `docker compose up`: сервис `bootstrap` применяет миграции Alembic, загружает справочник направлений (`data/reference/`) и строит RAG-индекс (`data/knowledge/`). Все шаги идемпотентны.

```bash
docker compose run --rm bootstrap      # повторить bootstrap
docker compose down -v                 # удалить данные БД целиком
```

## Маршруты и доступ

- `/` — UI (Streamlit)
- `/health` — `200 {"status":"ok"}`; если БД недоступна, `503 {"status":"degraded"}`
- `/api/docs` — Swagger UI
- `POST /api/chat` — `{"session_id": "<uuid>", "text": "..."}` или `{"session_id": "<uuid>", "action": {"type": "select_package", "package_id": "p2"}}` → поток событий агента (`text/event-stream`)
- `GET /api/chat/{session_id}/messages` — история диалога
- `GET /api/trips/{session_id}` — текущий план поездки (`TripState`); пока плана нет, `404`
- `POST /api/orders` — `{"session_id", "package_id", "idempotency_key"}` → `201` и заказ `TP-<год>-<номер>` (оплата имитируется). Повтор с тем же ключом или по тому же пакету возвращает тот же заказ; нет плана или пакета — `404`; по плану уже оплачен другой пакет — `409`
- Тестовый пользователь не нужен: авторизации пока нет. Диалог привязан к `?sid=` в адресе страницы.

Протокол событий (`src/trip_pilot/agent/events.py`), одна строка SSE на событие:

```
data: {"type": "stage", "stage": "intake"}
data: {"type": "step", "text": "Разбираю запрос"}
data: {"type": "question", "text": "Сколько лет ребёнку?", "options": ["до 2", "2–6"]}
data: {"type": "plan", "data": {...}}
data: {"type": "delta", "text": "Принял "}
data: {"type": "done"}
```

## Структура

Подробно об архитектуре (сервисы, слои, протокол событий, агент, RAG, дорожная карта): [docs/architecture.md](docs/architecture.md).

```
src/trip_pilot/
├── domain/       # ядро: запрос, предложения, план, доменные ошибки
├── agent/        # ядро: протокол событий, действия, оркестратор (пока заглушка)
├── ports.py      # интерфейсы, через которые ядро обращается к данным, RAG и LLM
├── adapters/db/  # SQLAlchemy async: ORM-модели по зонам, репозитории
├── rag/          # база знаний
├── seed/         # сидирование справочников
├── api/          # FastAPI: /health, /api/chat, /api/trips, /api/orders
├── ui/           # Streamlit: тонкий клиент к API
└── cli.py        # bootstrap | migrate | seed
migrations/       # Alembic
data/             # справочники и документы для RAG
docker/           # Dockerfile, конфиг nginx, pgAdmin
docs/             # документация
tests/            # pytest: unit/ на фейках (tests/fakes.py), integration/ на настоящем Postgres
.github/          # CI: линтер, тесты, запуск стека и проверка /health
```

## Разработка

**Hot-reload и доступ к БД из локального pgAdmin 4:**

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
docker compose up --build
```

БД будет доступна на `localhost:5433` (`trip` / `trip`), только с этого компьютера. Порт 5433, а не 5432, чтобы не конфликтовать с локально установленным Postgres. Сам `docker-compose.override.yml` в git не попадает: Compose подхватывает его автоматически, в том числе у жюри.

**pgAdmin в Docker:** `docker compose --profile tools up --build` → http://localhost:5050 (только с этого компьютера). Вход: `PGADMIN_EMAIL` / `PGADMIN_PASSWORD` из `.env`, по умолчанию `dev@example.com` / `dev`. Сервер БД уже настроен, пароль БД — `trip`.

**Git-хуки** — один раз после клонирования:

```bash
git config core.hooksPath .githooks
```

`pre-commit` проверяет коммит на секреты (gitleaks в Docker), `pre-push` не даёт пушить напрямую в `main`.

**Миграции.** Схема меняется только через Alembic. Правки, сделанные руками в pgAdmin, до жюри не доедут.

```bash
# после изменения моделей в src/trip_pilot/adapters/db/:
docker compose run --rm -v ./migrations:/app/migrations bootstrap alembic revision --autogenerate -m "add hotel"
docker compose run --rm bootstrap      # применить
docker compose run --rm bootstrap alembic check   # ORM и БД совпадают?
```

**Локальный CI** — все шаги GitHub Actions одной командой: линтер, юнит-тесты, запуск стека и `/health`, миграции, интеграционные тесты. Actions вызывает этот же скрипт, поэтому «прошло локально» = «прошло бы в CI». Локальный Python не нужен, всё идёт в контейнерах.

```bash
sh scripts/ci.sh                                           # Git Bash, Linux, macOS (или make ci)
& "C:\Program Files\Git\bin\sh.exe" scripts/ci.sh          # PowerShell на Windows
```

Отдельные шаги:

```bash
make test        # или: docker build -f docker/app.Dockerfile --target dev -t trip-pilot-dev . && docker run --rm trip-pilot-dev pytest
make lint
make test-integration   # или: docker compose --profile tests run --rm tests (поднимет БД и прогонит миграции)
```

**GitHub Actions** запускается только на pull request, кроме черновиков и PR, где менялась только документация (`*.md`, `docs/`, `tasks/`). Новый push в PR отменяет устаревший прогон. Ручной запуск: Actions → CI → Run workflow.

**Зависимости:** добавить пакет в `pyproject.toml`, затем `make lock` обновит `uv.lock` (uv запускается в контейнере).

**Сдача:** в дедлайн поставить тег `submission` на последний коммит основной ветки.

## Безопасность

- **Секреты** (ключ LLM и прочее) хранятся только в `.env`. Он и любые `.env.*`, кроме `.env.example`, а также ключи и сертификаты (`*.pem`, `*.key`, `secrets/`) исключены из git (`.gitignore`) и из Docker-образов (`.dockerignore`).
- **Проверка на секреты.** `scripts/ci.sh` первым шагом прогоняет gitleaks по истории git, хук `pre-commit` — по каждому коммиту.
- **Наружу открыт только шлюз `8080`.** БД, API и UI доступны лишь внутри сети compose. Порты для разработки — pgAdmin `5050` и БД `5433` из override-файла — привязаны к `127.0.0.1`: из локальной сети они недоступны. pgAdmin требует вход.
- **Пароли по умолчанию** (`trip`, `dev`) — локальные, для запуска без настройки. Где-то кроме своего компьютера задайте свои в `.env`. Пароль БД применяется при первом создании тома: чтобы сменить его, выполните `docker compose down -v`.
- **`?sid=` в адресе страницы — ключ к диалогу:** по нему API отдаёт историю и план. Авторизации в MVP нет, поэтому не публикуйте ссылки и скриншоты с `sid` из реальных диалогов. Данные в демо синтетические.
- **`docker compose config` без `--quiet` печатает все переменные из `.env`**, включая ключи. Не выкладывайте его вывод в чаты и PR.
