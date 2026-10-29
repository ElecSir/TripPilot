"""Выбор направлений под запрос. Зона: data."""

from trip_pilot.domain.offers import Destination
from trip_pilot.domain.request import TripRequest

MAX_DESTINATIONS = 3
MAX_PER_COUNTRY = 2  # три направления одной страны не предлагаем
TRIP_TAGS = {"short_flight"}  # про дорогу, а не про место: у направлений таких тегов нет


def _month(request: TripRequest) -> int | None:
    if request.month:
        return request.month
    return request.date_from.month if request.date_from else None


def _suits(destination: Destination, month: int | None, tags: set[str]) -> bool:
    """Подходит по сезону и по всем запрошенным тегам.

    Для зимнего отдыха сезон не проверяется: warm_months описывает тёплые месяцы.
    """
    if month is not None and "winter" not in tags and month not in destination.warm_months:
        return False
    return tags <= set(destination.tags)


def _diversify(suitable: list[Destination]) -> list[Destination]:
    """Сначала по одному направлению на страну, затем добор, но не больше двух на страну."""
    chosen: list[Destination] = []
    countries: set[str] = set()
    for destination in suitable:
        if destination.country not in countries and len(chosen) < MAX_DESTINATIONS:
            chosen.append(destination)
            countries.add(destination.country)
    for destination in suitable:
        if len(chosen) >= MAX_DESTINATIONS:
            break
        same_country = sum(d.country == destination.country for d in chosen)
        if destination not in chosen and same_country < MAX_PER_COUNTRY:
            chosen.append(destination)
    return chosen


def pick_destinations(request: TripRequest, catalog: list[Destination]) -> list[Destination]:
    """До трёх направлений: сезон и теги → разнообразие по странам; город вылета исключается."""
    month = _month(request)
    tags = set(request.tags) - TRIP_TAGS
    origin = request.origin
    suitable = sorted(
        (
            d
            for d in catalog
            if d.slug != origin and _suits(d, month, tags)
        ),
        key=lambda d: d.slug,  # детерминированный порядок
    )
    return _diversify(suitable)
