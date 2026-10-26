"""Пересборка плана: что искать заново и как описать человеку, что поменялось."""

from datetime import date, timedelta
from decimal import Decimal

from tests.fakes import sample_package
from trip_pilot.agent import texts
from trip_pilot.agent.replanner import (
    EVERYTHING,
    SearchNeeds,
    describe_changes,
    reused_step,
    search_needs,
)
from trip_pilot.domain.request import Party, TripRequest
from trip_pilot.domain.trip_state import SearchCache, SearchWindow

DAY = date(2030, 11, 9)
WINDOW = SearchWindow(check_in=DAY, check_out=DAY + timedelta(days=7), nights=7)
REQUEST = TripRequest(origin="moscow", destination="antalya", month=11)
CACHE = SearchCache(
    origin="moscow", destination="antalya", check_in=WINDOW.check_in,
    check_out=WINDOW.check_out, travellers=2,
)
NOTHING = SearchNeeds(outbound=False, inbound=False, hotels=False, transfers=False)


def window(check_in: date, nights: int) -> SearchWindow:
    check_out = check_in + timedelta(days=nights)
    return SearchWindow(check_in=check_in, check_out=check_out, nights=nights)


def test_without_cache_everything_is_searched():
    assert search_needs(None, REQUEST, WINDOW) == EVERYTHING
    assert reused_step(EVERYTHING) is None


def test_budget_pets_and_must_do_not_need_a_new_search():
    changed = REQUEST.model_copy(update={
        "budget": Decimal("90000"), "must": ["direct_only", "pets_allowed"],
        "party": Party(pets=["dog"]),  # животное не меняет число путешественников
    })
    needs = search_needs(CACHE, changed, WINDOW)
    assert needs == NOTHING
    assert reused_step(needs).startswith("Маршрут, даты и состав те же")


def test_longer_stay_searches_return_flights_hotels_and_transfers():
    needs = search_needs(CACHE, REQUEST, window(DAY, 9))
    assert needs == SearchNeeds(outbound=False, inbound=True, hotels=True, transfers=True)
    assert reused_step(needs) == "Беру из прошлого поиска: рейсы туда"


def test_shifted_dates_search_flights_and_hotels_again():
    assert search_needs(CACHE, REQUEST, window(DAY + timedelta(days=2), 7)) == EVERYTHING


def test_other_route_or_party_size_searches_everything():
    sochi = REQUEST.model_copy(update={"destination": "sochi"})
    trio = REQUEST.model_copy(update={"party": Party(adults=2, children_ages=[5])})
    assert search_needs(CACHE, sochi, WINDOW) == EVERYTHING
    assert search_needs(CACHE, trio, WINDOW) == EVERYTHING


def test_changes_report_dates_price_and_hotel():
    before = [sample_package("p1", day=DAY)]
    later = sample_package("p1", day=DAY + timedelta(days=2))
    after = [later.model_copy(update={"tier": "economy"})]

    lines = describe_changes(before, after, WINDOW, window(DAY + timedelta(days=2), 7))

    assert lines[0] == "даты: 9–16 ноября → 11–18 ноября"
    assert lines[1].startswith("«Эконом»: ")
    assert "отель тот же" in lines[1]


def test_changes_report_price_delta_and_lost_tier():
    economy = sample_package("p1", day=DAY)
    cheaper = economy.model_copy(update={
        "total": economy.total - Decimal("11400"), "price_breakdown": {},
    })
    comfort = economy.model_copy(update={"id": "p3", "tier": "comfort"})

    lines = describe_changes([economy, comfort], [cheaper], WINDOW, WINDOW)

    saved = texts.money(Decimal("11400"))
    assert lines[0].endswith(f"(−{saved}), отель тот же ({economy.hotel.name})")
    assert lines[1] == "«Комфорт»: под новые условия варианта нет"
