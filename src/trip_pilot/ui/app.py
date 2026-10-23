"""Streamlit-клиент. Тонкий: вся логика в API, здесь только отрисовка событий агента."""

import uuid
from collections.abc import Iterator

import httpx
import streamlit as st

from trip_pilot.agent.events import (
    AgentEvent,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    StageEvent,
    StepEvent,
    parse_event,
)
from trip_pilot.config import get_settings

STAGE_LABELS = {
    "intake": "Разбираю запрос",
    "clarify": "Уточняю",
    "inspire": "Подбираю направления",
    "search": "Ищу варианты",
    "compare": "Сравниваю",
    "assemble": "Собираю поездку",
    "checkout": "Оформление",
}

st.set_page_config(page_title="TripPilot", page_icon="🧳", layout="wide")


@st.cache_resource
def api_client() -> httpx.Client:
    return httpx.Client(base_url=get_settings().api_url, timeout=httpx.Timeout(60, connect=5))


def session_id() -> str:
    """id диалога живёт в адресе страницы (?sid=…), поэтому F5 не теряет переписку."""
    sid = st.query_params.get("sid")
    try:
        return str(uuid.UUID(sid))
    except (TypeError, ValueError):
        sid = str(uuid.uuid4())
        st.query_params["sid"] = sid
        return sid


def load_history(sid: str) -> list[dict]:
    try:
        resp = api_client().get(f"/api/chat/{sid}/messages")
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError:
        st.warning("Не удалось загрузить историю диалога: API недоступен.")
        return []


def stream_events(sid: str, text: str) -> Iterator[AgentEvent]:
    payload = {"session_id": sid, "text": text}
    with api_client().stream("POST", "/api/chat", json=payload) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line.startswith("data: "):
                yield parse_event(line.removeprefix("data: "))


def run_agent(sid: str, text: str) -> str | None:
    status = st.status("Агент работает…")
    answer = st.empty()
    reply = ""
    try:
        for event in stream_events(sid, text):
            match event:
                case StageEvent(stage=stage):
                    status.update(label=STAGE_LABELS.get(stage, stage))
                case StepEvent(text=step):
                    status.write(step)
                case DeltaEvent(text=delta):
                    reply += delta
                    answer.markdown(reply)
                case ErrorEvent(text=error):
                    status.update(label="Ошибка", state="error")
                    st.error(error)
                    return None
                case DoneEvent():
                    break
    except httpx.HTTPError:
        status.update(label="API недоступен", state="error")
        st.error("Не удалось связаться с API. Попробуйте ещё раз через минуту.")
        return None
    status.update(label="Готово", state="complete")
    return reply.strip()


sid = session_id()
if "messages" not in st.session_state:
    st.session_state.messages = load_history(sid)

st.title("TripPilot")
st.caption("Опишите поездку своими словами: куда, когда, с кем и на какой бюджет.")

chat_col, plan_col = st.columns([3, 2], gap="large")

with plan_col, st.container(border=True):
    st.subheader("Ваша поездка")
    st.caption("Демо-данные: цены и наличие синтетические")
    st.info("Здесь появится план: допущения агента, три пакета, таймлайн стыковок и корзина.")

with chat_col:
    history_box = st.container(height=520)
    with history_box:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    prompt = st.chat_input("Например: к тёплому морю в ноябре, недорого, с ребёнком")
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with history_box:
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                reply = run_agent(sid, prompt)
        if reply:
            st.session_state.messages.append({"role": "assistant", "content": reply})
