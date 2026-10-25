# Задание: data — синтетические данные, поиск, планирование

**Ветка:** `team/data` · **Файл:** `tasks/data.md` · **Владелец задания:** лид (правит лид, история правок внизу)

> Документ читают и человек, и ИИ-ассистент. Ассистенту: сначала прочитай `AGENTS.md`, затем этот файл целиком.
> Статус задач отмечай галочками `[x]` прямо здесь.

## Цель

Дать агенту правдоподобный каталог (отели, перелёты, поезда, трансферы) и логику, которая собирает из него три пакета и проверяет стыковки. Это «мозг» подбора. Здесь нет LLM, только детерминированный код, поэтому всё покрывается тестами.

## Как начать

```bash
git clone https://github.com/ostrovok-hackathon-2026/gradient-descent.git
cd gradient-descent
git switch team/data
docker compose up --build
```

Откройте http://localhost:8080. Справочник направлений лежит в `data/reference/destinations.json` и загружается через `seed/reference.py`.

## Твоя зона

**Можно менять:** `seed/`, `data/reference/`, `adapters/sources/`, `adapters/db/inventory.py` и `adapters/db/reference.py` (уже есть в `main`), `planning/`, свои миграции, тесты к этому.

**Нельзя без лида:** `domain/`, `ports.py`, `api/`, `migrations/env.py`, `pyproject.toml` / `uv.lock`, чужие зоны.

## Контракты, на которые опираешься

**Сначала подтяни `main`: `git pull origin main`.** Там уже лежат контракты (`domain/`, `ports.py`), сигнатуры твоих функций (`agent/toolkit.py`), фейки (`tests/fakes.py`), оркестратор, который эти функции вызывает (`agent/orchestrator.py`), и скрипт проверки `scripts/ci.sh`. Ниже — выжимка. Если она разойдётся с кодом в `main`, прав код.

```python
# domain/offers.py — эти модели ты наполняешь данными (деньги Decimal, время с часовым поясом)
Destination: slug, name, country, iata, lat, lon, timezone, tags: list[str], warm_months: list[int]
Hotel:       id, destination, name, stars, price_per_night, meal ("RO"|"BB"|"HB"|"AI"), free_cancellation,
             pets_allowed, kids_friendly, beach_distance_m | None, check_in_time, check_out_time, rating, is_synthetic
Leg:         id, mode ("flight"|"train"), origin, destination, depart_at, arrive_at, price (за пассажира),
             stops, carrier, baggage_included, pets_allowed, is_synthetic
Transfer:    id, destination, hotel_id, kind ("taxi"|"shuttle"), duration_min, price (за машину в одну сторону),
             capacity, pets_allowed
Package:     id, tier ("economy"|"balance"|"comfort"), destination, outbound, inbound, hotel, transfer,
             check_in, check_out, nights, total, price_breakdown, issues, why, tradeoffs, risks

# ports.py — ты реализуешь эти порты
class DestinationCatalog(Protocol):
    async def all(self) -> list[Destination]: ...
class HotelSource(Protocol):
    async def search(self, destination: str, check_in: date, check_out: date, party: Party) -> list[Hotel]: ...
class TransportSource(Protocol):
    async def search(self, origin: str, destination: str, day: date, party: Party) -> list[Leg]: ...
class TransferSource(Protocol):
    async def search(self, hotel_id: int, arrive_at: datetime, party: Party) -> list[Transfer]: ...
```

`Party`: `adults`, `children_ages` (в списке может быть `None`: возраст ещё не известен), `pets`; свойство `party.travellers` — число пассажиров. `TripRequest`: `origin`, `destination`, `month`, `date_from`, `nights`, `party`, `budget`, `tags`, `must`.

**Функции, которые вызывает оркестратор лида** (точные сигнатуры — в `agent/toolkit.py`, не меняй их без согласования; все чистые и синхронные):
```python
# planning/inspiration.py
def pick_destinations(request: TripRequest, catalog: list[Destination]) -> list[Destination]: ...
# planning/packages.py
def simple_packages(request: TripRequest, outbound: list[Leg], inbound: list[Leg], hotels: list[Hotel],
                    transfers_by_hotel: dict[int, list[Transfer]]) -> Result[list[Package], DomainError]: ...
# planning/itinerary.py
def check_package(package: Package) -> list[str]: ...
```

Как оркестратор их использует:
1. направления нет → `pick_destinations`, варианты показываются кнопками;
2. даты поиска считает сам оркестратор. В `simple_packages` приходит `request` **с уже заполненными `date_from` и `nights`**: `check_in = request.date_from`, `check_out = date_from + nights`;
3. `outbound` / `inbound` — рейсы туда и обратно на эти даты, `hotels` — отели направления, `transfers_by_hotel` — трансферы по `hotel.id`. Любой список может прийти пустым, если источник не ответил;
4. к каждому пакету оркестратор применяет `check_package` (результат пишет в `package.issues`), затем объяснения ui.

