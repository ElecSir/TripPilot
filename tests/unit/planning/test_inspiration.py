"""Тесты выбора направлений. Данные в фикстуре условные, не настоящий справочник."""

from datetime import date

from trip_pilot.domain.offers import Destination
from trip_pilot.domain.request import Party, TripRequest
from trip_pilot.planning.inspiration import pick_destinations

NOV = [11]


def _dest(slug: str, country: str, tags: list[str], months: list[int]) -> Destination:
    return Destination(
        slug=slug, name=slug, country=country, lat=0.0, lon=0.0,
        timezone="Europe/Moscow", tags=tags, warm_months=months,
    )


CATALOG = [
    _dest("moscow", "Россия", ["city"], [5, 6, 7, 8, 9]),
    _dest("spb", "Россия", ["city"], [5, 6, 7, 8, 9]),
    _dest("kazan", "Россия", ["city"], [5, 6, 7, 8, 9]),
    _dest("sochi", "Россия", ["sea", "nature"], [6, 7, 8, 9]),
    _dest("antalya", "Турция", ["sea", "warm"], [5, 6, 7, 8, 9, 10, 11]),
    _dest("bodrum", "Турция", ["sea", "warm"], NOV),
    _dest("marmaris", "Турция", ["sea", "warm"], NOV),
    _dest("sharm", "Египет", ["sea", "warm"], [10, 11, 12]),
    _dest("dubai", "ОАЭ", ["city", "warm"], [11, 12]),
    _dest("phuket", "Таиланд", ["sea", "warm"], [11, 12]),
    _dest("murmansk", "Россия", ["nature", "winter"], [6, 7, 8]),
]


def _request(**kwargs) -> TripRequest:
    base = dict(
        origin="moscow", destination=None, month=None, date_from=None, nights=7,
        party=Party(adults=2), budget=None, tags=[], must=[],
    )
    return TripRequest(**(base | kwargs))


def _pick(**kwargs) -> list[Destination]:
    return pick_destinations(_request(**kwargs), CATALOG)


def test_sea_in_november_gives_warm_sea_destinations():
    result = _pick(month=11, tags=["sea"])
    assert result
    assert all("sea" in d.tags and 11 in d.warm_months for d in result)
    assert "sochi" not in {d.slug for d in result}  # в ноябре в Сочи не купаются


def test_city_gives_cities():
    result = _pick(month=7, tags=["city"])
    assert result
    assert all("city" in d.tags for d in result)


def test_origin_is_excluded():
    result = _pick(origin="spb", month=7, tags=["city"])
    assert "spb" not in {d.slug for d in result}


def test_not_three_from_one_country():
    result = _pick(month=11, tags=["sea"])
    assert len(result) == 3
    assert len({d.country for d in result}) == 3  # три турецких не берём


def test_at_most_two_per_country_when_few_countries():
    catalog_two_countries = [d for d in CATALOG if d.country in {"Турция", "Египет"}]

    result = pick_destinations(_request(month=11, tags=["sea"]), catalog_two_countries)
    assert len(result) == 3
    assert sum(d.country == "Турция" for d in result) == 2


def test_month_taken_from_date_from():
    result = _pick(date_from=date(2026, 11, 20), tags=["sea"])
    assert result
    assert all(11 in d.warm_months for d in result)


def test_nothing_suitable_gives_empty_list():
    assert _pick(month=2, tags=["sea"]) == []


def test_winter_ignores_warm_months():
    result = _pick(month=1, tags=["winter"])
    assert [d.slug for d in result] == ["murmansk"]


def test_is_deterministic():
    assert _pick(month=11, tags=["sea"]) == _pick(month=11, tags=["sea"])


def test_trip_tags_do_not_filter_places():
    """«Без долгих перелётов» — про дорогу: выбор мест тот же, что и без этого тега."""
    with_trip_tag = _request(month=11, tags=["sea", "short_flight"])
    assert pick_destinations(with_trip_tag, CATALOG) == pick_destinations(
        _request(month=11, tags=["sea"]), CATALOG
    )


def test_ski_has_no_destinations_in_catalog():
    assert pick_destinations(_request(month=1, tags=["ski"]), CATALOG) == []
