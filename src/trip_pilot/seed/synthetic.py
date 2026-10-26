"""Генератор синтетического инвентаря: отели, перелёты, поезда, трансферы. Зона: data.

Детерминирован (random.Random(42)). Даты считаются от переданного «сегодня»: на 90 дней
вперёд. Всё помечено is_synthetic = true.
"""

import logging
import math
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from itertools import count, product
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_pilot.adapters.db import inventory as orm
from trip_pilot.adapters.db import reference
from trip_pilot.domain.offers import Destination, Hotel, Leg, Transfer

logger = logging.getLogger(__name__)

SEED = 42
HORIZON_DAYS = 90
FLIGHT_ORIGINS = ("moscow", "spb", "kazan")
CRUISE_KMH = 750
FLIGHT_OVERHEAD_MIN = 40
EARTH_RADIUS_KM = 6371.0
STOP_SHARE = 0.3  # доля рейсов с пересадкой
SEASON_FACTOR = 1.35  # наценка в «тёплые» месяцы

_STAR_PRICE = {2: 2500, 3: 4500, 4: 8500, 5: 16000}  # базовая цена за ночь
_MEALS = ("RO", "BB", "HB", "AI")
_NAME_A = ("Гранд", "Лазурный", "Золотой", "Северное", "Морской", "Парк", "Панорама", "Ривьера")
_NAME_B = ("Бриз", "Резиденс", "Плаза", "Берег", "Вилла", "Сити", "Гарден", "Маяк")
_SLOTS = (6, 8, 10, 12, 14, 16, 18, 20, 22)  # часы вылета
_MINUTES = (0, 10, 20, 30, 40, 50)
_CARRIERS = ("Демо Авиа", "Демо Эйр", "Демо Лайнс")
# Поезда: (пункт, пункт) → (минут в пути, базовая цена за пассажира, часы отправления).
_TRAINS = {
    ("moscow", "spb"): (4 * 60, 3500, (7, 13, 22)),
    ("moscow", "kazan"): (12 * 60, 3200, (19, 21)),
    ("moscow", "sochi"): (25 * 60, 6500, (9, 17)),
}


@dataclass(frozen=True)
class Inventory:
    """Сгенерированный инвентарь. id временные (1..N): настоящие выдаёт БД при записи."""

    hotels: list[Hotel]
    legs: list[Leg]
    transfers: list[Transfer]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def flight_minutes(distance_km: float) -> int:
    """Длительность прямого рейса: расстояние / 750 км/ч + 40 минут."""
    return math.ceil(distance_km / CRUISE_KMH * 60) + FLIGHT_OVERHEAD_MIN


def _money(value: float, step: int = 50) -> Decimal:
    return Decimal(max(step, round(value / step) * step))


def generate_inventory(destinations: list[Destination], today: date) -> Inventory:
    rng = random.Random(SEED)
    ordered = sorted(destinations, key=lambda d: d.slug)  # порядок не зависит от входа
    hotels = _hotels(rng, ordered, today)
    legs = [*_flights(rng, ordered, today), *_trains(rng, ordered, today)]
    legs = [leg.model_copy(update={"id": i}) for i, leg in enumerate(legs, start=1)]
    return Inventory(hotels=hotels, legs=legs, transfers=_transfers(rng, hotels))


