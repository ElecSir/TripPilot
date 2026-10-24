"""Инварианты синтетического инвентаря (без БД)."""

import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from trip_pilot.domain.offers import Destination
from trip_pilot.seed.synthetic import (
    FLIGHT_ORIGINS,
    HORIZON_DAYS,
    _STAR_PRICE,
    Inventory,
    flight_minutes,
    generate_inventory,
    haversine_km,
)

REFERENCE = Path(__file__).parents[3] / "data" / "reference" / "destinations.json"
TODAY = date(2026, 10, 24)
TRAIN_PAIRS = {
    ("moscow", "spb"), ("spb", "moscow"), ("moscow", "kazan"), ("kazan", "moscow"),
    ("moscow", "sochi"), ("sochi", "moscow"),
}


@pytest.fixture(scope="module")
def destinations() -> list[Destination]:
    items = json.loads(REFERENCE.read_text(encoding="utf-8"))
    return [Destination.model_validate(item) for item in items]


@pytest.fixture(scope="module")
def inventory(destinations: list[Destination]) -> Inventory:
    return generate_inventory(destinations, TODAY)


def test_reference_is_filled(destinations: list[Destination]):
    assert len(destinations) == 12
    for d in destinations:
        assert d.tags, d.slug
        assert d.warm_months, d.slug
        assert set(d.tags) <= {"sea", "city", "nature", "warm", "winter"}, d.slug
        assert all(1 <= m <= 12 for m in d.warm_months), d.slug


def test_is_deterministic(destinations: list[Destination], inventory: Inventory):
    assert generate_inventory(destinations, TODAY) == inventory
    assert generate_inventory(list(reversed(destinations)), TODAY) == inventory


def test_hotels(destinations: list[Destination], inventory: Inventory):
    sea = {d.slug for d in destinations if "sea" in d.tags}
    per_destination = Counter(h.destination for h in inventory.hotels)
    assert set(per_destination) == {d.slug for d in destinations}
    assert all(5 <= n <= 10 for n in per_destination.values())
    for hotel in inventory.hotels:
        assert 2 <= hotel.stars <= 5
        assert hotel.price_per_night > 0
        assert (hotel.beach_distance_m is not None) == (hotel.destination in sea)
        assert (hotel.check_in_time.hour, hotel.check_out_time.hour) == (14, 12)
    shares = {
        "free_cancellation": (0.3, 0.7), "pets_allowed": (0.08, 0.35), "kids_friendly": (0.4, 0.8),
    }
    for field, (low, high) in shares.items():
        share = sum(getattr(h, field) for h in inventory.hotels) / len(inventory.hotels)
        assert low <= share <= high, field


def test_season_makes_hotels_pricier(inventory: Inventory):
    # середина окна от 24.10 — начало декабря: у Дубая сезон, у Антальи нет
    def markup(slug: str) -> float:
        ratios = [
            float(h.price_per_night) / _STAR_PRICE[h.stars]
            for h in inventory.hotels
            if h.destination == slug
        ]
        return sum(ratios) / len(ratios)

    assert markup("dubai") > markup("antalya") * 1.2


def test_all_future_and_within_horizon(inventory: Inventory):
    now = datetime.now(UTC)
    last_day = TODAY + timedelta(days=HORIZON_DAYS)
    for leg in inventory.legs:
        assert leg.depart_at > datetime(TODAY.year, TODAY.month, TODAY.day, 23, 59, tzinfo=UTC)
        assert TODAY < leg.depart_at.date() <= last_day
    # относительно реальных часов тоже: генератор от «сегодня» всегда даёт будущее
    fresh = generate_inventory(
        [Destination.model_validate(i) for i in json.loads(REFERENCE.read_text("utf-8"))],
        date.today(),
    )
    assert all(leg.depart_at > now for leg in fresh.legs)


def test_legs_are_consistent(destinations: list[Destination], inventory: Inventory):
    by_slug = {d.slug: d for d in destinations}
    for leg in inventory.legs:
        assert leg.arrive_at > leg.depart_at
        assert leg.price > 0
        assert leg.depart_at.tzinfo.key == by_slug[leg.origin].timezone
        assert leg.arrive_at.tzinfo.key == by_slug[leg.destination].timezone
        assert leg.is_synthetic
    assert len({leg.id for leg in inventory.legs}) == len(inventory.legs)


def test_flight_duration_follows_distance(destinations: list[Destination], inventory: Inventory):
    by_slug = {d.slug: d for d in destinations}
    for leg in inventory.legs:
        if leg.mode != "flight":
            continue
        o, t = by_slug[leg.origin], by_slug[leg.destination]
        direct = flight_minutes(haversine_km(o.lat, o.lon, t.lat, t.lon))
        extra = leg.duration_min - direct
        assert (extra == 0) if leg.stops == 0 else (120 <= extra <= 240)


def test_flight_routes_cover_all_destinations(
    destinations: list[Destination], inventory: Inventory
):
    pairs = {(leg.origin, leg.destination) for leg in inventory.legs if leg.mode == "flight"}
    for origin in FLIGHT_ORIGINS:
        for d in destinations:
            if d.slug != origin:
                assert (origin, d.slug) in pairs
                assert (d.slug, origin) in pairs


def test_flights_per_day_and_stops_share(inventory: Inventory):
    flights = [leg for leg in inventory.legs if leg.mode == "flight"]
    per_day = Counter((f.origin, f.destination, f.depart_at.date()) for f in flights)
    assert all(1 <= n <= 3 for n in per_day.values())
    share = sum(f.stops > 0 for f in flights) / len(flights)
    assert 0.2 <= share <= 0.4


def test_trains_only_on_short_domestic_routes(inventory: Inventory):
    trains = [leg for leg in inventory.legs if leg.mode == "train"]
    assert {(t.origin, t.destination) for t in trains} == TRAIN_PAIRS
    assert all(t.stops == 0 for t in trains)


def test_transfers(inventory: Inventory):
    hotels = {h.id: h for h in inventory.hotels}
    by_hotel: dict[int, dict[str, object]] = {}
    for t in inventory.transfers:
        assert t.hotel_id in hotels
        assert t.destination == hotels[t.hotel_id].destination
        assert 3 <= t.capacity <= 7
        assert t.price > 0
        by_hotel.setdefault(t.hotel_id, {})[t.kind] = t
    assert set(by_hotel) == set(hotels)  # такси есть у каждого отеля
    assert all("taxi" in kinds for kinds in by_hotel.values())
    shuttles = [k["shuttle"] for k in by_hotel.values() if "shuttle" in k]
    assert 0 < len(shuttles) < len(hotels)  # шаттл есть не везде
    for kinds in by_hotel.values():
        if "shuttle" in kinds:
            taxi, shuttle = kinds["taxi"], kinds["shuttle"]
            assert shuttle.duration_min > taxi.duration_min
            assert shuttle.price < taxi.price
