# Задание: лид — инфраструктура, контракты, оркестратор

**Ветка:** `team/lead` · **Файл:** `tasks/lead.md` · **Владелец задания:** лид

> Документ читают и человек, и ИИ-ассистент. Ассистенту: сначала прочитай `AGENTS.md`, затем этот файл целиком.
> Статус задач отмечай галочками `[x]` прямо здесь.

## Навигация

**Этап 1: модель** (нагрузка лида минимальная, основная работа — у data и rag)
- [L1. Контракт этапа 1](#l1) — первым делом: data и rag ждут
- [L2. Провайдер, модель и ключи](#l2)
- [L3. Каждый день](#t6) — слияния и зелёный `main`
- [L4. Финиш](#l4) — README, видео, тег `submission`
- [L5. Пересборка плана](#l5) — основная задача трека: изменение условий не начинает поиск с нуля
- [L6. Модель не может оборвать ход](#l6) — страховка, лимит времени, кнопки без модели
- [L7. Ключ для жюри в `secrets.env.age`](#l7) — просьба организаторов

**MVP:** [шаг 0](#step0) · [задачи 1–5](#mvp-tasks) — всё сделано, тег `mvp` · [как править задания команды](#edit-tasks) · [правки лида](#changes)

## Цель

Склеить систему. Первым делом выдать команде контракты, чтобы трое остальных работали параллельно. Затем собрать из их частей MVP: весь путь от сообщения до номера заказа, без LLM, с e2e-тестом в CI и тегом `mvp`. Сделано.

**Этап 1 — модель.** Агент понимает живую речь и объясняет выбор с помощью LLM, а режим без LLM остаётся запасным (у жюри нашего ключа не будет). Основную работу ведут data (понимание запроса, объяснения, подбор) и rag (клиент LLM, база знаний, оценка). Лид и ui нагружены по минимуму и подключаются к ним по необходимости.

## Твоя зона

**Можно менять:** `docker/`, `.github/`, `api/`, `domain/`, `ports.py`, `config.py`, `cli.py`, `logs.py`, `agent/events.py`, `agent/actions.py`, `agent/toolkit.py`, `agent/orchestrator.py`, `agent/dates.py`, `agent/texts.py`, `agent/replanner.py`, `services/booking.py`, `services/post_purchase.py`, `adapters/db/{base,chat,orders,models,engine,repositories}.py`, `migrations/env.py`, `tests/fakes.py`, `AGENTS.md`, `README.md`, `docs/`, `tasks/*.md` (задания команды).

**Нельзя без владельца:** `rag/`, `adapters/llm/`, `data/knowledge/`, `evals/` (rag); `seed/`, `planning/`, `adapters/sources/`, `adapters/db/inventory.py`, а с этапа 1 и `agent/intent.py`, `agent/clarifier.py`, `agent/understand.py`, `agent/prompts/`, `services/explanation.py` (data); `ui/`, `.streamlit/` (ui).

---

<a id="step0"></a>
## Шаг 0 — сегодня, остальные ждут только его

Делается одним PR в `main`, после merge сообщи команде: «контракты в main, сделайте `git pull origin main`».

### 0.1. Зависимости MVP разом
Чтобы никто не правил `uv.lock` параллельно, добавь в `pyproject.toml` всё, что понадобится в MVP: `openai`, `returns`, `pyyaml`, `tenacity`, `rapidfuzz`. Потом выполни `make lock`.
- [x] `uv.lock` обновлён, образ собирается

### 0.2. Разделить `adapters/db/orm.py` по зонам

| Модуль | Содержимое | Владелец |
|---|---|---|
| `base.py` | `Base` | лид |
| `chat.py` | `ChatSession`, `ChatMessage` | лид |
| `orders.py` | пустой, с docstring (заполнишь в задаче 4) | лид |
| `knowledge.py` | `KbDocument`, `KbChunk`, `EMBEDDING_DIM` | rag |
| `reference.py` | `Destination` | data |
| `inventory.py` | **пустой**, с docstring (заполнит data) | data |
| `models.py` | импортирует все модули выше; его импортирует `migrations/env.py` | лид |

- [x] `orm.py` удалён, импорты в коде и тестах обновлены
- [x] `alembic check` показывает «No new upgrade operations detected» (схема не изменилась)

### 0.3. Доменные модели и ошибки (`domain/`)

```python
# domain/request.py
class Assumption(BaseModel):          # что агент додумал сам; UI показывает чипом
    field: str
    value: str
    reason: str

class Party(BaseModel):
    adults: int = Field(2, ge=1)
    children_ages: list[int] = []     # 0–17
    pets: list[str] = []              # "dog", "cat"

class TripRequest(BaseModel):
    origin: str | None = None         # slug из data/reference/destinations.json
    destination: str | None = None    # None → агент предлагает направления
    month: int | None = None          # 1–12, если точных дат нет
    date_from: date | None = None
    nights: int | None = None
    party: Party = Party()
    budget: Decimal | None = None     # на всех, ₽
    tags: list[str] = []              # "sea", "city", "nature", "warm"
    must: list[str] = []              # жёсткие: "pets_allowed", "direct_only", "kids_friendly"
    assumptions: list[Assumption] = []
```

```python
# domain/offers.py — деньги Decimal, время с часовым поясом
class Destination(BaseModel): slug: str; name: str; country: str; iata: str | None; lat: float; lon: float; timezone: str; tags: list[str]; warm_months: list[int]
class Hotel(BaseModel): id: int; destination: str; name: str; stars: int; price_per_night: Decimal; meal: Literal["RO","BB","HB","AI"]; free_cancellation: bool; pets_allowed: bool; kids_friendly: bool; beach_distance_m: int | None; check_in_time: time; check_out_time: time; rating: float; is_synthetic: bool
class Leg(BaseModel): id: int; mode: Literal["flight","train"]; origin: str; destination: str; depart_at: datetime; arrive_at: datetime; price: Decimal; stops: int; carrier: str; baggage_included: bool; pets_allowed: bool; is_synthetic: bool   # price — за одного пассажира
class Transfer(BaseModel): id: int; destination: str; hotel_id: int; kind: Literal["taxi","shuttle"]; duration_min: int; price: Decimal; capacity: int; pets_allowed: bool   # price — за машину в одну сторону
class Package(BaseModel):
    id: str
    tier: Literal["economy", "balance", "comfort"]
    destination: str
    outbound: Leg
    inbound: Leg
    hotel: Hotel
    transfer: Transfer | None
    check_in: date
    check_out: date
    nights: int
    total: Decimal                    # перелёты × пассажиры + отель × ночи + трансфер × 2
    price_breakdown: dict[str, Decimal]
    issues: list[str] = []            # предупреждения проверки стыковок
    why: list[str] = []
    tradeoffs: list[str] = []
    risks: list[str] = []
```

```python
# domain/trip_state.py — JSON этой модели уходит в событие plan (контракт с ui)
class Order(BaseModel): id: str; package_id: str; total: Decimal; status: Literal["paid", "cancelled"]; created_at: datetime
class PendingQuestion(BaseModel): text: str; options: list[str] = []   # своя модель: domain не импортирует agent
class TripState(BaseModel):
    session_id: UUID
    version: int = 0
    stage: str = "intake"
    request: TripRequest | None = None
    packages: list[Package] = []
    pending_question: PendingQuestion | None = None  # {text, options}: кнопки вопроса переживают F5
    selected_package_id: str | None = None
    order: Order | None = None
```

`domain/errors.py`: `MissingSlot(slot)`, `UnknownCity(raw)`, `AmbiguousCity(raw, candidates)`, `DatesInPast(start)`, `BudgetTooLow(budget, min_total)`, `NoResults(reason)`, а также тип `DomainError = …`.

### 0.4. Порты (`ports.py`), все async

```python
class DestinationCatalog(Protocol):
    async def all(self) -> list[Destination]: ...
class HotelSource(Protocol):
    async def search(self, destination: str, check_in: date, check_out: date, party: Party) -> list[Hotel]: ...
class TransportSource(Protocol):
    async def search(self, origin: str, destination: str, day: date, party: Party) -> list[Leg]: ...
class TransferSource(Protocol):
    async def search(self, hotel_id: int, arrive_at: datetime, party: Party) -> list[Transfer]: ...
class KnowledgeBase(Protocol):
    async def search(self, query: str, *, destination: str | None = None, doc_type: str | None = None, limit: int = 5) -> list[KnowledgeHit]: ...
class LLM(Protocol):
    enabled: bool
    async def complete(self, messages: list[dict[str, str]]) -> str: ...
    async def structured(self, messages: list[dict[str, str]], schema: type[T]) -> T: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
class OrderRepository(Protocol):
    async def create(self, session_id: UUID, package: Package, idempotency_key: str) -> Order: ...
class TripStateRepository(Protocol):
    async def load(self, session_id: UUID) -> TripState | None: ...
    async def save(self, state: TripState) -> None: ...
```

`KnowledgeHit`: `text`, `title`, `heading_path`, `source`, `score`.

### 0.5. Фейки (`tests/fakes.py`)
Реализации всех портов на данных в памяти: 3 направления, по 3 отеля, по 2 рейса туда и обратно, по трансферу; `FakeLLM()` без ответов ведёт себя как LLM без ключа. Подключение: `from tests.fakes import fake_sources`.
- [x] фейки реализуют все порты, а их данных хватает на три разных пакета (`tests/unit/test_contracts.py`). Сами пакеты собирает data (задача 6 в `tasks/data.md`)

### 0.6. API-контракт для ui

| Маршрут | Тело | Ответ |
|---|---|---|
| `POST /api/chat` | `{"session_id", "text"}` **или** `{"session_id", "action": {"type": "select_package", "package_id": "p2"}}` | SSE-поток событий |
| `GET /api/trips/{session_id}` | — | `TripState` (UI восстанавливает план после F5) |
| `POST /api/orders` | `{"session_id", "package_id", "idempotency_key"}` | `Order`; повтор с тем же ключом возвращает тот же заказ |

Ответ на вопрос агента UI отправляет обычным `text`.

Действия описаны в `agent/actions.py`. Интерфейс оркестратора: `handle(session_id, text)` и `handle_action(session_id, action)` → поток событий. До задач 1 и 4 маршрут плана отвечает `404`, а заказов — `501`: контракт виден в `/api/docs`, UI может на него опираться.
- [x] маршруты и схемы в `/api/docs`, тесты контракта — `tests/unit/test_api_contract.py`

- [x] **Шаг 0 готов:** PR влит в `main`, команда предупреждена

---

<a id="mvp-tasks"></a>
## Задачи MVP

### 1. Хранение состояния плана
Сделай таблицу `trip_state` (jsonb + version) и репозиторий `TripStateRepository`, а также `GET /api/trips/{session_id}`.
- [x] таблица, `SqlTripStateRepository` и маршрут готовы, интеграционные тесты на Postgres проходят
- [x] после F5 план восстанавливается (нужен оркестратор из задачи 2, который сохраняет план, и UI из `tasks/ui.md`): проверено в браузере, e2e читает план и историю как UI после F5

### 2. Линейный оркестратор MVP (`agent/orchestrator.py`)
Интерфейс `handle(...)` → поток событий сохраняется. Логика:
1. `intent.parse_request(text, catalog=…, today=…, base=текущий_запрос)` (ui) → `Success(TripRequest)` или `Failure(UnknownCity | AmbiguousCity | DatesInPast)`. `base` нужен, чтобы ответ на вопрос дополнял уже собранный запрос;
2. `clarifier.next_question(request, catalog)` (ui) → если не хватает обязательного (откуда, когда, возраст детей), событие `question`;
3. направление не задано → `planning.pick_destinations` (data) → `question` с вариантами направлений;
4. поиск через порты (параллельно, `asyncio.gather`) → `planning.simple_packages` (data) → `planning.check_package` (data) → `services.explanation.explain` (ui);
5. событие `plan` → текстовое резюме `delta`;
6. изменение условий («на 2 дня позже», «бюджет меньше») → `intent.parse_change` (ui) возвращает патч → применить к `TripRequest` → пересчитать (в MVP просто повторный поиск);
7. `select_package` → `plan` с `selected_package_id`.

События `step` по ходу: «Ищу перелёты Москва → Анталья…».
- [x] на фейках юнит-тест проходит все ветки: уточнение, выбор направления, пакеты, изменение, выбор пакета (`tests/unit/test_orchestrator.py`)

Решения по дизайну (24.10):
- ответ на вопрос разбирает `clarifier.apply_answer` (ui) по `PendingQuestion.slot`;
- даты поиска считает оркестратор (`agent/dates.py`): ближайшая суббота месяца не раньше чем через 3 дня, 7 ночей по умолчанию. Результат — `TripState.search`, запрос пользователя остаётся как есть;
- тексты резюме — шаблоны в `agent/texts.py`;
- `MvpOrchestrator` подключён в приложение в задаче 3, заглушка `StubOrchestrator` удалена;
- сигнатуры функций ui и data зафиксированы в `agent/toolkit.py`.

### 2а. Названия мест в плане
В запросе и рейсах места — slug, и UI нечего показать человеку. `TripState.places` (slug → название) заполняется оркестратором на каждом ходу для всех мест плана.
- [x] поле в контракте, заполнение в `MvpOrchestrator`, тесты; задание ui обновлено

### 3. Подключение реальных адаптеров
В `api/main.py` собрать `Toolkit` из функций ui и data, подставить синтетические источники data вместо фейков и заменить `StubOrchestrator` на `MvpOrchestrator`. `KnowledgeBase` rag подключается на этапе 1: в MVP её никто не вызывает.
- [x] в `docker compose up` тот же путь работает на синтетике из БД (`tests/integration/test_agent.py`, проверено в браузере)

### 4. Заказы и имитация оплаты
Таблица `orders` в `adapters/db/orders.py`, миграция, `POST /api/orders` с идемпотентностью по ключу. Номер заказа в формате `TP-<год>-<6 цифр>`. Зависит от задачи 1: пакет для заказа берётся из сохранённого плана.
- [x] повторный POST с тем же ключом не создаёт второй заказ
- [x] логика в `services/booking.py` (`place_order` возвращает `Result`), ошибки: нет плана / нет пакета → 404, по плану уже оплачен другой пакет / ключ занят другим пакетом → 409

### 5. e2e-тест MVP в CI и тег
Сценарий через API на поднятом стеке: запрос → ответ на вопрос → пакеты → выбор → заказ. Добавить в CI проверку «у Alembic одна голова».
- [x] в CI: одна голова Alembic, `alembic check`, интеграционные тесты (`docker compose --profile tests run --rm tests`)
- [x] e2e-сценарий через API: `tests/integration/test_e2e_api.py` ходит через шлюз, как браузер жюри, и проверяет SSE, историю, план и идемпотентность заказа
- [x] CI зелёный, на коммите в `main` стоит тег `mvp`

<a id="t6"></a>
### 6. Каждый день (на этапе 1 — L3)
Вливать PR команды, следить, чтобы `main` был зелёным, при необходимости обновлять задания в `tasks/`. Перед слиянием прогонять `scripts/ci.sh` локально на результате слияния и писать итог в комментарий к PR. GitHub Actions снова работает (с 2026-10-26), но локальный прогон остаётся основной проверкой. Итоги ревью переносить в задание участника (раздел «Ответы на PR»), а не оставлять только в комментариях GitHub.

---

## Этап 1 — модель

Контракт этапа описан и в заданиях data и rag (раздел «Контракты этапа 1»). Если меняешь его здесь, поправь и там.

<a id="l1"></a>
### L1. Контракт этапа 1 — первым делом, data и rag ждут
Один PR `feat(lead)!`:
- `agent/toolkit.py`: протоколы `Understand` и `Narrate`, `today` в `NextQuestion`, поля `understand` и `narrate` в `Toolkit` (не заданы — режим MVP);
- `ports.py`: `KnowledgeBase.context(request, destination, *, limit=4)`; `domain/offers.py`: `Package.sources: list[KnowledgeHit]`;
- оркестратор: в `AgentDeps` — `llm` (по умолчанию `NoLLM`) и `knowledge`. Есть LLM → `understand`; `None` или `LLMUnavailable` → правила MVP. После `explain` → `knowledge.context` → `narrate` (всегда; `LLMUnavailable` → шаблоны; упавшая база знаний → пустой список). С LLM ход показывает шаги «Разбираю запрос с помощью ИИ» и «Объясняю варианты с помощью ИИ», без LLM ход такой же, как в MVP;
- `api/main.py`: `make_llm(settings)`, `PostgresKnowledgeBase(sessions)`, `understand` и `narrate` в `TOOLKIT`; `cli.py`: `embed_index(session, make_llm(settings))` после `build_index`;
- заглушки с сигнатурами в зонах data и rag, как пустые файлы на шаге 0: `agent/understand.py` (`None`), `narrate` в `services/explanation.py` (пакеты как есть), `PostgresKnowledgeBase.context` (`[]`), `embed_index` (ничего). Необязательный `today` в `clarifier.next_question`, `"sources": []` в `ui/sample_plan.json`;
- `tests/fakes.py`: `FakeKnowledgeBase.context`; тесты оркестратора: LLM понимает первой, без ключа не вызывается, при сбое — правила; `narrate` получает фрагменты, её сбой оставляет шаблоны; упавшая база знаний не ломает план; `next_question` получает `today`.

Строку `COPY evals ./evals` в dev-образ добавит rag вместе с папкой `evals/` (задача 5): пока папки нет, сборка с этой строкой упала бы.

Готово, когда:
- [x] контракт в `main`, команда предупреждена («подтяните `main`»)
- [x] без ключа весь CI с e2e через шлюз зелёный: ход такой же, как в MVP

<a id="l2"></a>
### L2. Провайдер, модель и ключи
Решено 2026-10-26:
- **провайдер — OpenRouter.** Из России openrouter.ai отвечает 403 (Cloudflare), поэтому в VPN этот домен должен идти через туннель для всей системы: запросы идут из Docker;
- **модель для разработки — `dots-studio/dots-3-note-preview:free`:** ответ ~3 с, JSON по схеме ~10–18 с, «Турция» → Antalya разбирает верно. Бесплатные Gemma 4 отвечали 429 (перегружены у провайдера). Для показа — платная Gemma 4 (`google/gemma-4-31b-it`) с небольшим кредитом;
- **эмбеддинги** не выбраны: поиск полнотекстовый, пока rag не дойдёт до задачи 4. Модель нужна с размерностью 1024 (`EMBEDDING_DIM`), иначе — миграция;
- **ключи** — каждому свой ключ OpenRouter с лимитом трат; не в чат, не в репозиторий, не в PR;
- **организаторы** ключ не дают: у жюри, запускающего репозиторий, будет режим правил, а на защите агент работает с нашим ключом.

Готово, когда:
- [x] проверка ключа от rag (задача 2 в `tasks/rag.md`) проходит с нашим ключом: `complete` и `structured` ok (2026-10-29); с пустым `EMBEDDINGS_MODEL` пока код выхода 1 — правка у rag, задача 7; команда — в README
- [x] в README есть «Режим с LLM»

<a id="l4"></a>
### L4. Финиш
README по шаблону, видео-скринкаст (режим с моделью и без ключа), тег `submission` в дедлайн. Перед тегом решить, удалять ли `tasks/` из `main`.

<a id="l5"></a>
### L5. Пересборка плана
По условию трека при «а если на два дня позже?», «бюджет меньше», «с нами едет собака» агент перестраивает план, а не начинает поиск с нуля.
- `TripState.cache` (`SearchCache`): кандидаты последнего поиска. Поле исключено из `model_dump` — в событие `plan` и `GET /api/trips` не уходит, `SqlTripStateRepository` сохраняет его явно. Неполный поиск (упал источник) не кешируется;
- `agent/replanner.py`: `search_needs` — что искать заново (маршрут или число путешественников другие → всё; другой заезд → рейсы туда; другой выезд → обратные; любые новые даты → отели; новые рейсы туда или отели → трансферы; бюджет, `must`, животные → ничего), `describe_changes` — что поменялось для человека;
- оркестратор ищет только нужное, остальное берёт из кеша, а к резюме дописывает «Что поменялось»;
- заодно: шаги «с помощью ИИ» — только если модель действительно ответила (`AnsweredLLM`); локальный CI отключает ключ из `.env` (режим без LLM, как у жюри).

Готово, когда:
- [x] «бюджет до 200 000» пересобирает план без единого нового запроса к источникам, «на 2 дня позже» ищет только рейсы, отели и трансферы (тесты оркестратора и `tests/unit/test_replanner.py`)
- [x] в ответе агента — что поменялось: даты, цена по каждому уровню, тот же или другой отель

<a id="l6"></a>
### L6. Модель не может оборвать ход
После слияния задач data проверка с ключом показала: падения на ответах провайдера (`TypeError`, `BadRequestError 400`) обрывали ход «внутренней ошибкой», а бесплатная модель думала 9–64 с на сообщение. Правило: модель — улучшение поверх правил, а не их замена.
- любое исключение из `understand` / `narrate` → откат на правила; у `narrate` — повтор без модели (`NoLLM`), чтобы сравнения соседей не терялись;
- лимит `LLM_STEP_TIMEOUT` (по умолчанию 15 с) на каждый шаг с моделью, дольше — правила;
- ответ ровно текстом кнопки вопроса модель не получает: его разбирает `apply_answer`;
- `COPY evals ./evals` в dev-образ: 78 кейсов разбора data теперь проверяются в CI (раньше тест пропускался).

Готово, когда:
- [x] тесты оркестратора: падение `understand`, медленная модель, падение `narrate` с сохранением сравнений, кнопка без модели

<a id="l7"></a>
### L7. Ключ для жюри в `secrets.env.age`
Организаторы просят передать ключи только зашифрованными: `secrets.env.age` в корне репозитория, шифрование [age](https://age-encryption.org) их публичным ключом `age1932fu7f70rwyfhaxflyfszz4gf6avxwc95wc0yjwm6zns9tspycqpgdnc0`.
- отдельный ключ OpenRouter только для жюри, с лимитом трат; модель — `dots-studio/dots-3-note-preview:free`;
- шифруется `.env.jury` (закрыт в `.gitignore` правилом `.env.*`): только переменные LLM, остальное — по умолчанию; UTF-8 без BOM, LF, `NAME=value` без кавычек;
- `age -r <ключ> -o secrets.env.age .env.jury` — всегда через `-o`, без `>` и `|` (в PowerShell они портят файл), без `-a`; после правки `.env.jury` — зашифровать заново;
- `.env.example` — все переменные без значений (так просят организаторы), умолчания в комментариях; `Settings` с `env_ignore_empty=True`, чтобы пустые значения не ломали запуск;
- `secrets.env.age` в `.dockerignore`: в образ он не нужен.

Проверка перед сдачей (чек-лист организаторов):
- [x] `.env.example` в репозитории, все переменные без значений
- [x] `.env` в `.gitignore`, `git ls-files .env` ничего не выводит
- [ ] `secrets.env.age` в корне, закоммичен и есть в теге сдачи `submission`
- [x] `secrets.env.age` не пустой, ключ в нём не читается (проверено: бинарный age, один получатель, ключа и имён переменных открытым текстом нет, gitleaks чист)
- [x] ключ отдельный, для жюри (не совпадает с рабочим, OpenRouter отвечает 200)
- [x] в README указаны провайдер, модель и шаги запуска с ключом

## После этапа 1 (детализируется позже)
- машина стадий вместо линейного пайплайна; MVP-путь остаётся режимом без LLM;
- версии `TripState` и «верни как было»;
- пересборка по графу зависимостей + diff для пользователя;
- работа после покупки: ранний заезд, смена дат, напоминания.

<a id="edit-tasks"></a>
## Как править задания команды
Если ветка участника не впереди `main`, задание можно поправить в `team/lead` и отдать через PR в `main`: участник получит его при `git pull origin main`. Так сделано 2026-10-26, когда вместе с заданиями менялись зоны в `AGENTS.md`. Если в ветке участника есть свои коммиты, правь прямо в ней:

```bash
git switch team/rag
git pull
# правка tasks/rag.md + строка в таблице «Правки лида»
git add tasks/rag.md
git commit -m "docs(tasks): уточнить задачу 3 для rag"
git push
git switch team/lead
```
После этого напиши человеку: «обновил задание, сделай `git pull`».

<a id="changes"></a>
## Правки лида

| Дата | Что изменено |
|---|---|
| 2026-10-23 | первая версия |
| 2026-10-23 | шаг 0 выполнен в коде (кроме merge в `main`). Уточнения по ходу: `EMBEDDING_DIM` живёт в `knowledge.py`; `children_ages` допускает `None` («возраст не известен»); `LLMUnavailable` объявлен в `ports.py`; действия вынесены в `agent/actions.py`; критерий 0.5 сужен до «фейки реализуют порты и данных хватает на три пакета» — сами пакеты собирает data |
| 2026-10-24 | задачи 1 и 4 сделаны (кроме F5, который ждёт оркестратора и UI). Задача 4 зависит от 1. Добавлены доменные ошибки бронирования (`BookingError`), `sample_package()` в `tests/fakes.py`, интеграционные тесты и сервис `tests` в compose; в CI — проверка одной головы Alembic (часть задачи 5) |
| 2026-10-24 | задача 2 сделана. Изменения контракта: `PendingQuestion.slot` (обязательное поле), `TripState.search` (`SearchWindow`), `agent/toolkit.py` с сигнатурами функций ui и data; `clarifier.next_question` теперь возвращает `PendingQuestion`, добавлена `clarifier.apply_answer`. Текст вопроса сохраняется в историю чата |
| 2026-10-24 | GitHub Actions не запускаются из-за биллинга организации. Добавлен `scripts/ci.sh` — все шаги CI одной командой, его же вызывает workflow. CI теперь только на PR (без повторного прогона после слияния в main), без черновиков и PR с одной документацией, с отменой устаревших прогонов |
| 2026-10-24 | безопасность данных: порты pgAdmin и БД для разработки только на `127.0.0.1`; pgAdmin в серверном режиме со входом (раньше пускал без пароля), пароль — из `.env`; `.gitignore` и `.dockerignore` закрывают все `.env.*`, ключи и сертификаты; gitleaks в `scripts/ci.sh`; хуки `.githooks` (`pre-commit` — секреты, `pre-push` — запрет push в `main`); раздел «Безопасность» в README и `AGENTS.md` |
| 2026-10-25 | задача 2а: контракт `TripState.places` (slug → название), оркестратор заполняет его на каждом ходу; обещано ui в ревью PR #7 |
| 2026-10-26 | задача 3: в приложении `MvpOrchestrator` с функциями ui и data и синтетикой из БД, заглушка удалена. Подключение `KnowledgeBase` перенесено на этап 1 |
| 2026-10-26 | задача 5: e2e через шлюз в интеграционных тестах, сервис `tests` теперь ждёт поднятый стек; задача 1 закрыта (F5). Тег `mvp` ставится после слияния, правок разборщика от ui не ждём |
| 2026-10-26 | тег `mvp` поставлен. Этап 1 (модель): задачи L1–L4, понимание запроса и объяснения переходят от ui к data, нагрузка лида и ui минимальная. Задания data, rag и ui переписаны под этап 1 с шапкой-навигацией и ответами на PR |
| 2026-10-26 | задача L1: контракт этапа 1 в коде, заглушки в зонах data и rag, `make_llm` и база знаний в приложении, `embed_index` в bootstrap. `COPY evals` в dev-образ — за rag вместе с папкой `evals/` |
| 2026-10-26 | GitHub Actions в организации снова работает. Решение: локальный `scripts/ci.sh` остаётся обязательной проверкой перед PR и слиянием, прогон после слияния в `main` не возвращаем |
| 2026-10-26 | задача L5: пересборка плана из кеша прошлого поиска и «Что поменялось» в ответе; честные шаги «с помощью ИИ»; локальный CI без ключа LLM |
| 2026-10-26 | задача L2: OpenRouter через VPN, модель для разработки — dots-3 (free), для показа — платная Gemma 4; раздел «Режим с LLM» в README, пример в `.env.example` |
| 2026-10-28 | задача L6: страховка оркестратора от любых сбоев модели, лимит `LLM_STEP_TIMEOUT`, кнопки без модели; `COPY evals` в dev-образ |
| 2026-10-28 | задача L7: ключ для жюри в `secrets.env.age` (age, публичный ключ организаторов); `.env.example` без значений, пустые переменные — значения по умолчанию |
| 2026-10-28 | задача 7 data (правки `understand`) сделана лидом: data без компьютера, а с ключом ломался базовый сценарий |
| 2026-10-29 | L2 закрыта: проверка ключа от rag в README; там же — необязательная модель эмбеддингов и лимиты бесплатных моделей OpenRouter (50 запросов в день на аккаунт, 1000 после покупки от 10 $) |
