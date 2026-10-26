"""Реальные функции ui в полном диалоге существующего оркестратора на фейках."""

import asyncio
import uuid
from datetime import date

from returns.result import Success

from tests.fakes import fake_sources, sample_package
from trip_pilot.agent.clarifier import apply_answer, next_question
from trip_pilot.agent.events import DoneEvent, PlanEvent, QuestionEvent
from trip_pilot.agent.intent import parse_change, parse_request
from trip_pilot.agent.orchestrator import AgentDeps, MvpOrchestrator
from trip_pilot.agent.toolkit import Toolkit
from trip_pilot.domain.trip_state import TripState
from trip_pilot.services.explanation import explain

TODAY = date(2026, 10, 25)


def build_example(request, outbound, inbound, hotels, transfers_by_hotel):
    # Сборка data здесь подменена общим фейком: проверяем связку функций ui.
    return Success(
        [
            sample_package(
                destination=request.destination,
                day=request.date_from,
                nights=request.nights,
                party=request.party,
            )
        ]
    )


def dialog():
    sources = fake_sources()
    toolkit = Toolkit(
        parse_request=parse_request,
        parse_change=parse_change,
        next_question=next_question,
        apply_answer=apply_answer,
        pick_destinations=lambda request, catalog: [city for city in catalog if "sea" in city.tags],
        simple_packages=build_example,
        check_package=lambda package: ["Проверка на фейках"],
        explain=explain,
    )
    deps = AgentDeps(
        catalog=sources.catalog,
        hotels=sources.hotels,
        transport=sources.transport,
        transfers=sources.transfers,
        trips=sources.trips,
        toolkit=toolkit,
    )
    return MvpOrchestrator(deps, today=lambda: TODAY), sources, uuid.uuid4(), deps


def say(agent, session, text):
    async def collect():
        return [event async for event in agent.handle(session, text)]

    events = asyncio.run(collect())
    assert isinstance(events[-1], DoneEvent)
    [plan] = [event for event in events if isinstance(event, PlanEvent)]
    TripState.model_validate(plan.data)
    return events


def state(sources, session):
    return asyncio.run(sources.trips.load(session))


def test_questions_answers_plan_and_replanning_with_real_ui_functions():
    agent, sources, session, _ = dialog()
    for text, slot in [
        ("Хочу на море с ребёнком до 200к", "origin"),
        ("Москва", "when"),
        ("Ноябрь", "children_ages"),
        ("2–6", "destination"),
    ]:
        events = say(agent, session, text)
        [question] = [event for event in events if isinstance(event, QuestionEvent)]
        assert question.text and state(sources, session).pending_question.slot == slot
    say(agent, session, "Анталья")
    trip = state(sources, session)
    assert trip.pending_question is None and trip.packages
    assert trip.request.month == 11 and trip.request.date_from is None
    assert trip.request.party.children_ages == [4]
    assert trip.search.check_in == date(2026, 11, 7)
    assert "Проверка на фейках" in trip.packages[0].risks
    assert any(item.field == "party.children_ages.0" for item in trip.request.assumptions)
    say(agent, session, "на два дня позже")
    assert state(sources, session).search.check_in == date(2026, 11, 9)
    say(agent, session, "бюджет меньше")
    assert state(sources, session).request.budget == 160000
    say(agent, session, "в декабре")
    assert state(sources, session).search.check_in == date(2026, 12, 5)
    say(agent, session, "в Сочи до 150к")
    assert state(sources, session).request.destination == "sochi"
    assert state(sources, session).request.budget == 150000


def test_pending_question_survives_new_orchestrator_and_bad_answer():
    agent, sources, session, deps = dialog()
    say(agent, session, "в ноябре")
    restored = MvpOrchestrator(deps, today=lambda: TODAY)
    say(restored, session, "Урюпинск")
    assert state(sources, session).pending_question.slot == "origin"
    say(restored, session, "Москва")
    assert state(sources, session).request.origin == "moscow"
    assert state(sources, session).pending_question.slot == "destination"
