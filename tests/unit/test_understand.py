"""Черновик от LLM и его проверка кодом: каждое поле, отказы и слияние с прошлым запросом."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from returns.result import Failure, Success

from tests.fakes import DESTINATIONS
from trip_pilot.agent.understand import RequestDraft, apply_draft
from trip_pilot.domain.errors import AmbiguousCity, DatesInPast, NoResults, UnknownCity
from trip_pilot.domain.request import Assumption, Party, TripRequest
from trip_pilot.domain.trip_state import SearchWindow, TripState

TODAY = date(2026, 10, 25)
CATALOG = [
    *DESTINATIONS,
    *[
        DESTINATIONS[0].model_copy(update={"slug": slug, "name": name, "iata": None})
        for slug, name in [("spb", "Санкт-Петербург"), ("kazan", "Казань")]
    ],
]


def state_with(request=None, *, check_in=None):
    """Состояние сессии: запрос прошлого поиска и, если нужно, конкретные даты поиска."""
    search = (
        SearchWindow(check_in=check_in, check_out=check_in, nights=7) if check_in else None
    )
    return TripState(session_id=uuid.uuid4(), request=request, search=search)


def applied(draft, *, request=None, check_in=None):
    return apply_draft(
        RequestDraft(**draft) if isinstance(draft, dict) else draft,
        state_with(request, check_in=check_in),
        catalog=CATALOG,
        today=TODAY,
    )


def test_origin_is_resolved_to_slug_by_name_alias_and_slug():
    for raw, slug in [("Москва", "moscow"), ("Питер", "spb"), ("spb", "spb")]:
        result = applied({"origin": raw})
        assert isinstance(result, Success), result
        assert result.unwrap().origin == slug


def test_origin_unknown_is_failure_not_exception():
    result = applied({"origin": "Урюпинск"})
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), UnknownCity)


def test_destination_takes_city_country_and_slug():
    assert applied({"destination": "Анталья"}).unwrap().destination == "antalya"
    assert applied({"destination": "Турция"}).unwrap().destination == "antalya"
    assert applied({"destination": "sochi"}).unwrap().destination == "sochi"


def test_country_with_several_destinations_is_ambiguous():
    result = applied({"destination": "Россия"})
    assert isinstance(result, Failure)
    failure = result.failure()
    assert isinstance(failure, AmbiguousCity)
    assert set(failure.candidates) == {"moscow", "sochi", "spb", "kazan"}


def test_slug_outside_catalog_does_not_pass():
    result = applied({"destination": "paris"})
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), UnknownCity)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-11-14", date(2026, 11, 14)),
        ("14.11.2026", date(2026, 11, 14)),
        ("15 марта", date(2027, 3, 15)),  # год не назван и дата прошла → следующий
        ("14.11", date(2026, 11, 14)),
    ],
)
def test_date_without_year_is_nearest_future(raw, expected):
    result = applied({"date_from": raw})
    assert isinstance(result, Success), result
    assert result.unwrap().date_from == expected


def test_past_date_with_explicit_year_is_dates_in_past():
    for raw in ("5 января 2026", "2026-10-24"):
        result = applied({"date_from": raw})
        assert isinstance(result, Failure), result
        assert isinstance(result.failure(), DatesInPast)


def test_month_only_and_past_month():
    assert applied({"month": 12}).unwrap().month == 12
    result = applied({"month": 5})
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), DatesInPast)


def test_exact_date_clears_month_from_previous_request():
    base = TripRequest(month=11)
    result = applied({"date_from": "2026-12-05"}, request=base)
    assert isinstance(result, Success), result
    assert result.unwrap().date_from == date(2026, 12, 5)
    assert result.unwrap().month is None


def test_date_to_gives_nights_and_invalid_range_fails():
    result = applied({"date_from": "2026-12-05", "date_to": "2026-12-12"})
    assert isinstance(result, Success), result
    assert result.unwrap().nights == 7
    for draft in (
        {"date_to": "2026-12-12"},
        {"date_from": "2026-12-12", "date_to": "2026-12-05"},
    ):
        assert isinstance(applied(draft).failure(), NoResults)


def test_nights_from_draft():
    assert applied({"nights": 14}).unwrap().nights == 14


def test_shift_counts_from_last_search_and_rejects_past():
    result = applied({"shift_days": 2}, request=TripRequest(date_from=date(2026, 11, 7)),
                     check_in=date(2026, 11, 7))
    assert isinstance(result, Success), result
    assert result.unwrap().date_from == date(2026, 11, 9)
    result = applied({"shift_days": -30}, check_in=date(2026, 11, 7))
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), DatesInPast)


def test_shift_without_anchor_or_with_two_dates_fails():
    assert isinstance(applied({"shift_days": 2}).failure(), NoResults)
    assert isinstance(
        applied({"date_from": "2026-12-05", "shift_days": 2}).failure(), NoResults
    )


def test_budget_is_taken_from_draft_and_must_be_positive():
    assert applied({"budget": "100000"}).unwrap().budget == Decimal("100000")
    for value in ("0", "-5"):
        result = applied({"budget": value})
        assert isinstance(result, Failure), value
        assert isinstance(result.failure(), NoResults)


def test_budget_change_recounts_from_previous_request_with_assumption():
    base = TripRequest(budget=Decimal("150000"))
    for change, expected, share in (
        ("less", Decimal("120000.00"), "−20%"),
        ("more", Decimal("180000.00"), "+20%"),
    ):
        result = applied({"budget_change": change}, request=base)
        assert isinstance(result, Success), result
        request = result.unwrap()
        assert request.budget == expected
        assert any(
            item.field == "budget" and share in item.reason for item in request.assumptions
        )


def test_budget_change_without_budget_is_failure():
    result = applied({"budget_change": "less"})
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), NoResults)


def test_party_fields_are_merged_with_previous_request():
    base = TripRequest(party=Party(adults=2, children_ages=[5]))
    result = applied({"adults": 4}, request=base)
    assert isinstance(result, Success), result
    assert result.unwrap().party == Party(adults=4, children_ages=[5])
    result = applied({"children_ages": [None, 8], "pets": ["dog"]}, request=base)
    request = result.unwrap()
    assert request.party.children_ages == [None, 8]
    assert request.party.pets == ["dog"]
    assert "pets_allowed" in request.must


def test_tags_and_must_are_added_to_previous_request():
    base = TripRequest(tags=["sea"], must=["kids_friendly"])
    result = applied({"tags": ["warm"], "must": ["direct_only", "kids_friendly"]}, request=base)
    assert isinstance(result, Success), result
    assert result.unwrap().tags == ["sea", "warm"]
    assert result.unwrap().must == ["kids_friendly", "direct_only"]


def test_draft_keeps_what_user_said_before():
    base = TripRequest(
        origin="moscow",
        nights=7,
        budget=Decimal("150000"),
        party=Party(adults=3),
        assumptions=[Assumption(field="party", value="3", reason="пример")],
    )
    result = applied({"destination": "Сочи"}, request=base)
    assert isinstance(result, Success), result
    request = result.unwrap()
    assert request.origin == "moscow" and request.nights == 7
    assert request.budget == Decimal("150000") and request.party.adults == 3
    assert request.assumptions == base.assumptions


def test_empty_draft_returns_current_request_unchanged():
    base = TripRequest(origin="moscow", destination="sochi")
    result = applied({}, request=base)
    assert isinstance(result, Success), result
    assert result.unwrap() == base


def test_assumptions_do_not_replace_previous_ones():
    base = TripRequest(
        budget=Decimal("150000"),
        assumptions=[Assumption(field="party", value="2", reason="пример")],
    )
    request = applied({"budget_change": "less"}, request=base).unwrap()
    assert [item.field for item in request.assumptions] == ["party", "budget"]


def test_children_ages_are_validated_by_schema():
    with pytest.raises(ValidationError):
        RequestDraft(children_ages=[18])
    with pytest.raises(ValidationError):
        RequestDraft(nights=31)
