"""Тесты простых пакетов на фейках из tests/fakes.py (Москва ↔ Сочи, 3 отеля)."""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

from returns.result import Failure, Success

from tests.fakes import FakeHotelSource, FakeTransferSource, FakeTransportSource
from trip_pilot.domain.errors import BudgetTooLow, NoResults
from trip_pilot.domain.offers import Package
from trip_pilot.domain.request import Party, TripRequest
from trip_pilot.planning.packages import simple_packages

START = date(2026, 11, 10)
NIGHTS = 5
PARTY = Party(adults=2)


def _request(**kwargs) -> TripRequest:
    base = dict(
        origin="moscow", destination="sochi", month=11, date_from=START, nights=NIGHTS,
        party=PARTY, budget=None, tags=["sea"], must=[],
    )
    return TripRequest(**(base | kwargs))


def _data():
    async def load():
        end = START + timedelta(days=NIGHTS)
        outbound = await FakeTransportSource().search("moscow", "sochi", START, PARTY)
        inbound = await FakeTransportSource().search("sochi", "moscow", end, PARTY)
        hotels = await FakeHotelSource().search("sochi", START, end, PARTY)
        transfers = {
            h.id: await FakeTransferSource().search(h.id, outbound[0].arrive_at, PARTY)
            for h in hotels
        }
        return outbound, inbound, hotels, transfers

    return asyncio.run(load())


def _packages(**kwargs) -> list[Package]:
    outbound, inbound, hotels, transfers = _data()
    result = simple_packages(_request(**kwargs), outbound, inbound, hotels, transfers)
    assert isinstance(result, Success)
    return result.unwrap()


def _by_tier(packages: list[Package]) -> dict[str, Package]:
    return {p.tier: p for p in packages}


def test_three_different_packages():
    packages = _packages()
    assert [p.tier for p in packages] == ["economy", "balance", "comfort"]
    assert [p.id for p in packages] == ["p1", "p2", "p3"]
    assert len({p.hotel.id for p in packages}) == 3


def test_same_hotel_repeats_only_when_it_gives_something():
    """Один отель: дешёвый пакет с пересадками и прямой подороже; третий хуже обоих — его нет."""
    outbound, inbound, hotels, transfers = _data()
    packages = simple_packages(_request(), outbound, inbound, hotels[:1], transfers).unwrap()

    assert [p.tier for p in packages] == ["economy", "comfort"]
    economy, comfort = packages
    assert comfort.total > economy.total
    assert comfort.outbound.stops == comfort.inbound.stops == 0


def test_tiers_follow_their_meaning():
    tiers = _by_tier(_packages())
    assert tiers["economy"].total == min(p.total for p in tiers.values())
    assert tiers["comfort"].hotel.stars == 5
    assert tiers["comfort"].outbound.stops == 0
    assert tiers["comfort"].inbound.stops == 0
    assert tiers["balance"].hotel.stars == 4  # середина по рейтингу и цене


def test_total_is_sum_of_parts():
    economy = _by_tier(_packages())["economy"]
    pax = PARTY.travellers
    expected = (
        (economy.outbound.price + economy.inbound.price) * pax
        + economy.hotel.price_per_night * NIGHTS
        + economy.transfer.price * 2
    )
    assert economy.total == expected
    assert sum(economy.price_breakdown.values()) == economy.total
    assert economy.nights == NIGHTS
    assert economy.check_out - economy.check_in == timedelta(days=NIGHTS)


def test_budget_is_respected():
    budget = Decimal("60000")
    packages = _packages(budget=budget)
    assert packages
    assert all(p.total <= budget for p in packages)


def test_budget_too_low_reports_cheapest_total():
    outbound, inbound, hotels, transfers = _data()
    cheapest = _by_tier(_packages())["economy"].total
    result = simple_packages(
        _request(budget=Decimal("10000")), outbound, inbound, hotels, transfers
    )
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, BudgetTooLow)
    assert error.min_total == cheapest
    assert error.budget == Decimal("10000")


def test_with_pets_only_pets_allowed():
    packages = _packages(must=["pets_allowed"])
    assert packages
    for p in packages:
        assert p.hotel.pets_allowed
        assert p.outbound.pets_allowed and p.inbound.pets_allowed
        assert p.transfer is None or p.transfer.pets_allowed


def test_direct_only_has_no_stops():
    packages = _packages(must=["direct_only"])
    assert packages
    assert all(p.outbound.stops == 0 and p.inbound.stops == 0 for p in packages)


def test_kids_friendly_filters_hotels():
    outbound, inbound, hotels, transfers = _data()
    hotels = [h.model_copy(update={"kids_friendly": h.id == 2}) for h in hotels]
    result = simple_packages(_request(must=["kids_friendly"]), outbound, inbound, hotels, transfers)
    assert isinstance(result, Success)
    assert {p.hotel.id for p in result.unwrap()} == {2}


def test_no_hotels_gives_no_results():
    outbound, inbound, _, transfers = _data()
    result = simple_packages(_request(), outbound, inbound, [], transfers)
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), NoResults)


def test_nothing_matches_must_gives_no_results():
    outbound, inbound, hotels, transfers = _data()
    hotels = [h.model_copy(update={"pets_allowed": False}) for h in hotels]
    result = simple_packages(_request(must=["pets_allowed"]), outbound, inbound, hotels, transfers)
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), NoResults)


def test_issues_come_from_itinerary_check():
    # вечерний рейс с пересадкой прилетает в 00:10: отель забронирован с предыдущего дня,
    # поэтому ночного прилёта и несовпадения дат быть не должно
    economy = _by_tier(_packages())["economy"]
    assert not any("не совпадает" in issue for issue in economy.issues)


def test_with_children_only_kids_friendly_hotels_are_offered():
    outbound, inbound, hotels, transfers = _data()
    # Кипарис (5★) без отметки «для детей»: без фильтра он бы выиграл у «Баланса» и «Комфорта».
    hotels = [h.model_copy(update={"kids_friendly": h.id != 3}) for h in hotels]
    result = simple_packages(
        _request(party=Party(adults=2, children_ages=[5])), outbound, inbound, hotels, transfers
    )
    assert isinstance(result, Success), result
    packages = result.unwrap()
    assert packages
    assert all(package.hotel.kids_friendly for package in packages)
    assert _by_tier(packages)["balance"].hotel.kids_friendly


def test_reasons_of_choice_are_added_to_why():
    packages = _packages()
    for package in packages:
        assert any(line.startswith("Выбрали: ") for line in package.why)
    economy = _by_tier(packages)["economy"]
    text = " ".join(economy.why)
    assert "до пляжа" in text or "рейтинг" in text