`Package` сам проверяет инварианты: `total` = сумма `price_breakdown`, `nights` = `check_out − check_in`. Иначе — `ValidationError`. `id` пакета уникален в плане (`p1`–`p3`): по нему UI выбирает пакет.

Готовые данные для тестов: `from tests.fakes import fake_sources, sample_package`.

---

## Задачи MVP

### 1. Теги и тёплые месяцы направлений — можно начинать сразу
- Добавь в `data/reference/destinations.json` поля `tags` (`sea`, `city`, `nature`, `warm`, `winter`) и `warm_months` — месяцы, когда комфортно купаться или гулять. Проверяй по открытым климатическим данным, не на глаз.
- Миграция добавляет колонки в `destination` (модель `Destination` — в `adapters/db/reference.py`), а `seed/reference.py` их заполняет. В `main` последняя миграция — `0002`, твоя идёт после неё (`down_revision = "0002"`).
- [ ] данные заполнены у всех 12 направлений, миграция применяется на чистой БД

### 2. Таблицы инвентаря
Модели в `adapters/db/inventory.py`: `hotel`, `transport_leg`, `transfer`. Файл уже есть в `main`, пустой, и подключён к Alembic через `adapters/db/models.py`. Индексы под поиск: `(destination)`, `(origin, destination, depart_at)`, `(hotel_id)`. Цены `NUMERIC(12,2)`, время `timestamptz`.
- [ ] `alembic check` после твоей миграции без расхождений

### 3. Генератор синтетики (`seed/synthetic.py`)
- Детерминированность: `random.Random(42)`. Даты считаются **от сегодняшнего дня**: на 90 дней вперёд. Если в БД инвентарь начинается раньше сегодня, генератор пересоздаёт его. Вызывается из bootstrap после справочника.
- **Подключение в bootstrap (согласовано с лидом):** в `cli.py`, хотя это зона лида, в своём PR добавь ровно 3 строки — импорт `seed_inventory` и `await seed_inventory(session)` после `seed_reference`. Больше в `cli.py` ничего не меняй и отметь это в описании PR. Причина: вызов не может попасть в `main` раньше `seed/synthetic.py`, иначе bootstrap упадёт с `ImportError`.
- Отели: 5–10 на направление, 2–5 звёзд. Цена за ночь зависит от звёзд и сезона (в «тёплые» месяцы дороже). Питание, бесплатная отмена ~50 %, с животными ~20 %, для детей ~60 %. Для `sea` есть `beach_distance_m`. Заезд в 14:00, выезд в 12:00.
- Перелёты: из `moscow`, `spb`, `kazan` во все направления и обратно, 1–3 рейса в день. Длительность = расстояние по гаверсинусу / 750 км/ч + 40 мин. Цена растёт с расстоянием, в выходные дороже. ~30 % рейсов с пересадкой (+2–4 ч). Время хранится в часовых поясах аэропортов.
- Поезда для коротких внутренних направлений: Москва ↔ Санкт-Петербург, Москва ↔ Казань, Москва ↔ Сочи.
- Трансферы: для каждого отеля такси (быстрее, дороже) и шаттл (дольше, дешевле, есть не везде). Вместимость 3–7, с животными ~50 %.
- Все строки помечены `is_synthetic = true`.

Готово, когда:
- [ ] повторный bootstrap ничего не дублирует
- [ ] тесты на инварианты: прилёт позже вылета; длительность правдоподобна; цены > 0; все даты в будущем

### 4. Репозитории (`adapters/sources/synthetic.py`)
Реализуй `DestinationCatalog`, `HotelSource`, `TransportSource`, `TransferSource` поверх таблиц.
- Репозитории только достают кандидатов. Фильтры по `must` (`pets_allowed`, `kids_friendly`, `direct_only`) применяются в `planning/`, чтобы их можно было тестировать на фейках.
- Исключение — физическая невозможность: `TransferSource` не возвращает машины, вместимость которых меньше числа пассажиров.
- [ ] интеграционная проверка описана в PR: команды и ожидаемый вывод

### 5. Выбор направлений (`planning/inspiration.py`)
`pick_destinations(request, catalog) -> list[Destination]` возвращает до 3 направлений. Порядок: подходят по `month in warm_months` и тегам → разнообразие (не три направления одной страны) → `origin` исключается.
- [ ] юнит-тесты: «море в ноябре» → тёплые морские направления; «город» → города

