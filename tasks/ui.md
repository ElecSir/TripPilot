# Задание: ui — диалог и интерфейс

**Ветка:** `team/ui` · **Файл:** `tasks/ui.md` · **Владелец задания:** лид (правит лид, история правок внизу)

> Документ читают и человек, и ИИ-ассистент. Ассистенту: сначала прочитай `AGENTS.md`, затем этот файл целиком.
> Статус задач отмечай галочками `[x]` прямо здесь.

## Цель

Всё, что пользователь видит и читает: интерфейс, понимание его сообщения, уточняющие вопросы и объяснения выбора. Агент должен показывать результат структурой (карточки, корзина), а не пересказывать выдачу в чате: в задании хакатона это прямо названо «не решением». В MVP всё работает **без LLM**: правила и шаблоны.

## Как начать

```bash
git clone https://github.com/ostrovok-hackathon-2026/gradient-descent.git
cd gradient-descent
git switch team/ui
cp docker-compose.override.example.yml docker-compose.override.yml
docker compose up --build
```

Откройте http://localhost:8080. С override-файлом Streamlit сам перезагружается при правке `src/`. Сейчас UI — заглушка в `src/trip_pilot/ui/app.py`: слева чат, справа панель «Ваша поездка».

## Твоя зона

**Можно менять:** `ui/`, `.streamlit/`, `agent/intent.py`, `agent/clarifier.py`, `agent/prompts/`, `services/explanation.py`, тесты к этому.

**Нельзя без лида:** `domain/`, `ports.py`, `agent/events.py`, `agent/orchestrator.py`, `api/`, `pyproject.toml` / `uv.lock`, чужие зоны.

## Контракты, на которые опираешься

Контракты лежат в `main`: `domain/`, `agent/events.py`, `agent/actions.py`, **`agent/toolkit.py`** (сигнатуры твоих функций). Ниже — выжимка. Если она разойдётся с кодом в `main`, прав код.

```python
# domain/request.py — его собирает твой разборщик
Assumption: field, value, reason                     # «додумал сам» → чип в UI
Party:      adults (≥1, по умолчанию 2), children_ages: list[int | None], pets: list["dog" | "cat" | "other"]
            # None в children_ages — ребёнок есть, возраст ещё не известен
TripRequest: origin (slug | None), destination (slug | None), month (1–12 | None), date_from, nights,
             party, budget (Decimal | None, на всех), tags ("sea", "city", …), must ("pets_allowed",
             "direct_only", "kids_friendly"), assumptions
# domain/trip_state.py
PendingQuestion: slot ("origin" | "when" | "children_ages" | "destination"), text, options
SearchWindow:    check_in, check_out, nights, assumptions     # даты, по которым шёл поиск
# domain/errors.py: UnknownCity(raw), AmbiguousCity(raw, candidates), DatesInPast(start), …
# domain/offers.py: Destination(slug, name, …), Package(id, tier, destination, outbound, inbound, hotel,
#                   transfer, check_in, check_out, nights, total, price_breakdown, issues, why, tradeoffs, risks)
```

Готовый пакет для тестов и примеров: `from tests.fakes import sample_package`.

**События агента** (`agent/events.py`): `stage`, `step`, `question` (`text`, `options`), `plan` (`data`), `delta`, `error`, `done`. Каждый ход агента заканчивается событием `plan` с полным `TripState`: панель всегда рисует последнее состояние.

