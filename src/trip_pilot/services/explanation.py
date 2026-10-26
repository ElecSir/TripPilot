"""Короткие объяснения, основанные только на полях пакета и запроса."""

from decimal import Decimal

from trip_pilot.domain.offers import Package
from trip_pilot.domain.request import TripRequest


def _money(amount: Decimal) -> str:
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",").removesuffix(",00") + " ₽"


def _duration(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return f"{hours} ч {rest} мин" if rest else f"{hours} ч"


def explain(package: Package, request: TripRequest) -> Package:
    """Соседние пакеты не переданы: сравнительные числа не придумываем."""
    why, tradeoffs, risks = [], [], list(package.issues)
    hotel = package.hotel
    for direction, leg in (("туда", package.outbound), ("обратно", package.inbound)):
        if leg.stops == 0:
            mode = "перелёт" if leg.mode == "flight" else "поезд"
            why.append(f"Прямой {mode} {direction}: {_duration(leg.duration_min)}")
        else:
            tradeoffs.append(f"Пересадок {direction}: {leg.stops}")
            if "direct_only" in request.must:
                risks.append(f"Маршрут {direction} нарушает условие «без пересадок»")
    if hotel.free_cancellation:
        why.append("Бесплатная отмена отеля")
    else:
        risks.append("Без бесплатной отмены отеля")
    if request.party.children_ages or "kids_friendly" in request.must:
        if hotel.kids_friendly:
            why.append("Отель подходит для детей")
        else:
            risks.append("Отель не отмечен как подходящий для детей")
    if request.party.pets or "pets_allowed" in request.must:
        components = [
            ("отель", hotel),
            ("рейс туда", package.outbound),
            ("рейс обратно", package.inbound),
        ]
        if package.transfer:
            components.append(("трансфер", package.transfer))
        restricted = [name for name, component in components if not component.pets_allowed]
        if restricted:
            risks.extend(f"Компонент «{name}» не допускает животных" for name in restricted)
        else:
            why.append("Можно с животными во всех включённых компонентах")
    if hotel.beach_distance_m is not None:
        why.append(f"До пляжа: {hotel.beach_distance_m} м")
    why.append(f"Отель {hotel.stars}★, рейтинг {hotel.rating}/10")
    if request.budget is not None:
        if package.total <= request.budget:
            why.append(f"Стоимость {_money(package.total)} — в бюджете {_money(request.budget)}")
        else:
            tradeoffs.append(f"Превышение бюджета: {_money(package.total - request.budget)}")
    if package.transfer is None:
        tradeoffs.append("Трансфер не включён")
    if hotel.is_synthetic or package.outbound.is_synthetic or package.inbound.is_synthetic:
        risks.append("Синтетические предложения: цены и расписание демонстрационные")
    return package.model_copy(
        update={
            "why": list(dict.fromkeys(why)),
            "tradeoffs": list(dict.fromkeys(tradeoffs)),
            "risks": list(dict.fromkeys(risks)),
        },
        deep=True,
    )
