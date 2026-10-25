"""Проверки Streamlit: события плана, восстановление вопросов и точный текст ответа."""

import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from trip_pilot.domain.trip_state import PendingQuestion, TripState

APP_PATH = Path(__file__).parents[2] / "src/trip_pilot/ui/app.py"
SESSION_ID = "00000000-0000-4000-8000-000000000002"


@pytest.fixture
def app_factory(monkeypatch):
    st.cache_resource.clear()
    source = APP_PATH.read_text(encoding="utf-8").replace(
        "DEMO_PLAN_ENABLED = True", "DEMO_PLAN_ENABLED = False"
    )

    def create(plan: dict, events: list[dict] | None = None):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                requests.append(json.loads(request.content))
                content = "".join(f"data: {json.dumps(event)}\n\n" for event in events or [])
                return httpx.Response(200, text=content, headers={
                    "content-type": "text/event-stream",
                })
            if request.url.path.endswith("/messages"):
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=plan)

        original_init = httpx.Client.__init__

        def init_client(client, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            original_init(client, *args, **kwargs)

        monkeypatch.setattr(httpx.Client, "__init__", init_client)
        app = AppTest.from_string(source)
        app.query_params["sid"] = SESSION_ID
        app.run()
        assert not app.exception
        return app, requests

    return create


@pytest.mark.parametrize(("slot", "choice"), [
    ("origin", "Казань"), ("when", "Ноябрь"),
    ("children_ages", "2–6"), ("destination", "Анталья"),
])
def test_restored_question_sends_exact_button_text(app_factory, slot: str, choice: str) -> None:
    plan = TripState(
        session_id=UUID(SESSION_ID),
        pending_question=PendingQuestion(slot=slot, text="Уточните поездку", options=[choice]),
    ).model_dump(mode="json")
    updated = {**plan, "version": 1, "pending_question": None}
    app, requests = app_factory(plan, [{"type": "plan", "data": updated}, {"type": "done"}])
    assert app.get("button_group")[0].options == [choice]
    assert len(app.chat_input) == 1
    app.get("button_group")[0].select(choice).run()
    assert not app.exception
    assert requests == [{"session_id": SESSION_ID, "text": choice}]
    assert app.session_state["plan"] == updated
    assert len(app.get("button_group")) == 0


def test_question_event_and_free_text_remain_available(app_factory) -> None:
    plan = TripState(session_id=UUID(SESSION_ID)).model_dump(mode="json")
    app, requests = app_factory(plan, [
        {"type": "question", "text": "Откуда вылетаете?", "options": ["Москва", "Казань"]},
        {"type": "done"},
    ])
    app.chat_input[0].set_value("Хочу на море").run()
    assert not app.exception
    assert app.get("button_group")[0].options == ["Москва", "Казань"]
    assert app.session_state["messages"][-1] == {
        "role": "assistant", "content": "Откуда вылетаете?",
    }
    app.chat_input[0].set_value("Санкт-Петербург").run()
    assert not app.exception
    assert [request["text"] for request in requests] == ["Хочу на море", "Санкт-Петербург"]


def test_order_without_packages_and_synthetic_label_without_demo_mode(app_factory) -> None:
    plan = TripState.model_validate_json(APP_PATH.with_name("sample_plan.json").read_text(
        encoding="utf-8"
    )).model_dump(mode="json")
    app, _ = app_factory(plan)
    assert any("Демо-данные" in caption.value for caption in app.caption)
    assert any("Баланс" in element.value for element in app.markdown)
    plan["packages"] = []
    plan["order"] = {
        "id": "TP-2026-000123", "package_id": "p1", "total": "100", "status": "paid",
        "created_at": "2026-10-25T12:00:00+03:00",
    }
    app.session_state["plan"] = plan
    app.run()
    assert not app.exception
    assert any("TP-2026-000123" in element.value for element in app.success)
    plan["order"]["status"] = "cancelled"
    app.session_state["plan"] = plan
    app.run()
    assert any("отменён" in element.value for element in app.info)
