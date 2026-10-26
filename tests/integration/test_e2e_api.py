"""e2e MVP через шлюз, как у жюри: запрос → ответ на вопрос → пакеты → выбор → заказ.

Запуск: docker compose --profile tests run --rm tests (поднимет стек, если он не запущен).
Синтетику создаёт bootstrap на 90 дней вперёд от сегодня, поэтому даты в запросе относительные.
"""

import os
import re
import uuid

import httpx
import pytest

from trip_pilot.agent.events import parse_event

BASE_URL = os.getenv("E2E_BASE_URL", "")

pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="нужен поднятый стек: docker compose --profile tests run --rm tests",
)


def chat(client: httpx.Client, session: str, **body) -> list:
    """Сообщение или действие → все события потока SSE. Поток всегда заканчивается done."""
    with client.stream("POST", "/api/chat", json={"session_id": session, **body}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = [
            parse_event(line.removeprefix("data: "))
            for line in resp.iter_lines()
            if line.startswith("data: ")
        ]
    assert events[-1].type == "done", events
    return events


def last_plan(events) -> dict:
    return [e for e in events if e.type == "plan"][-1].data


def test_mvp_path_through_gateway():
    session = str(uuid.uuid4())
    request = "Хочу на море из Москвы в Анталью через две недели на неделю вдвоём с ребёнком"
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        health = client.get("/health").json()

        asked = chat(client, session, text=request)
        [question] = [e for e in asked if e.type == "question"]

        found = last_plan(chat(client, session, text="2–6"))  # ответ — ровно текст кнопки
        package_id = found["packages"][-1]["id"]
        action = {"type": "select_package", "package_id": package_id}
        chosen = last_plan(chat(client, session, action=action))

        order_body = {
            "session_id": session,
            "package_id": package_id,
            "idempotency_key": f"e2e-{session}",
        }
        paid = client.post("/api/orders", json=order_body)
        again = client.post("/api/orders", json=order_body)

        # После F5 UI берёт план и историю отсюда.
        trip = client.get(f"/api/trips/{session}").json()
        history = client.get(f"/api/chat/{session}/messages").json()

    assert health == {"status": "ok"}
    assert question.options == ["до 2", "2–6", "7–12", "13–17"]

    assert found["packages"]
    assert found["pending_question"] is None
    assert found["request"]["party"]["children_ages"] == [4]
    assert found["search"]["nights"] == 7
    assert found["places"]["antalya"] == "Анталья"
    assert chosen["selected_package_id"] == package_id

    assert paid.status_code == 201
    order = paid.json()
    assert re.fullmatch(r"TP-\d{4}-\d{6}", order["id"])
    assert order["status"] == "paid"
    assert again.json()["id"] == order["id"]  # повтор с тем же ключом не создаёт второй заказ

    assert trip["order"]["id"] == order["id"]
    assert [m["role"] for m in history][:4] == ["user", "assistant", "user", "assistant"]
    assert history[0]["content"] == request
    assert "Сколько лет ребёнку" in history[1]["content"]
