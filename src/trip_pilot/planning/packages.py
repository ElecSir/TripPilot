"""Простые пакеты: economy, balance, comfort без многокритериального поиска. Зона: data."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from itertools import product

from returns.result import Failure, Result, Success

from trip_pilot.domain.errors import BudgetTooLow, NoResults
from trip_pilot.domain.offers import Hotel, Leg, Package, Tier, Transfer
from trip_pilot.domain.request import Party, TripRequest
from trip_pilot.planning.itinerary import check_package
from trip_pilot.planning.scoring import score

_WHY: dict[Tier, str] = {
    "economy": "Минимальная полная стоимость среди подходящих вариантов",
    "balance": "Лучшее сочетание рейтинга отеля и цены",
    "comfort": "Лучший отель по звёздам и рейтингу, по возможности без пересадок",
}
_ORDER: tuple[Tier, ...] = ("economy", "balance", "comfort")


@dataclass(frozen=True)
class _Candidate:
    outbound: Leg
    inbound: Leg
    hotel: Hotel
    transfer: Transfer | None
    total: Decimal
    breakdown: dict[str, Decimal]

    @property
    def direct(self) -> bool:
        return not self.outbound.stops and not self.inbound.stops


def simple_packages(
    request: TripRequest,
    outbound: list[Leg],
    inbound: list[Leg],
    hotels: list[Hotel],
    transfers_by_hotel: dict[int, list[Transfer]],
) -> Result[list[Package], NoResults | BudgetTooLow]:
    """До трёх разных пакетов (economy, balance, comfort) с учётом must и бюджета."""
    nights = request.nights
    if request.date_from is None or not nights or nights < 1:
        return Failure(NoResults("не заданы даты или число ночей"))

    candidates = _candidates(request, outbound, inbound, hotels, transfers_by_hotel, nights)
    if isinstance(candidates, str):
        return Failure(NoResults(candidates))

    if request.budget is not None:
        affordable = [c for c in candidates if c.total <= request.budget]
        if not affordable:
            return Failure(BudgetTooLow(request.budget, min(c.total for c in candidates)))
        candidates = affordable

    chosen = _choose(candidates, request)
    tiers = [tier for tier in _ORDER if tier in chosen]
    # id уникален в плане (p1–p3): по нему UI выбирает пакет
    packages = [
        _build(f"p{n}", tier, chosen[tier], request, nights) for n, tier in enumerate(tiers, 1)
    ]
    return Success(packages)


def _pets_required(request: TripRequest) -> bool:
    return "pets_allowed" in set(request.must) or bool(request.party.pets)


def _pick_transfer(transfers: list[Transfer], party: Party, pets: bool) -> Transfer | None:
    """Самый дешёвый трансфер, куда помещается группа (и с животными, если нужно)."""
    suitable = [
        t for t in transfers if t.capacity >= party.travellers and (t.pets_allowed or not pets)
    ]
    return min(suitable, key=lambda t: (t.price, t.duration_min, t.id), default=None)


def _candidates(
    request: TripRequest,
    outbound: list[Leg],
    inbound: list[Leg],
    hotels: list[Hotel],
    transfers_by_hotel: dict[int, list[Transfer]],
    nights: int,
) -> list[_Candidate] | str:
    """Все допустимые сочетания рейсов и отеля. Строка вместо списка: причина, почему пусто."""
    must = set(request.must)
    pets = _pets_required(request)
    direct = "direct_only" in must
    kids = "kids_friendly" in must
    pax = request.party.travellers

    def leg_ok(leg: Leg) -> bool:
        return (leg.pets_allowed or not pets) and not (direct and leg.stops)

    outs = [leg for leg in outbound if leg_ok(leg)]
    backs = [leg for leg in inbound if leg_ok(leg)]
    hotels_ok = [
        h for h in hotels if (h.pets_allowed or not pets) and (h.kids_friendly or not kids)
    ]
    # С детьми берём только «для детей», если такие отели вообще есть: иначе «Баланс»
    # выбирал бы дешёвый отель без отметки, и предупреждение в рисках было бы вместо выбора.
    if request.party.children_ages and not kids:
        friendly = [hotel for hotel in hotels_ok if hotel.kids_friendly]
        if friendly:
            hotels_ok = friendly
    if not outs:
        return "нет рейсов туда, подходящих под условия"
    if not backs:
        return "нет обратных рейсов, подходящих под условия"
    if not hotels_ok:
        return "нет отелей, подходящих под условия"

    result: list[_Candidate] = []
    for out, back in product(outs, backs):
        if back.depart_at <= out.arrive_at:
            continue
        for hotel in hotels_ok:
            if not hotel.destination == out.destination == back.origin:
                continue
            transfer = _pick_transfer(transfers_by_hotel.get(hotel.id, []), request.party, pets)
            breakdown = {
                "outbound": out.price * pax,
                "inbound": back.price * pax,
                "hotel": hotel.price_per_night * nights,
            }
            if transfer:
                breakdown["transfer"] = transfer.price * 2  # туда и обратно
            total = sum(breakdown.values(), Decimal(0))
            result.append(_Candidate(out, back, hotel, transfer, total, breakdown))
    return result or "нет сочетаний рейсов и отеля с подходящими датами"


def _plain(candidate: _Candidate, request: TripRequest, nights: int) -> Package:
    """Пакет для оценки: без проверки стыковок, она нужна только готовому пакету."""
    check_in = request.date_from
    assert check_in is not None  # проверено в simple_packages
    return Package(
        id="score",
        tier="balance",
        destination=candidate.hotel.destination,
        outbound=candidate.outbound,
        inbound=candidate.inbound,
        hotel=candidate.hotel,
        transfer=candidate.transfer,
        check_in=check_in,
        check_out=check_in + timedelta(days=nights),
        nights=nights,
        total=candidate.total,
        price_breakdown=candidate.breakdown,
    )


def _choose(candidates: list[_Candidate], request: TripRequest) -> dict[Tier, _Candidate]:
    """По одному кандидату на тариф; один и тот же вариант дважды не берётся.

    Тарифы значат ровно то, что написано: economy — самая низкая цена, comfort — лучшая
    оценка (по возможности без пересадок), balance — лучшая оценка на рубль (`scoring.py`).
    """
    pool = list(candidates)
    chosen: dict[Tier, _Candidate] = {}
    nights = request.nights or 1
    totals = [candidate.total for candidate in candidates]
    reference = (min(totals), max(totals)) if totals else None
    scored = {
        id(candidate): score(
            _plain(candidate, request, nights), request, reference=reference
        ).total
        for candidate in candidates
    }

    def economy(items: list[_Candidate]) -> _Candidate:
        return min(items, key=lambda c: (c.total, -c.hotel.rating, c.hotel.id))

    def comfort(items: list[_Candidate]) -> _Candidate:
        direct = [c for c in items if c.direct] or items
        return max(direct, key=lambda c: (c.hotel.stars, c.hotel.rating, scored[id(c)], -c.total))

    def balance(items: list[_Candidate]) -> _Candidate:
        return max(items, key=lambda c: (scored[id(c)] / float(c.total), -c.total))

    pickers: list[tuple[Tier, Callable[[list[_Candidate]], _Candidate]]] = [
        ("economy", economy),
        ("comfort", comfort),
        ("balance", balance),
    ]
    for tier, pick in pickers:
        # Три пакета должны быть разными не только по рейсам: отель тоже не повторяем.
        # Отели кончились — тот же отель ещё раз, только если он дешевле или прямее уже
        # выбранного; иначе пакетов меньше трёх, а не «Баланс» дороже «Комфорта» в том же отеле.
        used = {candidate.hotel.id for candidate in chosen.values()}
        fresh = [candidate for candidate in pool if candidate.hotel.id not in used] or [
            candidate for candidate in pool if not _dominated(candidate, chosen.values())
        ]
        if not fresh:
            break
        candidate = pick(fresh)
        pool.remove(candidate)
        chosen[tier] = candidate
    return chosen


def _dominated(candidate: _Candidate, chosen: Iterable[_Candidate]) -> bool:
    """Тот же отель, не дешевле и не прямее уже выбранного варианта: выбирать его незачем."""
    return any(
        other.hotel.id == candidate.hotel.id
        and candidate.total >= other.total
        and (other.direct or not candidate.direct)
        for other in chosen
    )


def _build(
    package_id: str, tier: Tier, c: _Candidate, request: TripRequest, nights: int
) -> Package:
    check_in = request.date_from
    assert check_in is not None  # проверено в simple_packages
    risks = [] if c.transfer else ["Подходящий трансфер не найден: до отеля добираться самим"]
    package = Package(
        id=package_id,
        tier=tier,
        destination=c.hotel.destination,
        outbound=c.outbound,
        inbound=c.inbound,
        hotel=c.hotel,
        transfer=c.transfer,
        check_in=check_in,
        check_out=check_in + timedelta(days=nights),
        nights=nights,
        total=c.total,
        price_breakdown=c.breakdown,
        why=[_WHY[tier]],
        risks=risks,
    )
    # Почему выбран именно он: самые весомые вклады оценки, словами и без выдуманных чисел.
    reasons = score(package, request).reasons()
    if reasons:
        package = package.model_copy(
            update={"why": [*package.why, f"Выбрали: {' и '.join(reasons)}"]}
        )
    return package.model_copy(update={"issues": check_package(package)})
