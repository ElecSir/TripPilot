"""Проверки Streamlit: события плана, восстановление вопросов и точный текст ответа."""

import json
from pathlib import Path
from threading import Event
from uuid import UUID

import httpx
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from trip_pilot.domain.trip_state import PendingQuestion, TripState

APP_PATH = Path(__file__).parents[2] / "src/trip_pilot/ui/app.py"
SESSION_ID = "00000000-0000-4000-8000-000000000002"


def finish_run(app: AppTest) -> None:
    """Таймер фрагмента в AppTest заменяем явным чтением готовой очереди."""
    run = app.session_state["agent_run"]
    if run:
        assert run["stream"].wait(3)
        app.run()
    assert not app.exception
    assert app.session_state["agent_run"] is None


@pytest.fixture
def app_factory(monkeypatch):
    st.cache_resource.clear()
    source = APP_PATH.read_text(encoding="utf-8").replace(
        "DEMO_PLAN_ENABLED = True", "DEMO_PLAN_ENABLED = False"
    )

    def create(plan: dict, events: list[dict] | None = None, *, on_stream=None):
        requests = []

        class EventStream(httpx.SyncByteStream):
            def __iter__(self):
                for index, event in enumerate(events or []):
                    yield f"data: {json.dumps(event)}\n\n".encode()
                    if index == 1 and on_stream is not None:
                        on_stream()

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                requests.append(json.loads(request.content))
                return httpx.Response(200, stream=EventStream(), headers={
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
    finish_run(app)
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
    finish_run(app)
    assert not app.exception
    assert app.get("button_group")[0].options == ["Москва", "Казань"]
    assert app.session_state["messages"][-1] == {
        "role": "assistant", "content": "Откуда вылетаете?",
    }
    app.chat_input[0].set_value("Санкт-Петербург").run()
    finish_run(app)
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


def test_card_reviews_and_sources_survive_selection_and_reload(app_factory) -> None:
    plan = json.loads(APP_PATH.with_name("sample_plan.json").read_text(encoding="utf-8"))
    plan["packages"] = plan["packages"][:1]
    package = plan["packages"][0]
    package["issues"] = ["Один и тот же риск", "Только техническая проверка"]
    package["risks"] = ["Один и тот же риск", "Один и тот же риск"]
    plan["request"]["assumptions"] = [{
        "field": "party.children_ages.0", "value": "4", "reason": "Ответ диапазоном",
    }]
    app, _ = app_factory(plan)
    markdown = "\n".join(element.value for element in app.markdown)
    assert markdown.count("Один и тот же риск") == 1
    assert "Только техническая проверка" not in markdown
    assert "Ребёнку №1: 4 года" in markdown
    sources = [element.value for element in app.text if "Источники:" in element.value]
    assert len(sources) == 1
    assert "[S1] Анталья › С детьми (синтетика)" in sources[0]
    assert "[S2] Анталья › Транспорт (синтетика)" in sources[0]
    why_index = next(i for i, element in enumerate(app.main) if (
        element.type == "markdown" and "Почему подходит" in element.value
    ))
    sources_index = next(i for i, element in enumerate(app.main) if (
        element.type == "text" and "Источники:" in element.value
    ))
    assert why_index < sources_index
    assert not any("+0300" in element.value for element in app.get("markdown"))

    plan["selected_package_id"] = package["id"]
    app, _ = app_factory(plan)
    markdown = "\n".join(element.value for element in app.markdown)
    assert "Источники: [S1] Анталья › С детьми (синтетика)" in markdown
    assert "Почему подходит" in markdown
    assert "+0300" not in markdown
    package["sources"] = []
    app, _ = app_factory(plan)
    assert not any("Источники:" in element.value for element in app.markdown)
    plan["selected_package_id"] = None
    app, _ = app_factory(plan)
    assert not any("Источники:" in element.value for element in app.text)


def test_theme_change_during_stream_keeps_answer_and_does_not_repeat_post(app_factory) -> None:
    plan = TripState(session_id=UUID(SESSION_ID)).model_dump(mode="json")
    updated = {**plan, "version": 1}
    waiting = Event()
    release = Event()

    def pause_stream():
        waiting.set()
        assert release.wait(10)

    app, requests = app_factory(plan, [
        {"type": "stage", "stage": "search"},
        {"type": "delta", "text": "Найден план. "},
        {"type": "delta", "text": "Первая строка\n\n- Первый пункт\n- Второй пункт"},
        {"type": "plan", "data": updated},
        {"type": "done"},
    ], on_stream=pause_stream)
    try:
        app.chat_input[0].set_value("Хочу на море").run()
        assert waiting.wait(3)
        assert not app.session_state["agent_run"]["stream"].finished
        assert app.chat_input[0].disabled
        assert not app.toggle[0].disabled
        assert len(app.status) == 1
        assert app.status[0].state == "running"
        app.toggle[0].set_value(True).run()
        assert not app.exception
        assert app.session_state["ui_dark_mode"] is True
        assert len(app.status) == 1
        assert app.status[0].state == "running"
        assert [caption.value for caption in app.status[0].caption] == [
            "Подробности этапа ещё не получены.",
        ]
        assert any("--trip-bg: #101827" in element.value for element in app.markdown)
        assert any("Найден план." in element.value for element in app.markdown)
        assert not release.is_set()
        assert not app.session_state["agent_run"]["stream"].finished
        assert len(requests) == 1
        # Пока ответ ещё не закончен, можно переключить тему обратно.
        app.toggle[0].set_value(False).run()
        assert app.session_state["ui_dark_mode"] is False
        assert app.status[0].state == "running"
        assert any("--trip-bg: #f5f8fc" in element.value for element in app.markdown)
    finally:
        release.set()
    finish_run(app)
    assert requests == [{"session_id": SESSION_ID, "text": "Хочу на море"}]
    assert app.session_state["plan"] == updated
    assert app.session_state["ui_dark_mode"] is False
    assert app.session_state["messages"] == [
        {"role": "user", "content": "Хочу на море"},
        {"role": "assistant", "content": (
            "Найден план. Первая строка\n\n- Первый пункт\n- Второй пункт"
        )},
    ]
    app.toggle[0].set_value(True).run()
    assert not app.exception
    assert len(requests) == 1
    assert app.session_state["messages"][-1]["content"].endswith("- Второй пункт")


def test_package_selection_uses_background_stream_and_updates_basket(app_factory) -> None:
    plan = json.loads(APP_PATH.with_name("sample_plan.json").read_text(encoding="utf-8"))
    package_id = plan["packages"][0]["id"]
    updated = {**plan, "version": plan["version"] + 1, "selected_package_id": package_id}
    app, requests = app_factory(plan, [{"type": "plan", "data": updated}, {"type": "done"}])
    app.button(key=f"select_{package_id}").click().run()
    finish_run(app)
    assert requests == [{
        "session_id": SESSION_ID,
        "action": {"type": "select_package", "package_id": package_id},
    }]
    assert app.session_state["plan"]["selected_package_id"] == package_id
    assert any("Корзина" in element.value for element in app.markdown)


def test_background_stream_error_leaves_theme_available(app_factory) -> None:
    plan = TripState(session_id=UUID(SESSION_ID)).model_dump(mode="json")
    app, requests = app_factory(plan, [{"type": "error", "text": "Ничего не найдено"}])
    app.chat_input[0].set_value("Хочу на море").run()
    finish_run(app)
    assert any("Ничего не найдено" in element.value for element in app.error)
    assert not app.chat_input[0].disabled
    app.toggle[0].set_value(True).run()
    assert not app.exception
    assert app.session_state["ui_dark_mode"] is True
    assert len(requests) == 1


def test_progress_poll_keeps_details_without_restarting_status() -> None:
    definitions = APP_PATH.read_text(encoding="utf-8").split("\nsid = session_id()", 1)[0]
    harness = '''
class Stream:
    finished = False

    def __init__(self):
        self.batches = [
            [StageEvent(stage="intake"), StepEvent(text="Начал поиск"), DeltaEvent(text="Ответ")],
            [], [StageEvent(stage="intake")], [], [StageEvent(stage="search")], [],
        ]

    def drain(self):
        return self.batches.pop(0)

class Status:
    def update(self, **kwargs):
        st.session_state.updates.append(kwargs)

class Details:
    def markdown(self, text):
        st.session_state.detail_frames.append(text)

    def caption(self, text):
        st.session_state.detail_frames.append(text)

class Answer:
    def markdown(self, text):
        st.session_state.replies.append(text)

st.session_state.updates = []
st.session_state.detail_frames = []
st.session_state.replies = []
st.session_state.agent_run = {
    "stream": Stream(), "stage": "Агент работает…", "reply": "", "steps": [],
}
panel, details, answer = Status(), Details(), Answer()
for _ in range(6):
    render_agent_progress(panel, details, answer)
'''
    app = AppTest.from_string(definitions + harness).run()
    assert not app.exception
    assert app.session_state["updates"] == [
        {"label": "Разбираю запрос", "state": "running"},
        {"label": "Ищу варианты", "state": "running"},
    ]
    assert app.session_state["detail_frames"] == ["- Начал поиск"] * 6
    assert app.session_state["agent_run"]["steps"] == ["Начал поиск"]
    assert app.session_state["replies"] == ["Ответ"]


def test_progress_keeps_spinner_on_later_request_and_after_theme_change(app_factory) -> None:
    plan = TripState(session_id=UUID(SESSION_ID)).model_dump(mode="json")
    waiting, release = Event(), Event()
    responses = []

    def pause_second_response():
        responses.append(True)
        if len(responses) == 2:
            waiting.set()
            assert release.wait(15)

    app, requests = app_factory(plan, [
        {"type": "stage", "stage": "intake"},
        {"type": "delta", "text": "Начало ответа. "},
        {"type": "delta", "text": "Ответ закончен."},
        {"type": "done"},
    ], on_stream=pause_second_response)
    app.chat_input[0].set_value("Первый запрос").run()
    finish_run(app)
    try:
        app.chat_input[0].set_value("Второй запрос").run()
        assert waiting.wait(3)
        for dark in (False, True, True, False):
            app.toggle[0].set_value(dark).run()
            assert not app.exception
            assert not app.session_state["agent_run"]["stream"].finished
            assert len(app.status) == 1
            assert app.status[0].state == "running"
            assert app.status[0].icon == "spinner"
            assert app.status[0].label == "Разбираю запрос"
            assert len(requests) == 2
    finally:
        release.set()
    finish_run(app)
    app.chat_input[0].set_value("Третий запрос").run()
    finish_run(app)
    assert len(requests) == 3
    assert len(app.session_state["messages"]) == 6


def test_received_steps_stay_in_expanded_status_during_wait(app_factory) -> None:
    plan = TripState(session_id=UUID(SESSION_ID)).model_dump(mode="json")
    waiting, release = Event(), Event()

    def pause_stream():
        waiting.set()
        assert release.wait(10)

    app, _ = app_factory(plan, [
        {"type": "stage", "stage": "search"},
        {"type": "step", "text": "Ищу перелёты туда"},
        {"type": "step", "text": "Ищу отели"},
        {"type": "delta", "text": "Готово"},
        {"type": "done"},
    ], on_stream=pause_stream)
    try:
        app.chat_input[0].set_value("Хочу на море").run()
        assert waiting.wait(3)
        for dark in (False, True, False):
            app.toggle[0].set_value(dark).run()
            assert not app.exception
            assert app.status[0].state == "running"
            assert [point.value for point in app.status[0].markdown] == ["- Ищу перелёты туда"]
            assert app.session_state["agent_run"]["steps"] == ["Ищу перелёты туда"]
    finally:
        release.set()
    finish_run(app)