**Событие `plan`:** `data` = `TripState`:
```json
{"session_id": "…", "version": 3, "stage": "compare",
 "request": {"origin": "moscow", "destination": "antalya", "month": 11, "date_from": null, "nights": null,
             "party": {"adults": 2, "children_ages": [5], "pets": []}, "budget": "150000",
             "assumptions": [{"field": "party", "value": "2 взрослых", "reason": "состав не указан"}]},
 "search": {"check_in": "2026-11-07", "check_out": "2026-11-14", "nights": 7,
            "assumptions": [{"field": "nights", "value": "7", "reason": "длительность не указана — неделя"},
                            {"field": "date_from", "value": "2026-11-07", "reason": "ноябрь → заезд в ближайшую субботу, 7 ноября"}]},
 "packages": [{"id": "p1", "tier": "economy", "total": "84800", "hotel": {"name": "…", "stars": 3}, "why": ["…"], "tradeoffs": ["…"], "risks": ["…"], "...": "..."}],
 "places": {"antalya": "Анталья", "moscow": "Москва"},
 "pending_question": null, "selected_package_id": null, "order": null}
```

- **`request`** — то, что сказал пользователь («в ноябре»). **`search`** — во что это превратилось при поиске («7–14 ноября») и что агент при этом додумал. Чипы допущений = `request.assumptions` + `search.assumptions`.
- **`pending_question`** = `{"slot", "text", "options"}`, пока агент ждёт ответа. По нему кнопки восстанавливаются после F5.
- **`places`** — названия всех мест плана: slug → «Москва». В запросе (`origin`, `destination`) и в рейсах (`outbound` / `inbound`: `origin`, `destination`) места приходят как slug, а человеку показывай `places[slug]`, например «Москва → Анталья» и «из Москвы ✎». Если slug вдруг нет в `places`, выводи сам slug. В `sample_plan.json` это поле тоже нужно.

**API** (делает лид, всё уже в `main`):
- `POST /api/chat` с `{"session_id", "text"}` → SSE. Ответ на вопрос агента — обычный `text`, **ровно текст кнопки**.
- `POST /api/chat` с `{"session_id", "action": {"type": "select_package", "package_id": "p2"}}` → SSE с обновлённым `plan`.
- `GET /api/trips/{session_id}` → `TripState`, плана нет → 404.
- `POST /api/orders` с `{"session_id", "package_id", "idempotency_key"}` → 201 и `{"id": "TP-2026-000123", "package_id", "total", "status": "paid", "created_at"}`. Повтор с тем же ключом → тот же заказ; нет плана или пакета → 404; по плану уже оплачен другой пакет → 409.

Маршруты настоящие, но в приложении пока работает заглушка агента: план в БД появится, когда лид подключит оркестратор (его задача 3, после твоих функций). До этого панель и корзина работают на `sample_plan.json`.

**Функции, которые вызывает оркестратор лида** (точные сигнатуры — в `agent/toolkit.py`, не меняй их без согласования):
```python
# agent/intent.py
def parse_request(text: str, *, catalog: list[Destination], today: date,
                  base: TripRequest | None = None) -> Result[TripRequest, DomainError]: ...
def parse_change(text: str, current: TripRequest, *, today: date) -> dict | None: ...   # патч или None
# agent/clarifier.py
def next_question(request: TripRequest, catalog: list[Destination]) -> PendingQuestion | None: ...
def apply_answer(question: PendingQuestion, text: str, request: TripRequest, *,
                 catalog: list[Destination], today: date) -> Result[TripRequest, DomainError] | None: ...
# services/explanation.py
def explain(package: Package, request: TripRequest) -> Package: ...   # заполняет why / tradeoffs / risks
```

Как оркестратор их использует:
1. агент ждёт ответа → `apply_answer`; вернула `None` → это не ответ, дальше как обычное сообщение;
2. план уже есть → `parse_change`; `current` приходит **с датами последнего поиска** (`date_from`, `nights` заполнены), сдвиг считай от них;
3. иначе → `parse_request(..., base=текущий запрос)`;
4. затем `next_question`. Если вернула `None`, а направления нет, вопрос «Куда?» с вариантами задаёт сам оркестратор (`slot="destination"`), но ответ на него разбирает твоя `apply_answer`.

Даты поиска из «в ноябре» считает оркестратор, а не разборщик: `parse_request` кладёт `month=11`, `date_from` оставляет пустым.

