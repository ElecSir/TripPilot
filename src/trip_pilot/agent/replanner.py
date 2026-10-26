"""Пересборка плана: что искать заново при изменении условий и что поменялось для человека.

Поиск зависит только от маршрута, дат и числа путешественников. Бюджет, «без пересадок»,
животные и предпочтения меняют выбор из уже найденного — для них новый поиск не нужен.
"""

from dataclasses import dataclass
from decimal import Decimal

from trip_pilot.agent import texts
from trip_pilot.domain.offers import Package
from trip_pilot.domain.request import TripRequest
from trip_pilot.domain.trip_state import SearchCache, SearchWindow


@dataclass(frozen=True)
class SearchNeeds:
    """Какие источники опросить заново. Остальное берётся из кеша прошлого поиска."""

    outbound: bool = True
    inbound: bool = True
    hotels: bool = True
    transfers: bool = True

    @property
    def everything(self) -> bool:
        return self.outbound and self.inbound and self.hotels and self.transfers


EVERYTHING = SearchNeeds()


def search_needs(
    cache: SearchCache | None, request: TripRequest, window: SearchWindow
) -> SearchNeeds:
    """Кеша нет, другой маршрут или другое число путешественников — ищем всё заново."""
    if (
        cache is None
        or (cache.origin, cache.destination) != (request.origin, request.destination)
        or cache.travellers != request.party.travellers
    ):
        return EVERYTHING
    outbound = cache.check_in != window.check_in
    inbound = cache.check_out != window.check_out
    hotels = outbound or inbound
    # Трансфер зависит от времени прилёта и от отеля.
    transfers = outbound or hotels
    return SearchNeeds(outbound=outbound, inbound=inbound, hotels=hotels, transfers=transfers)


def reused_step(needs: SearchNeeds) -> str | None:
    """Шаг хода: что агент берёт из прошлого поиска. None — ищет всё заново."""
    if needs.everything:
        return None
    reused = [
        name
        for name, again in (
            ("рейсы туда", needs.outbound),
            ("обратные рейсы", needs.inbound),
            ("отели", needs.hotels),
            ("трансферы", needs.transfers),
        )
        if not again
    ]
    if len(reused) == 4:
        return "Маршрут, даты и состав те же — пересобираю пакеты из уже найденных вариантов"
    return "Беру из прошлого поиска: " + ", ".join(reused)


def describe_changes(
    before: list[Package],
    after: list[Package],
    before_window: SearchWindow | None,
    after_window: SearchWindow,
) -> list[str]:
    """Что поменялось в плане: строка про даты и по строке на каждый уровень пакета."""
    lines = []
    if before_window is not None and (before_window.check_in, before_window.check_out) != (
        after_window.check_in,
        after_window.check_out,
    ):
        old_period = texts.period(before_window.check_in, before_window.check_out)
        new_period = texts.period(after_window.check_in, after_window.check_out)
        lines.append(f"даты: {old_period} → {new_period}")
    old = {p.tier: p for p in before}
    new = {p.tier: p for p in after}
    for tier, name in texts.TIERS.items():
        if tier in old and tier not in new:
            lines.append(f"«{name}»: под новые условия варианта нет")
        elif tier in new and tier not in old:
            lines.append(f"«{name}»: новый вариант, {texts.money(new[tier].total)}")
        elif tier in new:
            lines.append(f"«{name}»: {_package_change(old[tier], new[tier])}")
    return lines


def _package_change(old: Package, new: Package) -> str:
    parts = [_price_change(old.total, new.total)]
    if old.hotel.id == new.hotel.id:
        parts.append(f"отель тот же ({new.hotel.name})")
    else:
        parts.append(f"отель: {old.hotel.name} → {new.hotel.name}")
    if (old.outbound.id, old.inbound.id) != (new.outbound.id, new.inbound.id):
        parts.append("другие рейсы")
    return ", ".join(parts)


def _price_change(old: Decimal, new: Decimal) -> str:
    if old == new:
        return f"цена та же, {texts.money(new)}"
    sign = "+" if new > old else "−"
    return f"{texts.money(old)} → {texts.money(new)} ({sign}{texts.money(abs(new - old))})"
