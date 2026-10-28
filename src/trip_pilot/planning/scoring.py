"""Оценка пакета под запрос с разложением на вклады. Зона: data.

Оценка — не «магия»: каждый вклад считается по полю пакета и объясняется словами.
Вклады складываются в итог, поэтому по ним же строится `why`
(«Выбрали: 300 м до пляжа и рейтинг 9,1»).

Веса заданы здесь и видны тестам; факторы, которых нет в запросе (пляж без «моря»,
дети без детей), не считаются вовсе — иначе они бы размывали оценку.
"""

from dataclasses import dataclass
from decimal import Decimal

from trip_pilot.domain.offers import Package
from trip_pilot.domain.request import TripRequest

# Сколько метров до пляжа считаем «далеко»: дальше — вклад в ноль.
_BEACH_LIMIT_M = 2000
# Вес факторов: сумма 1.0, поэтому итог всегда от 0 до 1 и сравним между запросами.
_WEIGHTS: dict[str, float] = {
    "price": 0.35,  # цена относительно бюджета или соседей
    "rating": 0.20,  # рейтинг отеля
    "beach": 0.15,  # расстояние до моря, если просят море
    "kids": 0.10,  # отель для детей, если едут с детьми
    "pets": 0.10,  # животные во всех компонентах, если едут с питомцем
    "stops": 0.05,  # без пересадок
    "cancellation": 0.05,  # бесплатная отмена
}


@dataclass(frozen=True)
class Contribution:
    """Один вклад в оценку: что именно дало плюс и сколько."""

    factor: str
    weight: float
    value: float  # насколько фактор хорош: 0 — плохо, 1 — хорошо
    score: float  # weight × value — сколько он добавляет к итогу
    reason: str  # человеческая причина для `why`: «300 м до пляжа»


@dataclass(frozen=True)
class Score:
    total: float
    contributions: tuple[Contribution, ...]

    def reasons(self, limit: int = 2) -> list[str]:
        """Самые весомые вклады — короткие причины для `why`."""
        best = sorted(self.contributions, key=lambda item: item.score, reverse=True)
        return [item.reason for item in best[:limit] if item.score > 0]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _distance(meters: int) -> str:
    if meters >= 1000:
        return f"{meters / 1000:.1f}".replace(".", ",") + " км"
    return f"{meters} м"


def _rub(amount: Decimal) -> str:
    return f"{amount:,.0f}".replace(",", " ") + " ₽"


def _price(
    package: Package, request: TripRequest, reference: tuple[Decimal, Decimal] | None
) -> tuple[float, str]:
    total = package.total
    if request.budget is not None:
        return _clamp(1 - float(total / request.budget)), f"{_rub(total)} в бюджете"
    if reference is not None:
        low, high = reference
        if high > low:
            return 1 - float((total - low) / (high - low)), f"{_rub(total)}"
    return 0.5, _rub(total)


def _beach(package: Package, request: TripRequest) -> tuple[float, str] | None:
    if "sea" not in request.tags:
        return None
    meters = package.hotel.beach_distance_m
    if meters is None:
        return 0.0, "расстояние до пляжа неизвестно"
    return _clamp(1 - meters / _BEACH_LIMIT_M), f"{_distance(meters)} до пляжа"


def _kids(package: Package, request: TripRequest) -> tuple[float, str] | None:
    if not request.party.children_ages and "kids_friendly" not in request.must:
        return None
    if package.hotel.kids_friendly:
        return 1.0, "отель для детей"
    return 0.0, "отель не отмечен как подходящий для детей"


def _pets(package: Package, request: TripRequest) -> tuple[float, str] | None:
    if not request.party.pets and "pets_allowed" not in request.must:
        return None
    components = [package.hotel, package.outbound, package.inbound]
    if package.transfer is not None:
        components.append(package.transfer)
    share = sum(1 for component in components if component.pets_allowed) / len(components)
    if share == 1:
        return 1.0, "можно с животными"
    return share, "животные разрешены не везде"


def _stops(package: Package) -> tuple[float, str]:
    stops = package.outbound.stops + package.inbound.stops
    if stops == 0:
        return 1.0, "без пересадок"
    return _clamp(1 - stops / 4), f"пересадок: {stops}"


def score(
    package: Package,
    request: TripRequest,
    *,
    reference: tuple[Decimal, Decimal] | None = None,
) -> Score:
    """Оценка пакета: сумма вкладов. `reference` — диапазон цен соседей без бюджета."""
    contributions: list[Contribution] = []
    price_value, price_reason = _price(package, request, reference)
    facts: list[tuple[str, tuple[float, str] | None]] = [
        ("price", (price_value, price_reason)),
        ("rating", (package.hotel.rating / 10, f"рейтинг {package.hotel.rating}")),
        ("beach", _beach(package, request)),
        ("kids", _kids(package, request)),
        ("pets", _pets(package, request)),
        ("stops", _stops(package)),
        (
            "cancellation",
            (1.0, "бесплатная отмена") if package.hotel.free_cancellation else (0.0, "без отмены"),
        ),
    ]
    for factor, fact in facts:
        if fact is None:
            continue
        weight = _WEIGHTS[factor]
        value, reason = fact
        contributions.append(Contribution(factor, weight, value, weight * value, reason))
    return Score(sum(item.score for item in contributions), tuple(contributions))


def best_by_score(
    packages: list[Package], request: TripRequest, *, budget: Decimal | None = None
) -> Package:
    """Пакет с лучшей оценкой на рубль: «Баланс» из простых пакетов."""
    totals = [package.total for package in packages]
    reference = (min(totals), max(totals)) if totals else None
    return max(
        packages,
        key=lambda package: (
            score(package, request, reference=reference).total / float(package.total),
            -package.total,
        ),
    )