---

## Задачи MVP

### 1. Панель поездки на образце данных — можно начинать сразу
Положи пример `plan` в `src/trip_pilot/ui/sample_plan.json` (по образцу выше, три пакета). Сделай правую панель:
- **допущения** — чипы («из Москвы ✎», «7 ночей ✎») из `request.assumptions` и `search.assumptions`; добавь в `sample_plan.json` поле `search` и `slot` у `pending_question` по образцу выше;
- **три карточки пакетов** (`st.container(border=True)` в `st.columns(3)`): уровень, полная цена, ночи, отель и звёзды, перелёт туда и обратно (время местное), трансфер, 2–3 пункта «почему», «чем жертвуем», «риски» (из `issues` и `risks`, выделены);
- кнопка «Выбрать» отправляет `select_package`;
- метка «демо-данные».

Пока API не отдаёт `plan`, панель берёт образец (флаг в коде, убрать после интеграции).

Готово, когда:
- [x] на ширине ноутбука и телефона карточки читаются

### 2. Корзина и имитация оплаты — можно начинать сразу
После выбора пакета панель показывает корзину: состав, разбивку цены из `price_breakdown`, итог. Кнопка «Оформить» открывает `st.dialog`:
- никаких полей карты, только «Оплатить (имитация)»;
- `POST /api/orders` с `idempotency_key` = uuid, созданный один раз на попытку;
- экран «Заказ TP-… оформлен».

Готово, когда:
- [x] двойной клик не создаёт два заказа (тот же ключ)

### 3. Вопросы агента кнопками
Событие `question` с `options` → `st.pills` под сообщением агента. Выбор отправляется как обычный `text`, **ровно текст кнопки**: по нему `apply_answer` узнаёт ответ. Свободный ввод остаётся доступен. Текст вопроса сохраняется в истории чата сам (это делает API).
- [ ] вопрос и варианты не пропадают после F5 (берутся из `TripState.pending_question`)

### 4. Разбор запроса правилами (`agent/intent.py`)
Сначала **таблица тестов** (≥ 40 фраз → ожидаемые поля), потом код. Что извлекаем:
- **месяц и даты:** «в ноябре», «на майские», «с 5 по 12 декабря», «через две недели»; прошедшая дата → `Failure(DatesInPast)`;
- **длительность:** «на неделю» = 7, «на выходные» = 2, «на 10 дней»;
- **города:** нечётко по названиям из `catalog` и алиасам («Питер», «СПб», «Масква» → moscow) через `rapidfuzz`; неизвестный → `UnknownCity`, несколько похожих → `AmbiguousCity`; «из …» = `origin`, «в …» = `destination`;
- **состав:** «вдвоём» = 2, «втроём», «одна», «с мужем»; «с ребёнком 5 лет» → `children_ages=[5]`; «с детьми» без возраста → ребёнок есть, возраст неизвестен;
- **животные:** «с собакой», «с котом» → `pets` + `must: pets_allowed`;
- **бюджет:** «до 150 000», «150к», «тысяч 100»; «недорого» → допущение, а не число;
- **теги:** «море», «тёплое», «город», «горы»;
- **база:** если передан `base`, новое дополняет и перекрывает старое.

Всё додуманное записывается в `assumptions` с причиной.

`parse_change` возвращает патч — словарь полей `TripRequest` с **новыми значениями**, посчитанными от `current`:
- «на два дня позже» → `{"date_from": <current.date_from + 2 дня>}`;
- «бюджет меньше» → `{"budget": <current.budget × 0.8>}` + допущение; «до 100к» → `{"budget": Decimal("100000")}`;
- «без пересадок» → `{"must": [...current.must, "direct_only"]}`;
- «с нами едет собака» → `{"party": {...current.party, "pets": ["dog"]}, "must": [..., "pets_allowed"]}`.

Не изменение → `None`.

