"""API-контракт для ui: форма запросов и ответы маршрутов, которые ещё в работе."""

from fastapi.testclient import TestClient

from trip_pilot.agent.events import parse_event
from trip_pilot.api.main import create_app

SESSION = "6f1c1a52-6c4e-4a43-9a51-2a8a3c9f1a10"


def client() -> TestClient:
    return TestClient(create_app())


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
    with client() as c, c.stream("POST", "/api/chat", json=payload) as resp:
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
        resp = c.get(f"/api/trips/{SESSION}")
    assert resp.status_code == 404


def test_order_contract_is_published_but_not_implemented_yet():
    with client() as c:
        bad = c.post("/api/orders", json={"session_id": SESSION, "package_id": "p1"})
        ok_shape = c.post(
            "/api/orders",
            json={"session_id": SESSION, "package_id": "p1", "idempotency_key": "attempt-0001"},
        )
        schema = c.get("/api/openapi.json").json()
    assert bad.status_code == 422  # без idempotency_key заказ не принимается
    assert ok_shape.status_code == 501
    assert "/api/orders" in schema["paths"]
    assert "/api/trips/{session_id}" in schema["paths"]