### 6. Простые пакеты (`planning/packages.py`)
`simple_packages(request, outbound, inbound, hotels, transfers_by_hotel) -> Result[list[Package], DomainError]`. Даты берутся из `request.date_from` и `request.nights`.
- **economy** — минимальная полная стоимость;
- **comfort** — максимум (звёзды, рейтинг), без пересадок, если такой вариант есть;
- **balance** — лучшее соотношение рейтинга и цены;
- `must` и бюджет соблюдаются: если ничего не подходит, вернуть `Failure(NoResults(...))` или `Failure(BudgetTooLow(...))`;
- расчёт `total`: перелёты × число пассажиров (туда и обратно) + отель × ночи + трансфер × 2; `price_breakdown` по статьям.

Готово, когда:
- [ ] юнит-тесты на фейках из `tests/fakes.py`: три разных пакета; бюджет соблюдён; «с собакой» → только `pets_allowed`

### 7. Минимальная проверка стыковок (`planning/itinerary.py`)
`check_package(package) -> list[str]` — предупреждения понятным текстом:
- прилёт + трансфер позже 23:00 по местному времени;
- прилёт ночью (00:00–06:00), а отель только с этой даты: нужна ещё ночь;
- даты отеля не совпадают с датами перелётов в **местном** часовом поясе;
- обратный рейс: время выезда в аэропорт неудобное (два правила ниже).

**Обратный рейс.** Сначала считаем, когда нужно выехать из отеля в аэропорт:

```
выезд_в_аэропорт = inbound.depart_at − AIRPORT_BUFFER − transfer.duration_min (0, если трансфера нет)
```

Время берётся в местном поясе аэропорта (`depart_at` уже в нём), выезд из номера — `check_out` + `hotel.check_out_time` в том же поясе. Дальше два правила:
1. **Ночной выезд:** `выезд_в_аэропорт` попадает на `NIGHT_START`–`NIGHT_END` → «Выезжать из отеля в аэропорт придётся ночью, в 04:10».
2. **Долгое ожидание:** `выезд_в_аэропорт` позже выезда из номера больше чем на `LONG_WAIT` → «Между выездом из номера (12:00) и дорогой в аэропорт 6 ч: нужен поздний выезд или камера хранения».

Константы — в одном месте модуля: `AIRPORT_BUFFER = 2 ч`, `NIGHT_START = 00:00`, `NIGHT_END = 06:00` (не включая), `LONG_WAIT = 4 ч`.

Вылет просто раньше стандартного выезда из номера (например, в 10:00) — **не** предупреждение: уехать раньше времени выезда нормально. Буквальное правило «вылет раньше выезда + 3 ч» срабатывало почти на каждом пакете, и предупреждения превращались в шум.

Готово, когда:
- [ ] юнит-тест на каждое правило, включая границы: выезд ровно в 06:00 — не ночь; ожидание ровно 4 ч — ещё не предупреждение; пакет без трансфера

---

## После MVP (детализируется позже)
- многокритериальный скоринг с разложением вклада (основа объяснений ui);
- beam search + Парето-фронт вместо сортировки;
- ослабление ограничений, когда пусто («+1 день → есть за 72 000 ₽»);
- гибкие даты (префиксные суммы по календарю цен);
- каталог 60–100 направлений из открытых данных; климат из Open-Meteo;
- полный валидатор: вместимость, детское кресло, животные в салоне;
- (по желанию) Connection Scan Algorithm для стыковок самолёт + поезд.

## Как сдавать работу
- Коммиты делает человек после просмотра diff. Формат: Conventional Commits на русском, только суть, например `feat(planning): добавить сборку трёх пакетов`.
- Перед PR выполни проверку из `AGENTS.md`. PR `team/data` → `main` открывай, как только задача готова, не копи. Слияние обычным merge commit.
- Не реже раза в день: `git pull origin main`.

## Правки лида

| Дата | Что изменено |
|---|---|
| 2026-10-23 | первая версия |
| 2026-10-24 | контракты и оркестратор уже в `main` (сначала `git pull origin main`); добавлены сигнатуры из `agent/toolkit.py`: `simple_packages` возвращает `Result`, а не список, `request` приходит с готовыми `date_from` и `nights`; описаны инварианты `Package` и уникальные `id`; `children_ages` допускает `None`; миграции идут после `0002`; проверка перед PR — `scripts/ci.sh` |
| 2026-10-25 | задача 7: буквальное правило «вылет раньше выезда + 3 ч» заменено на два — ночной выезд в аэропорт и долгое ожидание после выезда из номера (константы и границы описаны). Задача 3: правка `cli.py` (3 строки, вызов `seed_inventory`) согласована, делается в PR data |
