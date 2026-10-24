# Задание: лид — инфраструктура, контракты, оркестратор

**Ветка:** `team/lead` · **Файл:** `tasks/lead.md` · **Владелец задания:** лид

> Документ читают и человек, и ИИ-ассистент. Ассистенту: сначала прочитай `AGENTS.md`, затем этот файл целиком.
> Статус задач отмечай галочками `[x]` прямо здесь.

## Цель

Склеить систему. Первым делом выдать команде контракты, чтобы трое остальных работали параллельно. Затем собрать из их частей MVP: весь путь от сообщения до номера заказа, без LLM, с e2e-тестом в CI и тегом `mvp`.

## Твоя зона

**Можно менять:** `docker/`, `.github/`, `api/`, `domain/`, `ports.py`, `config.py`, `cli.py`, `logs.py`, `agent/events.py`, `agent/actions.py`, `agent/orchestrator.py`, `agent/replanner.py`, `services/booking.py`, `services/post_purchase.py`, `adapters/db/{base,chat,orders,models,engine,repositories}.py`, `migrations/env.py`, `tests/fakes.py`, `AGENTS.md`, `README.md`, `docs/`, `tasks/*.md` (задания команды).

**Нельзя без владельца:** `rag/`, `adapters/llm/` (rag); `seed/`, `planning/`, `adapters/sources/`, `adapters/db/inventory.py` (data); `ui/`, `agent/intent.py`, `agent/clarifier.py`, `services/explanation.py` (ui).

---

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

## Задачи MVP

### 1. Хранение состояния плана
Сделай таблицу `trip_state` (jsonb + version) и репозиторий `TripStateRepository`, а также `GET /api/trips/{session_id}`.
- [x] таблица, `SqlTripStateRepository` и маршрут готовы, интеграционные тесты на Postgres проходят
- [ ] после F5 план восстанавливается (нужен оркестратор из задачи 2, который сохраняет план, и UI из `tasks/ui.md`)

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
- в приложении пока `StubOrchestrator`, `MvpOrchestrator` подключается в задаче 3;
- сигнатуры функций ui и data зафиксированы в `agent/toolkit.py`.

### 3. Подключение реальных адаптеров
В `api/main.py` подставить репозитории data и `KnowledgeBase` rag вместо фейков, собрать `Toolkit` из функций ui и data и заменить `StubOrchestrator` на `MvpOrchestrator`.
- [ ] в `docker compose up` тот же путь работает на синтетике из БД

### 4. Заказы и имитация оплаты
Таблица `orders` в `adapters/db/orders.py`, миграция, `POST /api/orders` с идемпотентностью по ключу. Номер заказа в формате `TP-<год>-<6 цифр>`. Зависит от задачи 1: пакет для заказа берётся из сохранённого плана.
- [x] повторный POST с тем же ключом не создаёт второй заказ
- [x] логика в `services/booking.py` (`place_order` возвращает `Result`), ошибки: нет плана / нет пакета → 404, по плану уже оплачен другой пакет / ключ занят другим пакетом → 409

### 5. e2e-тест MVP в CI и тег
Сценарий через API на поднятом стеке: запрос → ответ на вопрос → пакеты → выбор → заказ. Добавить в CI проверку «у Alembic одна голова».
- [x] в CI: одна голова Alembic, `alembic check`, интеграционные тесты (`docker compose --profile tests run --rm tests`)
- [ ] e2e-сценарий через API
- [ ] CI зелёный, на коммите в `main` стоит тег `mvp`

### 6. Каждый день
Вливать PR команды, следить, чтобы `main` был зелёным, при необходимости обновлять задания в `tasks/`. Пока GitHub Actions в организации не запускаются (биллинг), перед слиянием прогонять `scripts/ci.sh` на ветке PR локально и писать итог в комментарий к PR.

## После MVP (детализируется позже)
- машина стадий вместо линейного пайплайна; MVP-путь остаётся режимом без LLM;
- версии `TripState` и «верни как было»;
- пересборка по графу зависимостей + diff для пользователя;
- работа после покупки: ранний заезд, смена дат, напоминания;
- README, видео-скринкаст, тег `submission`. Перед тегом решить, удалять ли `tasks/` из `main`.

## Как править задания команды
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

## Правки лида

| Дата | Что изменено |
|---|---|
| 2026-10-23 | первая версия |
| 2026-10-23 | шаг 0 выполнен в коде (кроме merge в `main`). Уточнения по ходу: `EMBEDDING_DIM` живёт в `knowledge.py`; `children_ages` допускает `None` («возраст не известен»); `LLMUnavailable` объявлен в `ports.py`; действия вынесены в `agent/actions.py`; критерий 0.5 сужен до «фейки реализуют порты и данных хватает на три пакета» — сами пакеты собирает data |
| 2026-10-24 | задачи 1 и 4 сделаны (кроме F5, который ждёт оркестратора и UI). Задача 4 зависит от 1. Добавлены доменные ошибки бронирования (`BookingError`), `sample_package()` в `tests/fakes.py`, интеграционные тесты и сервис `tests` в compose; в CI — проверка одной головы Alembic (часть задачи 5) |
| 2026-10-24 | задача 2 сделана. Изменения контракта: `PendingQuestion.slot` (обязательное поле), `TripState.search` (`SearchWindow`), `agent/toolkit.py` с сигнатурами функций ui и data; `clarifier.next_question` теперь возвращает `PendingQuestion`, добавлена `clarifier.apply_answer`. Текст вопроса сохраняется в историю чата |
| 2026-10-24 | GitHub Actions не запускаются из-за биллинга организации. Добавлен `scripts/ci.sh` — все шаги CI одной командой, его же вызывает workflow. CI теперь только на PR (без повторного прогона после слияния в main), без черновиков и PR с одной документацией, с отменой устаревших прогонов |
