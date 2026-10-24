"""Streamlit-клиент TripPilot: диалог и адаптивные карточки поездки."""

import json
import logging
import uuid
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

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

LOGGER = logging.getLogger(__name__)
DEMO_PLAN_ENABLED = True  # Отключить после интеграции события plan.
SAMPLE_PLAN_PATH = Path(__file__).with_name("sample_plan.json")
TIER_LABELS = {"economy": "Эконом", "comfort": "Комфорт", "premium": "Премиум"}
ASSUMPTION_LABELS = {"origin": "из Москвы", "nights": "7 ночей"}
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


@st.cache_data
def sample_plan() -> dict:
    with SAMPLE_PLAN_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def session_id() -> str:
    """ID диалога хранится в URL, чтобы F5 не терял переписку."""
    sid = st.query_params.get("sid")
    try:
        return str(uuid.UUID(sid))
    except (TypeError, ValueError):
        sid = str(uuid.uuid4())
        st.query_params["sid"] = sid
        return sid


def load_history(sid: str) -> list[dict]:
    try:
        response = api_client().get(f"/api/chat/{sid}/messages")
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError:
        st.warning("Не удалось загрузить историю диалога: API недоступен.")
        return []


def load_plan(sid: str) -> dict:
    """До подключения API отображаем явно отмеченный синтетический пример."""
    if DEMO_PLAN_ENABLED:
        return sample_plan()
    try:
        response = api_client().get(f"/api/trips/{sid}")
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError:
        LOGGER.exception("Не удалось загрузить план поездки")
        return {}


def stream_events(sid: str, text: str | None = None, action: dict | None = None) -> Iterator[AgentEvent]:
    payload = {"session_id": sid}
    if action is not None:
        payload["action"] = action
    else:
        payload["text"] = text or ""
    with api_client().stream("POST", "/api/chat", json=payload) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("data: "):
                yield parse_event(line.removeprefix("data: "))


def run_agent(sid: str, text: str | None = None, action: dict | None = None) -> str | None:
    status = st.status("Агент работает…")
    answer = st.empty()
    reply = ""
    try:
        for event in stream_events(sid, text=text, action=action):
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
                case _:
                    # PlanEvent обрабатываем без импорта: контракт лида может обновиться.
                    if getattr(event, "type", None) == "plan":
                        st.session_state.plan = event.data
    except (httpx.HTTPError, ValueError):
        status.update(label="API недоступен", state="error")
        st.error("Не удалось связаться с API. Повторите попытку позже.")
        return None
    status.update(label="Готово", state="complete")
    return reply.strip()


def price(value: object) -> str:
    try:
        amount = Decimal(str(value))
        return f"{amount:,.0f}".replace(",", " ") + " ₽"
    except (InvalidOperation, TypeError):
        return "Цена уточняется"


def flight_text(flight: dict | None) -> str:
    if not flight:
        return "Данные о рейсе уточняются"
    try:
        departure = datetime.fromisoformat(flight["departure"])
        arrival = datetime.fromisoformat(flight["arrival"])
        route = f"{flight.get('from', '—')} → {flight.get('to', '—')}"
        nonstop = " · прямой" if flight.get("direct") else ""
        return f"{route} · {departure:%d.%m %H:%M} → {arrival:%d.%m %H:%M}{nonstop}"
    except (KeyError, TypeError, ValueError):
        return "Данные о рейсе уточняются"


def render_points(label: str, values: list, *, warning: bool = False) -> None:
    if not values:
        return
    st.markdown(f"**{label}**")
    for value in values[:3]:
        prefix = "⚠️" if warning else "•"
        st.markdown(f"{prefix} {value}")


def render_assumptions(plan: dict) -> None:
    assumptions = plan.get("request", {}).get("assumptions", [])
    if not assumptions:
        return
    st.markdown("**Допущения агента**")
    chips = []
    for assumption in assumptions:
        field = assumption.get("field", "")
        value = assumption.get("value", "")
        label = ASSUMPTION_LABELS.get(field, str(value))
        chips.append(f"`{label} ✎`")
    st.markdown("  ".join(chips))
    with st.expander("Почему агент сделал эти допущения?"):
        for assumption in assumptions:
            st.write(f"{assumption.get('field', 'Поле')}: {assumption.get('reason', 'Не указано')}")
    st.caption("✎ Редактирование допущений появится после MVP")


