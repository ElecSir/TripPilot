"""API-контракт для ui: форма запросов и ответы маршрутов. Хранилища подменены фейками."""

import asyncio
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from tests.fakes import FakeSources, fake_sources, sample_package
from trip_pilot.agent.events import DoneEvent, StepEvent, parse_event
from trip_pilot.api.main import create_app
from trip_pilot.domain.trip_state import TripState

SESSION = "6f1c1a52-6c4e-4a43-9a51-2a8a3c9f1a10"


class EchoAgent:
    """Двойник агента: здесь проверяется маршрут, а не оркестратор (он — в test_orchestrator)."""

    async def handle_action(self, session_id, action):
        yield StepEvent(text=f"Выбран пакет {action.package_id}")
        yield DoneEvent()


def client() -> TestClient:
    return TestClient(create_app())


@contextmanager
def api_with_plan() -> Iterator[tuple[TestClient, FakeSources]]:
    """API на фейковых хранилищах с готовым планом из двух пакетов для SESSION."""
    src = fake_sources()
    state = TripState(
        session_id=uuid.UUID(SESSION),
        packages=[sample_package("p1"), sample_package("p2", destination="sochi")],
    )
    asyncio.run(src.trips.save(state))
    with client() as c:
        c.app.state.trips = src.trips
        c.app.state.orders = src.orders
        yield c, src


def order_body(package_id: str = "p1", key: str = "attempt-0001") -> dict:
    return {"session_id": SESSION, "package_id": package_id, "idempotency_key": key}


def test_chat_needs_exactly_one_of_text_or_action():
    with client() as c:
        neither = c.post("/api/chat", json={"session_id": SESSION})
        both = c.post(
            "/api/chat",
            json={
                "session_id": SESSION,
                "text": "в Сочи",
                "action": {"type": "select_package", "package_id": "p1"},
            },
        )
    assert neither.status_code == 422
    assert both.status_code == 422


def test_select_package_action_streams_events():
    payload = {"session_id": SESSION, "action": {"type": "select_package", "package_id": "p2"}}
    with client() as c:
        c.app.state.orchestrator = EchoAgent()
        with c.stream("POST", "/api/chat", json=payload) as resp:
            assert resp.status_code == 200
            events = [
                parse_event(line.removeprefix("data: "))
                for line in resp.iter_lines()
                if line.startswith("data: ")
            ]
    assert events[-1].type == "done"
    assert any(e.type == "step" and "p2" in e.text for e in events)


def test_trip_is_not_found_until_plan_exists():
    with client() as c:
        c.app.state.trips = fake_sources().trips
        resp = c.get(f"/api/trips/{SESSION}")
    assert resp.status_code == 404


def test_trip_is_returned_as_plan_json():
    with api_with_plan() as (c, _):
        resp = c.get(f"/api/trips/{SESSION}")
    assert resp.status_code == 200
    plan = resp.json()
    assert [p["id"] for p in plan["packages"]] == ["p1", "p2"]
    assert plan["packages"][0]["total"] == str(sample_package("p1").total)  # деньги — строкой


def test_order_is_created_and_repeat_is_idempotent():
    with api_with_plan() as (c, _):
        first = c.post("/api/orders", json=order_body())
        again = c.post("/api/orders", json=order_body())
        plan = c.get(f"/api/trips/{SESSION}").json()
    assert first.status_code == 201
    assert first.json()["id"].startswith("TP-")
    assert first.json()["status"] == "paid"
    assert again.json()["id"] == first.json()["id"]
    assert plan["order"]["id"] == first.json()["id"]
    assert plan["selected_package_id"] == "p1"


def test_order_errors():
    with client() as c:
        c.app.state.trips = fake_sources().trips
        no_plan = c.post("/api/orders", json=order_body())
        no_key = c.post("/api/orders", json={"session_id": SESSION, "package_id": "p1"})
    with api_with_plan() as (c, _):
        unknown = c.post("/api/orders", json=order_body("p9"))
        c.post("/api/orders", json=order_body("p1"))
        other = c.post("/api/orders", json=order_body("p2", key="attempt-0002"))
        schema = c.get("/api/openapi.json").json()
    assert no_plan.status_code == 404
    assert no_key.status_code == 422  # без idempotency_key заказ не принимается
    assert unknown.status_code == 404
    assert other.status_code == 409
    assert "/api/orders" in schema["paths"]
