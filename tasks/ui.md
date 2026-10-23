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

Лид сегодня кладёт их в `main` (шаг 0). Ниже — черновик. Если он разойдётся с кодом в `main`, прав код.

```python
# domain/request.py — его собирает твой разборщик
Assumption: field, value, reason                     # «додумал сам» → чип в UI
Party:      adults (≥1, по умолчанию 2), children_ages: list[int], pets: list[str]
TripRequest: origin (slug | None), destination (slug | None), month (1–12 | None), date_from, nights,
             party, budget (Decimal | None, на всех), tags ("sea", "city", …), must ("pets_allowed",
             "direct_only", "kids_friendly"), assumptions
# domain/errors.py: UnknownCity(raw), AmbiguousCity(raw, candidates), DatesInPast(start), …
# domain/offers.py: Destination(slug, name, …), Package(id, tier, destination, outbound, inbound, hotel,
#                   transfer, check_in, check_out, nights, total, price_breakdown, issues, why, tradeoffs, risks)
```

**События агента** уже есть в `agent/events.py`: `stage`, `step`, `question` (`text`, `options`), `plan` (`data`), `delta`, `error`, `done`.

**Событие `plan`:** `data` = `TripState`:
```json
{"session_id": "…", "version": 3, "stage": "compare",
 "request": {"origin": "moscow", "destination": "antalya", "month": 11, "nights": 7, "party": {"adults": 2, "children_ages": [5], "pets": []},
             "budget": "150000", "assumptions": [{"field": "nights", "value": "7", "reason": "«на неделю»"}]},
 "packages": [{"id": "p1", "tier": "economy", "total": "118400.00", "hotel": {"name": "…", "stars": 4}, "why": ["…"], "tradeoffs": ["…"], "risks": ["…"], "...": "..."}],
 "pending_question": null, "selected_package_id": null, "order": null}
```

`pending_question` = `{"text", "options"}`, пока агент ждёт ответа. По нему кнопки восстанавливаются после F5.

**API** (делает лид):
- `POST /api/chat` с `{"session_id", "text"}` → SSE. Ответ на вопрос агента — обычный `text`.
- `POST /api/chat` с `{"session_id", "action": {"type": "select_package", "package_id": "p2"}}` → SSE с обновлённым `plan`.
- `GET /api/trips/{session_id}` → `TripState`.
- `POST /api/orders` с `{"session_id", "package_id", "idempotency_key"}` → `{"id": "TP-2026-000123", "status": "paid", "total": "…"}`.

**Функции, которые вызывает оркестратор лида** (сигнатуры не меняй без согласования):
```python
# agent/intent.py
def parse_request(text: str, *, catalog: list[Destination], today: date,
                  base: TripRequest | None = None) -> Result[TripRequest, DomainError]: ...
def parse_change(text: str, current: TripRequest, *, today: date) -> dict | None: ...   # патч или None
# agent/clarifier.py
def next_question(request: TripRequest, catalog: list[Destination]) -> QuestionEvent | None: ...
# services/explanation.py
def explain(package: Package, request: TripRequest) -> Package: ...   # заполняет why / tradeoffs / risks
```

---

## Задачи MVP

### 1. Панель поездки на образце данных — можно начинать сразу
Положи пример `plan` в `src/trip_pilot/ui/sample_plan.json` (по образцу выше, три пакета). Сделай правую панель:
- **допущения** — чипы («из Москвы ✎», «7 ночей ✎»);
- **три карточки пакетов** (`st.container(border=True)` в `st.columns(3)`): уровень, полная цена, ночи, отель и звёзды, перелёт туда и обратно (время местное), трансфер, 2–3 пункта «почему», «чем жертвуем», «риски» (из `issues` и `risks`, выделены);
- кнопка «Выбрать» отправляет `select_package`;
- метка «демо-данные».

Пока API не отдаёт `plan`, панель берёт образец (флаг в коде, убрать после интеграции).

Готово, когда:
- [ ] на ширине ноутбука и телефона карточки читаются

### 2. Корзина и имитация оплаты — можно начинать сразу
После выбора пакета панель показывает корзину: состав, разбивку цены из `price_breakdown`, итог. Кнопка «Оформить» открывает `st.dialog`:
- никаких полей карты, только «Оплатить (имитация)»;
- `POST /api/orders` с `idempotency_key` = uuid, созданный один раз на попытку;
- экран «Заказ TP-… оформлен».

Готово, когда:
- [ ] двойной клик не создаёт два заказа (тот же ключ)

### 3. Вопросы агента кнопками
Событие `question` с `options` → `st.pills` под сообщением агента. Выбор отправляется как обычный `text`. Свободный ввод остаётся доступен.
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
`next_question` спрашивает **одно**, самое важное, в порядке:
1. откуда (нет `origin`) — варианты: 3 города вылета из каталога + «Другой»;
2. когда (нет ни `month`, ни `date_from`) — ближайшие 3 месяца;
3. возраст детей (дети есть, возраста нет) — «до 2», «2–6», «7–12», «13–17».

Остальное не спрашиваем: это допущения. Всё известно → `None`.
- [ ] юнит-тесты на каждый случай

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
