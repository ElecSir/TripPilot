"""Приоритеты вопросов, месяцы и ответы по каждому slot."""

from datetime import date

import pytest
from returns.result import Failure, Success

from tests.fakes import DESTINATIONS
from trip_pilot.agent import clarifier
from trip_pilot.agent.clarifier import apply_answer, next_question
from trip_pilot.domain.errors import DatesInPast, NoResults, UnknownCity
from trip_pilot.domain.request import Party, TripRequest
from trip_pilot.domain.trip_state import PendingQuestion

TODAY = date(2026, 10, 25)


@pytest.fixture(autouse=True)
def freeze_question_date(monkeypatch):
    class FrozenDate(date):
        @classmethod
        def today(cls):
            return TODAY

    monkeypatch.setattr(clarifier, "date", FrozenDate)


def question(slot):
    return PendingQuestion(slot=slot, text="Вопрос", options=[])


def test_one_question_in_contract_priority_and_no_invented_cities():
    request = TripRequest(party=Party(children_ages=[None]))
    first = next_question(request, DESTINATIONS)
    assert first.slot == "origin"
    assert first.options == ["Москва"]
    request.origin = "moscow"
    second = next_question(request, DESTINATIONS)
    assert second.slot == "when"
    assert second.options == ["Ноябрь", "Декабрь", "Январь"]
    request.month = 11
    third = next_question(request, DESTINATIONS)
    assert third.slot == "children_ages"
    assert third.options == ["до 2", "2–6", "7–12", "13–17"]
    request.party.children_ages = [5]
    assert next_question(request, DESTINATIONS) is None
    assert request.destination is None  # направление спрашивает оркестратор


def test_exact_date_satisfies_when_and_year_wrap(monkeypatch):
    assert next_question(TripRequest(origin="moscow", date_from=date(2026, 11, 1)), []) is None

    class December(date):
        @classmethod
        def today(cls):
            return date(2026, 12, 25)

    monkeypatch.setattr(clarifier, "date", December)
    assert next_question(TripRequest(origin="moscow"), []).options == ["Январь", "Февраль", "Март"]


@pytest.mark.parametrize(
    ("slot", "text", "slug"),
    [
        ("origin", "Москва", "moscow"),
        ("origin", "из Масквы", "moscow"),
        ("destination", "Анталья", "antalya"),
        ("destination", "в Сочи", "sochi"),
        ("destination", "Турция", "antalya"),
        ("destination", "в Турцию", "antalya"),
        ("destination", "на Анталью", "antalya"),
    ],
)
def test_city_answer_is_resolved_by_slot(slot, text, slug):
    result = apply_answer(question(slot), text, TripRequest(), catalog=DESTINATIONS, today=TODAY)
    assert isinstance(result, Success)
    assert getattr(result.unwrap(), slot) == slug


@pytest.mark.parametrize("slot", ["origin", "destination"])
def test_unknown_city_is_failure_and_new_request_is_not_consumed(slot):
    result = apply_answer(
        question(slot), "Урюпинск", TripRequest(), catalog=DESTINATIONS, today=TODAY
    )
    assert isinstance(result, Failure) and isinstance(result.failure(), UnknownCity)
    assert (
        apply_answer(
            question(slot),
            "хочу на море с собакой",
            TripRequest(),
            catalog=DESTINATIONS,
            today=TODAY,
        )
        is None
    )


@pytest.mark.parametrize(
    ("text", "month", "start"),
    [
        ("Ноябрь", 11, None),
        ("в декабре", 12, None),
        ("5 ноября", None, date(2026, 11, 5)),
        # Прошедшая дата без года → следующий год, как в parse_when (сегодня 2026-10-25)
        ("15 марта", None, date(2027, 3, 15)),
        ("с 3 по 10 января", None, date(2027, 1, 3)),
        ("2026-11-07", None, date(2026, 11, 7)),
        ("через две недели", None, date(2026, 11, 8)),
    ],
)
def test_when_answer(text, month, start):
    result = apply_answer(question("when"), text, TripRequest(), catalog=DESTINATIONS, today=TODAY)
    assert isinstance(result, Success)
    assert result.unwrap().month == month and result.unwrap().date_from == start


def test_past_invalid_and_unrelated_when():
    for text, kind in [("2026-10-24", DatesInPast), ("31 ноября", NoResults)]:
        result = apply_answer(
            question("when"), text, TripRequest(), catalog=DESTINATIONS, today=TODAY
        )
        assert isinstance(result, Failure) and isinstance(result.failure(), kind)
    assert (
        apply_answer(
            question("when"), "с нами едет собака", TripRequest(), catalog=DESTINATIONS, today=TODAY
        )
        is None
    )
    assert (
        apply_answer(
            question("when"), "в ноябре с котом", TripRequest(), catalog=DESTINATIONS, today=TODAY
        )
        is None
    )


@pytest.mark.parametrize(
    ("text", "age", "assumed"),
    [
        ("до 2", 1, True),
        ("2–6", 4, True),
        ("7-12", 9, True),
        ("13–17", 15, True),
        ("5 лет", 5, False),
        ("5", 5, False),
        ("0", 0, False),
        ("17", 17, False),
    ],
)
def test_age_answer_preserves_known_ages_and_marks_ranges(text, age, assumed):
    request = TripRequest(party=Party(adults=3, children_ages=[8, None, None], pets=["dog"]))
    before = request.model_dump()
    result = apply_answer(
        question("children_ages"), text, request, catalog=DESTINATIONS, today=TODAY
    )
    updated = result.unwrap()
    assert updated.party.children_ages == [8, age, None]
    assert updated.party.adults == 3 and updated.party.pets == ["dog"]
    assert bool(updated.assumptions) is assumed
    assert request.model_dump() == before


def test_invalid_age_unrelated_input_and_no_unknown_child():
    request = TripRequest(party=Party(children_ages=[None]))
    result = apply_answer(
        question("children_ages"), "18", request, catalog=DESTINATIONS, today=TODAY
    )
    assert isinstance(result, Failure) and isinstance(result.failure(), NoResults)
    assert (
        apply_answer(
            question("children_ages"), "хочу в Сочи", request, catalog=DESTINATIONS, today=TODAY
        )
        is None
    )
    assert (
        apply_answer(
            question("children_ages"), "5", TripRequest(), catalog=DESTINATIONS, today=TODAY
        )
        is None
    )


@pytest.mark.parametrize(
    ("slot", "text"),
    [
        ("when", "в Сочи"),
        ("when", "в ноябре в Сочи"),
        ("origin", "в ноябре"),
        ("origin", "Москва в ноябре"),
    ],
)
def test_answer_for_another_slot_is_not_consumed(slot, text):
    assert (
        apply_answer(question(slot), text, TripRequest(), catalog=DESTINATIONS, today=TODAY) is None
    )
