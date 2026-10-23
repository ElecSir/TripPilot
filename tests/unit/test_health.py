from fastapi.testclient import TestClient

from trip_pilot.api.health import database_ok
from trip_pilot.api.main import create_app


def make_client(db_ok: bool) -> TestClient:
    app = create_app()
    app.dependency_overrides[database_ok] = lambda: db_ok
    return TestClient(app)


def test_health_ok_when_db_available():
    with make_client(db_ok=True) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_degraded_when_db_unavailable():
    with make_client(db_ok=False) as client:
        resp = client.get("/health")

    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"


def test_chat_rejects_empty_text():
    with make_client(db_ok=True) as client:
        resp = client.post(
            "/api/chat",
            json={"session_id": "6f1c1a52-6c4e-4a43-9a51-2a8a3c9f1a10", "text": ""},
        )

    assert resp.status_code == 422