def select_package(sid: str, package_id: str) -> None:
    if DEMO_PLAN_ENABLED:
        st.session_state.demo_selected_package_id = package_id
        st.toast("Демонстрационный пакет выбран")
        return
    run_agent(sid, action={"type": "select_package", "package_id": package_id})
    st.session_state.plan = load_plan(sid)


def render_package(package: dict, sid: str, selected_id: str | None) -> None:
    """Карточка растягивается на ширину своей колонки без пиксельных размеров."""
    package_id = package.get("id", "")
    hotel = package.get("hotel") or {}
    transfer = package.get("transfer") or {}
    tier = TIER_LABELS.get(package.get("tier"), package.get("tier", "Пакет"))
    with st.container(border=True):
        st.subheader(tier)
        st.metric("Стоимость всей поездки", price(package.get("total")))
        st.caption(f"{package.get('nights', '—')} ночей · за всех путешественников")
        stars = hotel.get("stars")
        stars_label = f" · {stars}★" if stars else ""
        st.markdown(f"**🏨 {hotel.get('name', 'Отель уточняется')}{stars_label}**")
        st.markdown("**✈️ Туда**")
        st.write(flight_text(package.get("outbound")))
        st.markdown("**✈️ Обратно**")
        st.write(flight_text(package.get("inbound")))
        transfer_label = transfer.get("description") or "Информация уточняется"
        if transfer.get("included") is False:
            transfer_label += " · не включён"
        st.markdown(f"**🚐 Трансфер:** {transfer_label}")
        render_points("Почему подходит", package.get("why") or [])
        render_points("Чем жертвуем", package.get("tradeoffs") or [])
        render_points("Риски", (package.get("issues") or []) + (package.get("risks") or []), warning=True)
        selected = selected_id == package_id
        st.button(
            "✓ Выбрано" if selected else "Выбрать",
            key=f"select_{package_id}",
            type="primary" if selected else "secondary",
            use_container_width=True,
            disabled=selected or not package_id,
            on_click=select_package,
            args=(sid, package_id),
        )


def render_plan(plan: dict, sid: str) -> None:
    st.divider()
    st.header("Ваша поездка")
    if DEMO_PLAN_ENABLED or plan.get("is_synthetic") or plan.get("source") == "synthetic":
        st.caption("🧪 Демо-данные: цены, расписания и наличие синтетические")
    if not plan:
        st.info("Когда агент подберёт варианты, они появятся здесь.")
        return
    render_assumptions(plan)
    packages = plan.get("packages") or []
    if not packages:
        st.info("Пакеты пока не сформированы.")
        return
    selected_id = (
        st.session_state.get("demo_selected_package_id")
        if DEMO_PLAN_ENABLED
        else plan.get("selected_package_id")
    )
    # Streamlit перестраивает колонки в вертикальный стек на узких экранах.
    columns = st.columns(3, gap="medium") if len(packages) >= 3 else st.columns(len(packages))
    for index, package in enumerate(packages):
        with columns[index % len(columns)]:
            render_package(package, sid, selected_id)
    if selected_id:
        chosen = next((item for item in packages if item.get("id") == selected_id), None)
        if chosen:
            st.success(f"Выбран пакет «{TIER_LABELS.get(chosen.get('tier'), 'Пакет')}» — {price(chosen.get('total'))}.")
            st.caption("Корзину и оформление добавим во второй задаче.")


sid = session_id()
if st.session_state.get("active_sid") != sid:
    st.session_state.active_sid = sid
    st.session_state.messages = load_history(sid)
    st.session_state.plan = load_plan(sid)
    st.session_state.demo_selected_package_id = None

st.title("TripPilot")
st.caption("Опишите поездку своими словами: куда, когда, с кем и на какой бюджет.")

# Чат использует всю доступную ширину, а три карточки — полноценную сетку ниже.
with st.container():
    st.subheader("Диалог")
    history_box = st.container(height=380)
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
                reply = run_agent(sid, text=prompt)
        if reply:
            st.session_state.messages.append({"role": "assistant", "content": reply})

render_plan(st.session_state.plan, sid)