def _hotels(rng: random.Random, destinations: list[Destination], today: date) -> list[Hotel]:
    # У отеля одна цена, а не календарь: «сезон» берём по середине окна генерации.
    middle_month = (today + timedelta(days=HORIZON_DAYS // 2)).month
    ids = count(1)
    hotels = []
    for dest in destinations:
        season = SEASON_FACTOR if middle_month in dest.warm_months else 1.0
        for a, b in rng.sample(list(product(_NAME_A, _NAME_B)), rng.randint(5, 10)):
            stars = rng.choices((2, 3, 4, 5), weights=(1, 3, 3, 2))[0]
            hotels.append(
                Hotel(
                    id=next(ids),
                    destination=dest.slug,
                    name=f"{a} {b}",
                    stars=stars,
                    price_per_night=_money(
                        _STAR_PRICE[stars] * season * rng.uniform(0.85, 1.15), 100
                    ),
                    meal=rng.choices(_MEALS, weights=(2, 4, 2, 2))[0],
                    free_cancellation=rng.random() < 0.5,
                    pets_allowed=rng.random() < 0.2,
                    kids_friendly=rng.random() < 0.6,
                    beach_distance_m=rng.randrange(30, 1500, 10) if "sea" in dest.tags else None,
                    check_in_time=time(14),
                    check_out_time=time(12),
                    rating=round(min(9.8, 6.2 + 0.8 * (stars - 2) + rng.uniform(-0.3, 0.7)), 1),
                )
            )
    return hotels


def _flight_pairs(slugs: set[str]) -> list[tuple[str, str]]:
    """Из Москвы, Петербурга и Казани во все направления и обратно, без повторов."""
    pairs = set()
    for origin in FLIGHT_ORIGINS:
        if origin not in slugs:
            continue
        for slug in slugs - {origin}:
            pairs |= {(origin, slug), (slug, origin)}
    return sorted(pairs)


def _departures(
    day: date, hours: list[int], zone: ZoneInfo, rng: random.Random, cutoff: datetime
) -> Iterator[datetime]:
    """Времена вылета в местном поясе; всё, что не позже cutoff, отбрасывается."""
    for hour in sorted(hours):
        depart = datetime.combine(day, time(hour, rng.choice(_MINUTES)), tzinfo=zone)
        if depart > cutoff:
            yield depart


def _arrival(depart: datetime, minutes: int, zone: ZoneInfo) -> datetime:
    """Прилёт в поясе пункта прибытия. Время в пути считается в UTC: переводы часов не врут."""
    return (depart.astimezone(UTC) + timedelta(minutes=minutes)).astimezone(zone)


def _cutoff(today: date) -> datetime:
    """Конец сегодняшних суток по UTC: всё, что позже, гарантированно в будущем."""
    return datetime.combine(today, time.max, tzinfo=UTC)


def _flights(rng: random.Random, destinations: list[Destination], today: date) -> list[Leg]:
    by_slug = {d.slug: d for d in destinations}
    zones = {slug: ZoneInfo(d.timezone) for slug, d in by_slug.items()}
    cutoff = _cutoff(today)
    legs = []
    for origin, target in _flight_pairs(set(by_slug)):
        o, t = by_slug[origin], by_slug[target]
        km = haversine_km(o.lat, o.lon, t.lat, t.lon)
        for offset in range(1, HORIZON_DAYS + 1):
            day = today + timedelta(days=offset)
            hours = rng.sample(_SLOTS, rng.randint(1, 3))  # 1–3 рейса в день
            for depart in _departures(day, hours, zones[origin], rng, cutoff):
                stops = 1 if rng.random() < STOP_SHARE else 0
                minutes = flight_minutes(km) + (rng.randint(120, 240) if stops else 0)
                price = (
                    (2000 + 3.5 * km)  # цена растёт с расстоянием
                    * (1.2 if day.weekday() >= 5 else 1.0)  # в выходные дороже
                    * (0.85 if stops else 1.0)
                    * rng.uniform(0.9, 1.15)
                )
                legs.append(
                    Leg(
                        id=0, mode="flight", origin=origin, destination=target,
                        depart_at=depart,
                        arrive_at=_arrival(depart, minutes, zones[target]),
                        price=_money(price), stops=stops, carrier=rng.choice(_CARRIERS),
                        baggage_included=rng.random() < 0.7, pets_allowed=rng.random() < 0.6,
                    )
                )
    return legs


def _trains(rng: random.Random, destinations: list[Destination], today: date) -> list[Leg]:
    zones = {d.slug: ZoneInfo(d.timezone) for d in destinations}
    cutoff = _cutoff(today)
    legs = []
    for (a, b), (minutes, base_price, hours) in _TRAINS.items():
        if a not in zones or b not in zones:
            continue
        for origin, target in ((a, b), (b, a)):
            for offset in range(1, HORIZON_DAYS + 1):
                day = today + timedelta(days=offset)
                picked = rng.sample(hours, rng.randint(1, min(2, len(hours))))
                for depart in _departures(day, picked, zones[origin], rng, cutoff):
                    price = base_price * (1.1 if day.weekday() >= 5 else 1.0)
                    legs.append(
                        Leg(
                            id=0, mode="train", origin=origin, destination=target,
                            depart_at=depart,
                            arrive_at=_arrival(depart, minutes, zones[target]),
                            price=_money(price * rng.uniform(0.9, 1.1)), stops=0,
                            carrier="Демо Рейл", baggage_included=True,
                            pets_allowed=rng.random() < 0.8,
                        )
                    )
    return legs


def _transfers(rng: random.Random, hotels: list[Hotel]) -> list[Transfer]:
    ids = count(1)
    transfers = []
    for hotel in hotels:
        taxi_min = rng.randint(15, 50)
        taxi_price = _money(taxi_min * 60 + 500)
        transfers.append(
            Transfer(
                id=next(ids), destination=hotel.destination, hotel_id=hotel.id, kind="taxi",
                duration_min=taxi_min, price=taxi_price, capacity=rng.randint(3, 5),
                pets_allowed=rng.random() < 0.5,
            )
        )
        if rng.random() < 0.6:  # шаттл есть не везде: дольше и дешевле такси
            transfers.append(
                Transfer(
                    id=next(ids), destination=hotel.destination, hotel_id=hotel.id,
                    kind="shuttle", duration_min=int(taxi_min * 1.6) + 10,
                    price=_money(float(taxi_price) * 0.35), capacity=rng.randint(4, 7),
                    pets_allowed=rng.random() < 0.5,
                )
            )
    return transfers


async def seed_inventory(session: AsyncSession, today: date | None = None) -> bool:
    """Создаёт инвентарь, если его нет или самый ранний рейс уже улетел. Иначе ничего не делает.

    Возвращает True, если инвентарь пересоздан. Транзакцией управляет вызывающий код.
    """
    earliest = await session.scalar(select(func.min(orm.TransportLeg.depart_at)))
    hotels_count = await session.scalar(select(func.count()).select_from(orm.Hotel))
    if earliest is not None and hotels_count and earliest > datetime.now(UTC):
        logger.info("Инвентарь актуален, пересоздание не нужно")
        return False

    rows = (await session.scalars(select(reference.Destination))).all()
    destinations = [Destination.model_validate(row, from_attributes=True) for row in rows]
    inventory = generate_inventory(destinations, today or date.today())

    # порядок удаления: трансферы ссылаются на отели
    for table in (orm.Transfer, orm.Hotel, orm.TransportLeg):
        await session.execute(delete(table))

    hotel_rows = [orm.Hotel(**h.model_dump(exclude={"id"})) for h in inventory.hotels]
    session.add_all(hotel_rows)
    await session.flush()  # получаем настоящие id отелей
    real_ids = {h.id: row.id for h, row in zip(inventory.hotels, hotel_rows, strict=True)}

    await session.execute(
        insert(orm.TransportLeg), [leg.model_dump(exclude={"id"}) for leg in inventory.legs]
    )
    await session.execute(
        insert(orm.Transfer),
        [
            t.model_dump(exclude={"id", "hotel_id"}) | {"hotel_id": real_ids[t.hotel_id]}
            for t in inventory.transfers
        ],
    )
    logger.info(
        "Инвентарь создан: отелей %d, рейсов и поездов %d, трансферов %d",
        len(inventory.hotels), len(inventory.legs), len(inventory.transfers),
    )
    return True
