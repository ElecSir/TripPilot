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

**Можно менять:** `seed/`, `data/reference/`, `adapters/sources/`, `adapters/db/inventory.py` и `adapters/db/reference.py` (появятся после шага 0 лида), `planning/`, свои миграции, тесты к этому.

**Нельзя без лида:** `domain/`, `ports.py`, `api/`, `migrations/env.py`, `pyproject.toml` / `uv.lock`, чужие зоны.

## Контракты, на которые опираешься

Лид сегодня кладёт их в `main` (шаг 0). Ниже — черновик. Если он разойдётся с кодом в `main`, прав код.

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

`Party`: `adults`, `children_ages`, `pets`. `TripRequest`: `origin`, `destination`, `month`, `date_from`, `nights`, `party`, `budget`, `tags`, `must`.

---

## Задачи MVP

### 1. Теги и тёплые месяцы направлений — можно начинать сразу
- Добавь в `data/reference/destinations.json` поля `tags` (`sea`, `city`, `nature`, `warm`, `winter`) и `warm_months` — месяцы, когда комфортно купаться или гулять. Проверяй по открытым климатическим данным, не на глаз.
- Миграция (после шага 0 лида, модель `Destination` будет в `adapters/db/reference.py`) добавляет колонки в `destination`, а `seed/reference.py` их заполняет.
- [ ] данные заполнены у всех 12 направлений, миграция применяется на чистой БД

### 2. Таблицы инвентаря — после шага 0 лида
Модели в `adapters/db/inventory.py`: `hotel`, `transport_leg`, `transfer`. Индексы под поиск: `(destination)`, `(origin, destination, depart_at)`, `(hotel_id)`. Цены `NUMERIC(12,2)`, время `timestamptz`.
- [ ] `alembic check` после твоей миграции без расхождений

### 3. Генератор синтетики (`seed/synthetic.py`)
- Детерминированность: `random.Random(42)`. Даты считаются **от сегодняшнего дня**: на 90 дней вперёд. Если в БД инвентарь начинается раньше сегодня, генератор пересоздаёт его. Вызывается из bootstrap после справочника.
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
`simple_packages(request, outbound, inbound, hotels, transfers_by_hotel) -> list[Package]`:
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
- обратный вылет раньше выезда из отеля + 3 ч.

Готово, когда:
- [ ] юнит-тест на каждое правило

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
