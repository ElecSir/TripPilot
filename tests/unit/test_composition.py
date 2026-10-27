"""Сборка агента из api/main.py: настоящие функции ui и data проходят путь MVP на фейках."""

import asyncio
import uuid
from datetime import date

from fastapi.testclient import TestClient

from tests.fakes import FakeLLM, fake_sources
from trip_pilot.agent.actions import SelectPackage
from trip_pilot.agent.events import PlanEvent, QuestionEvent, StepEvent
from trip_pilot.agent.orchestrator import AgentDeps, MvpOrchestrator
from trip_pilot.api.main import TOOLKIT, create_app
from trip_pilot.domain.trip_state import TripState

TODAY = date(2026, 10, 26)


def agent_on_fakes(llm=None) -> MvpOrchestrator:
    src = fake_sources()
    deps = AgentDeps(
        catalog=src.catalog, hotels=src.hotels, transport=src.transport,
        transfers=src.transfers, trips=src.trips, toolkit=TOOLKIT, knowledge=src.knowledge,
        **({"llm": llm} if llm is not None else {}),
    )
    return MvpOrchestrator(deps, today=lambda: TODAY)


def run(events):
    async def collect():
        return [e async for e in events]

    return asyncio.run(collect())


def plan_of(events) -> TripState:
    return TripState.model_validate(next(e for e in events if isinstance(e, PlanEvent)).data)


def test_app_uses_mvp_orchestrator():
    with TestClient(create_app()) as c:
        assert isinstance(c.app.state.orchestrator, MvpOrchestrator)


def test_real_toolkit_goes_from_request_to_checkout():
    agent, session = agent_on_fakes(), uuid.uuid4()

    first = run(agent.handle(session, "На море из Москвы в Анталью в ноябре вдвоём с ребёнком"))
    question = next(e for e in first if isinstance(e, QuestionEvent))
    assert question.options == ["до 2", "2–6", "7–12", "13–17"]  # clarifier ui

    found = plan_of(run(agent.handle(session, "2–6")))
    assert found.request.party.children_ages == [4]
    assert found.search.check_in == date(2026, 11, 7)  # ближайшая суббота ноября
    assert {p.tier for p in found.packages} == {"economy", "balance", "comfort"}  # пакеты data
    assert all(p.why for p in found.packages)  # объяснения ui
    assert found.places == {"antalya": "Анталья", "moscow": "Москва"}

    shifted = plan_of(run(agent.handle(session, "на 2 дня позже")))  # parse_change ui
    assert shifted.search.check_in == date(2026, 11, 9)

    package_id = shifted.packages[0].id
    chosen = plan_of(run(agent.handle_action(session, SelectPackage(package_id=package_id))))
    assert chosen.stage == "checkout"
    assert chosen.selected_package_id == package_id


def test_without_key_agent_does_not_claim_ai():
    # Ключа нет: модель не вызывается, шагов «с помощью ИИ» быть не должно,
    # путь тот же, что в MVP.
    events = run(agent_on_fakes().handle(uuid.uuid4(), "Из Москвы в Анталью в ноябре"))
    steps = [e.text for e in events if isinstance(e, StepEvent)]
    assert not [s for s in steps if "с помощью ИИ" in s]
    assert plan_of(events).packages  # путь тот же, что в MVP


def test_with_key_model_understanding_keeps_the_same_path():
    # Ключ есть и модель ответила черновиком: запрос собирает код, путь тот же,
    # а шаг «с помощью ИИ» появляется по факту ответа модели, а не по факту ключа.
    draft = '{"origin": "moscow", "destination": "Анталья", "month": 11}'
    events = run(
        agent_on_fakes(FakeLLM([draft])).handle(uuid.uuid4(), "Из Москвы в Анталью в ноябре")
    )
    steps = [e.text for e in events if isinstance(e, StepEvent)]
    assert [s for s in steps if "с помощью ИИ" in s]
    plan = plan_of(events)
    assert plan.request.origin == "moscow" and plan.request.destination == "antalya"
    assert plan.packages