Готово, когда:
- [ ] все фразы из таблицы проходят; функции чистые (без IO), `today` передаётся параметром

### 5. Уточнитель (`agent/clarifier.py`)
`next_question` возвращает `PendingQuestion(slot, text, options)` и спрашивает **одно**, самое важное, в порядке:
1. `slot="origin"` (нет `origin`) — варианты: 3 города вылета из каталога (Москва, Санкт-Петербург, Казань). Кнопку «Другой» не делай: свой город человек просто напишет;
2. `slot="when"` (нет ни `month`, ни `date_from`) — ближайшие 3 месяца («Ноябрь», «Декабрь», «Январь»);
3. `slot="children_ages"` (в `children_ages` есть `None`) — «до 2», «2–6», «7–12», «13–17».

Остальное не спрашиваем: это допущения. Всё известно → `None`. Направление (`slot="destination"`) не спрашивай: этот вопрос задаёт оркестратор.

`apply_answer(question, text, request, catalog=…, today=…)` разбирает ответ на вопрос с этим `slot`:
- `origin` / `destination` — текст кнопки или свободный ввод → slug по каталогу (нечётко, как в разборщике); неизвестный город → `Failure(UnknownCity)`;
- `when` — название месяца → `month`; дата → `date_from` (прошедшая → `Failure(DatesInPast)`);
- `children_ages` — диапазон → характерный возраст вместо `None` («до 2» → 1, «2–6» → 4, «7–12» → 9, «13–17» → 15) и допущение с причиной; точный возраст («5 лет», «5») → 5.

Текст не похож на ответ на этот вопрос → `None`: оркестратор разберёт его как обычное сообщение.
- [ ] юнит-тесты на каждый случай `next_question` и на каждый `slot` в `apply_answer`, включая `None`

### 6. Объяснения шаблонами (`services/explanation.py`)
`explain(package, request)` заполняет поля:
- **why**: связь с запросом — «прямой рейс 4 ч — вы просили без долгих перелётов», «300 м до пляжа», «бесплатная отмена»;
- **tradeoffs**: чем уступает соседним пакетам — «на 1,2 км дальше от моря, чем комфорт»;
- **risks**: из `package.issues`, невозвратный тариф.

Только факты из `package` и `request`, никаких выдуманных чисел.
- [ ] юнит-тесты: каждое утверждение опирается на поле пакета

---

## После MVP (детализируется позже)
- разбор запроса через LLM (`structured()` из клиента rag) с откатом на правила;
- редактируемые чипы допущений (правка → `parse_change`);
- таблица сравнения пакетов, таймлайн стыковок (Plotly), карта (отель, пляж, аэропорт);
- страницы «Мои поездки» и «Метрики агента» (`st.navigation`);
- (по желанию) Telegram-бот на `aiogram` поверх того же API.

## Как сдавать работу
- Коммиты делает человек после просмотра diff. Формат: Conventional Commits на русском, только суть, например `feat(ui): добавить карточки пакетов`.
- Перед PR выполни проверку из `AGENTS.md`. PR `team/ui` → `main` открывай, как только задача готова, не копи. Слияние обычным merge commit.
- Не реже раза в день: `git pull origin main`.

## Правки лида

| Дата | Что изменено |
|---|---|
| 2026-10-23 | первая версия |
| 2026-10-24 | контракт под оркестратор MVP: у `PendingQuestion` появился `slot`; `next_question` возвращает `PendingQuestion` (а не `QuestionEvent`); новая функция `apply_answer`; в `TripState` появилось `search` (даты поиска и их допущения); `children_ages` допускает `None`; `/api/trips` и `/api/orders` работают по-настоящему; точные сигнатуры — `agent/toolkit.py` |
| 2026-10-25 | в `TripState` появилось `places` (slug → название места): города в карточках, рейсах и чипах берутся оттуда, а не выводятся slug'ом. Обещано в ревью PR #7 |
