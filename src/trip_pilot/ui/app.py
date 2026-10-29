"""Streamlit-клиент TripPilot: диалог и адаптивные карточки поездки."""

import json
import logging
import uuid
from html import escape
from pathlib import Path

import httpx
import streamlit as st

from trip_pilot.agent.events import (
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    PlanEvent,
    QuestionEvent,
    StageEvent,
    StepEvent,
)
from trip_pilot.config import get_settings
from trip_pilot.ui.agent_stream import AgentStream
from trip_pilot.ui.cart_view import (
    cart_details_html,
    cart_header_html,
    cart_prices_html,
)
from trip_pilot.ui.checkout import (
    breakdown_matches_total,
    money,
    pay_once,
    prepare_attempt,
)
from trip_pilot.ui.plan_view import (
    TIER_LABELS,
    assumption_label,
    flight_text,
    has_synthetic_offers,
    hotel_details,
    plan_assumptions,
    sources_text,
    transfer_text,
)
from trip_pilot.ui.theme import theme_css

LOGGER = logging.getLogger(__name__)
DEMO_PLAN_ENABLED = False  # Отключить после интеграции события plan.
SAMPLE_PLAN_PATH = Path(__file__).with_name("sample_plan.json")
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


def apply_theme(dark: bool) -> None:
    """Применяет палитру без привязки карточек к внутренним wrapper Streamlit."""
    st.markdown(theme_css(dark), unsafe_allow_html=True)


@st.fragment
def render_theme_toggle() -> None:
    """Смена темы не перезапускает чтение потока ответа агента."""
    dark = st.toggle("Тёмная тема", key="ui_dark_mode")
    apply_theme(dark)


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


def run_agent(sid: str, text: str | None = None, action: dict | None = None) -> None:
    """Создаёт один запрос; перерисовки экрана сохраняют тот же рабочий поток."""
    if st.session_state.get("agent_run"):
        return
    payload = {"session_id": sid}
    if action is not None:
        payload["action"] = action
    else:
        payload["text"] = text or ""
    st.session_state.agent_error = None
    st.session_state.agent_run = {
        "stream": AgentStream(api_client(), payload),
        "reply": "", "question": "", "stage": "Агент работает…", "steps": [], "error": None,
    }


@st.fragment(run_every=0.2)
def render_agent_progress(status, details, answer) -> None:
    """Короткое чтение очереди оставляет экран свободным для переключения темы."""
    run = st.session_state.get("agent_run")
    if not run:
        return
    stream = run["stream"]
    previous_stage = run["stage"]
    previous_reply = run["reply"]
    # Сначала проверяем завершение: иначе можно пропустить последние события очереди.
    finished = stream.finished
    for event in stream.drain():
        match event:
            case StageEvent(stage=stage):
                run["stage"] = STAGE_LABELS.get(stage, stage)
            case StepEvent(text=step):
                run["steps"].append(step)
            case DeltaEvent(text=delta):
                run["reply"] += delta
            case ErrorEvent(text=error):
                run["error"] = error
            case QuestionEvent(text=question, options=options):
                run["question"] = question
                st.session_state.pending_question = {"text": question, "options": options}
            case PlanEvent(data=data):
                st.session_state.plan = data
                st.session_state.pending_question = data.get("pending_question")
            case DoneEvent():
                pass
    if finished:
        reply = run["reply"].strip() or run["question"]
        if reply:
            st.session_state.messages.append({"role": "assistant", "content": reply})
        st.session_state.agent_error = run["error"] or stream.error
        st.session_state.agent_run = None
        st.rerun()
    if run["stage"] != previous_stage:
        status.update(label=run["stage"], state="running")
    # Обновляем один слот: шаги остаются видны и при следующем пустом опросе фрагмента.
    if run["steps"]:
        details.markdown("\n".join(f"- {step}" for step in run["steps"]))
    else:
        details.caption("Подробности этапа ещё не получены.")
    if run["reply"] != previous_reply:
        answer.markdown(run["reply"])


def render_points(label: str, values: list, *, warning: bool = False) -> None:
    if not values:
        return
    st.markdown(f"**{label}**")
    for value in values[:3]:
        prefix = "⚠️" if warning else "•"
        st.markdown(f"{prefix} {value}")


def render_assumptions(plan: dict) -> None:
    assumptions = plan_assumptions(plan)
    if not assumptions:
        return
    st.markdown("**Допущения агента**")
    chips = []
    for assumption in assumptions:
        label = assumption_label(assumption, plan.get("places"))
        chips.append(
            f'<span class="trip-chip">{escape(label)} <span aria-hidden="true">✎</span></span>'
        )
    st.markdown(
        '<div class="trip-chip-list">' + "".join(chips) + "</div>",
        unsafe_allow_html=True,
    )
    with st.container(key="assumptions_explanation"):
        with st.expander("Почему агент сделал эти допущения?"):
            for assumption in assumptions:
                st.write(
                    f"{assumption.get('field', 'Поле')}: "
                    f"{assumption.get('reason', 'Не указано')}"
                )
    st.caption("✎ Редактирование допущений появится после MVP")


def select_package(sid: str, package_id: str) -> None:
    if st.session_state.get("agent_run"):
        return
    # При выборе другого пакета старый платёж не должен использоваться повторно.
    st.session_state.checkout_attempt = None
    st.session_state.checkout_dialog_open = False
    st.session_state.compare_packages = False
    if DEMO_PLAN_ENABLED:
        st.session_state.demo_selected_package_id = package_id
        st.toast("Демонстрационный пакет выбран")
        return
    run_agent(sid, action={"type": "select_package", "package_id": package_id})


def render_package(
    package: dict, sid: str, selected_id: str | None, places: dict[str, str]
) -> None:
    """Карточка растягивается на ширину своей колонки без пиксельных размеров."""
    package_id = package.get("id", "")
    hotel = package.get("hotel") or {}
    tier = TIER_LABELS.get(package.get("tier"), package.get("tier", "Пакет"))
    st.markdown(
        f'<h3 class="trip-card-marker">{escape(str(tier))}</h3>',
        unsafe_allow_html=True,
    )
    st.metric("Стоимость всей поездки", money(package.get("total")))
    st.caption(f"{package.get('nights', '—')} ночей · за всех путешественников")
    stars = hotel.get("stars")
    stars_label = f" · {stars}★" if stars else ""
    st.markdown(f"**🏨 {hotel.get('name', 'Отель уточняется')}{stars_label}**")
    st.caption(hotel_details(hotel))
    st.markdown("**✈️ Туда**")
    st.write(flight_text(package.get("outbound"), places))
    st.markdown("**✈️ Обратно**")
    st.write(flight_text(package.get("inbound"), places))
    st.markdown("**🚐 Трансфер**")
    st.write(transfer_text(package.get("transfer")))
    render_points("Почему подходит", package.get("why") or [])
    if sources := sources_text(package):
        st.text(sources)
    render_points("Чем жертвуем", package.get("tradeoffs") or [])
    render_points(
        "Риски",
        list(dict.fromkeys(package.get("risks") or [])),
        warning=True,
    )
    selected = selected_id == package_id
    st.button(
        "✓ Выбрано" if selected else "Выбрать",
        key=f"select_{package_id}",
        type="primary" if selected else "secondary",
        use_container_width=True,
        disabled=selected or not package_id or bool(st.session_state.get("agent_run")),
        on_click=select_package,
        args=(sid, package_id),
    )


def open_checkout(sid: str, package_id: str) -> None:
    """Ключ создаётся только для новой пары сессия–пакет и сохраняется при повторах."""
    if st.session_state.get("agent_run"):
        return
    st.session_state.checkout_attempt = prepare_attempt(
        st.session_state.get("checkout_attempt"), sid, package_id
    )
    st.session_state.checkout_dialog_open = True


def render_order(order: dict, *, demo: bool) -> None:
    """Показывает подтверждение из ответа API, не выдумывая номер заказа."""
    order_id = str(order.get("id", "—"))
    status = order.get("status")
    if status == "paid":
        st.success(f"✅ Заказ {order_id} оформлен!")
        st.write(f"Итоговая стоимость: **{money(order.get('total'))}**")
        if demo:
            st.info("Это демонстрационное оформление. Деньги не списывались, заказ не настоящий.")
        else:
            st.caption("Статус заказа: оплачен (имитация)")
    elif status == "cancelled":
        st.info(f"Заказ {order_id} отменён.")
    else:
        st.info(f"Заказ {order_id} создан. Статус: {status or 'уточняется'}.")
        st.caption("Новая попытка оплаты не отправляется до уточнения статуса заказа.")


def render_cart_contents(
    package: dict, request: dict, places: dict[str, str], *, compact: bool = False
) -> None:
    """В широкой корзине разделяем состав и стоимость; в диалоге собираем вертикально."""
    details = cart_details_html(
        package,
        request,
        flight_text(package.get("outbound"), places),
        flight_text(package.get("inbound"), places),
        compact=compact,
    )
    prices = cart_prices_html(package)
    if compact:
        st.markdown(details, unsafe_allow_html=True)
        st.markdown(prices, unsafe_allow_html=True)
    else:
        detail_col, price_col = st.columns([1.5, 1], gap="large", vertical_alignment="top")
        with detail_col:
            st.markdown(details, unsafe_allow_html=True)
        with price_col:
            st.markdown(prices, unsafe_allow_html=True)

    if breakdown_matches_total(package) is False:
        st.warning("Сумма компонентов отличается от цены пакета. Уточните стоимость до оплаты.")


@st.dialog("Оформление поездки")
def checkout_dialog(
    sid: str, package: dict, request: dict, places: dict[str, str]
) -> None:
    """Открывается по кнопке из корзины; повторяет запрос только с прежним UUID."""
    attempt = st.session_state.get("checkout_attempt")
    if not attempt or attempt.get("package_id") != package.get("id"):
        st.error("Пакет изменился. Вернитесь в корзину и оформите заказ заново.")
        return

    st.markdown("**Проверьте состав перед оформлением**")
    render_cart_contents(package, request, places, compact=True)
    if DEMO_PLAN_ENABLED:
        st.caption("🧪 Демонстрация: запрос в API заказов не отправляется.")
    else:
        st.caption("Оплата имитируется — вводить данные банковской карты не нужно.")

    if attempt.get("order"):
        render_order(attempt["order"], demo=DEMO_PLAN_ENABLED)
        return
    if attempt.get("status") == "retry":
        st.warning(
            "Подтверждение от сервера не получено. Повтор использует тот же ключ запроса, "
            "чтобы не создавать второй заказ."
        )
    if attempt.get("status") == "submitting":
        st.info("Запрос уже обрабатывается. Повторная отправка заблокирована.")
        return

    if st.button(
        "Оплатить (имитация)",
        key="checkout_pay",
        type="primary",
        use_container_width=False,
    ):
        with st.spinner("Оформляем заказ…"):
            try:
                order = pay_once(
                    attempt,
                    package,
                    demo=DEMO_PLAN_ENABLED,
                    client=None if DEMO_PLAN_ENABLED else api_client(),
                )
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                LOGGER.exception("Не удалось завершить оформление заказа")
                st.error("Не удалось подтвердить заказ. Можно повторить с тем же ключом.")
                return
        if order:
            st.session_state.plan["order"] = order
            st.session_state.checkout_dialog_open = False
            st.rerun()


def render_basket(package: dict, plan: dict, sid: str) -> None:
    """Одна выделенная панель для состава поездки, цены и действий."""
    tier = TIER_LABELS.get(package.get("tier"), "Выбранный пакет")
    with st.container(border=True, key="trip_basket"):
        st.markdown(cart_header_html(tier), unsafe_allow_html=True)
        render_cart_contents(package, plan.get("request") or {}, plan.get("places") or {})

        attempt = st.session_state.get("checkout_attempt") or {}
        order = plan.get("order") or attempt.get("order")
        if order and not plan.get("order"):
            render_order(order, demo=DEMO_PLAN_ENABLED)
        if not order and breakdown_matches_total(package) is False:
            st.error("Оформление недоступно, пока не согласована итоговая стоимость.")

        # Действия ограничены долями строки; на узких экранах Streamlit складывает колонки.
        pay_col, change_col, _ = st.columns([1.2, 1.5, 2.3], gap="small")
        if not order and breakdown_matches_total(package) is not False:
            with pay_col:
                st.button(
                    "Перейти к оплате",
                    key="checkout_open",
                    type="primary",
                    use_container_width=True,
                    on_click=open_checkout,
                    args=(sid, package["id"]),
                    disabled=bool(st.session_state.get("agent_run")),
                )
        if not order:
            comparing = st.session_state.get("compare_packages", False)
            with change_col:
                if st.button(
                    "Скрыть варианты" if comparing else "Изменить пакет",
                    key="compare_again",
                    type="secondary",
                    use_container_width=True,
                    disabled=bool(st.session_state.get("agent_run")),
                ):
                    st.session_state.compare_packages = not comparing
                    st.rerun()


def render_packages(
    packages: list[dict], sid: str, selected_id: str | None, places: dict[str, str]
) -> None:
    """Нативные колонки Streamlit сохраняют равную высоту карточек."""
    for start in range(0, len(packages), 3):
        batch = packages[start : start + 3]
        columns = st.columns(len(batch), gap="medium", border=True)
        for column, package in zip(columns, batch, strict=True):
            with column:
                render_package(package, sid, selected_id, places)


def render_plan(plan: dict, sid: str) -> None:
    st.divider()
    st.header("Ваша поездка")
    if DEMO_PLAN_ENABLED or has_synthetic_offers(plan):
        st.caption("🧪 Демо-данные: цены, расписания и наличие синтетические")
    if not plan:
        st.info("Когда агент подберёт варианты, они появятся здесь.")
        return
    render_assumptions(plan)
    if plan.get("order"):
        render_order(plan["order"], demo=DEMO_PLAN_ENABLED)
    packages = plan.get("packages") or []
    if not packages:
        st.info("Пакеты пока не сформированы.")
        return
    selected_id = (
        st.session_state.get("demo_selected_package_id")
        if DEMO_PLAN_ENABLED
        else plan.get("selected_package_id")
    )
    chosen = next((item for item in packages if item.get("id") == selected_id), None)
    if chosen:
        render_basket(chosen, plan, sid)
        if st.session_state.get("compare_packages", False) and not plan.get("order"):
            st.divider()
            st.subheader("Другие варианты поездки")
            render_packages(packages, sid, selected_id, plan.get("places") or {})
        if st.session_state.get("checkout_dialog_open", False):
            checkout_dialog(sid, chosen, plan.get("request") or {}, plan.get("places") or {})
            # Закрытие через X/ESC не вызывает rerun: избегаем повторного открытия.
            st.session_state.checkout_dialog_open = False
    else:
        render_packages(packages, sid, selected_id, plan.get("places") or {})


def queue_answer() -> None:
    """Передаёт ровно текст выбранной кнопки; свободный ввод остаётся доступен."""
    if st.session_state.get("agent_run"):
        return
    choice = st.session_state.get("question_choice")
    if choice:
        st.session_state.queued_answer = choice
        st.session_state.question_choice = None


def render_question() -> None:
    """При загрузке вопрос берётся из TripState, во время потока — из question."""
    question = st.session_state.get("pending_question")
    if not question:
        return
    text = question.get("text", "")
    messages = st.session_state.get("messages") or []
    if (
        not messages
        or messages[-1].get("role") != "assistant"
        or messages[-1].get("content") != text
    ):
        st.markdown(text)
    options = question.get("options") or []
    if options:
        st.pills(
            "Выберите ответ или напишите свой",
            options,
            key="question_choice",
            selection_mode="single",
            on_change=queue_answer,
            disabled=bool(st.session_state.get("agent_run")),
        )


sid = session_id()
if st.session_state.get("active_sid") != sid:
    st.session_state.active_sid = sid
    st.session_state.messages = load_history(sid)
    st.session_state.plan = load_plan(sid)
    st.session_state.pending_question = st.session_state.plan.get("pending_question")
    st.session_state.queued_answer = None
    st.session_state.demo_selected_package_id = None
    st.session_state.checkout_attempt = None
    st.session_state.checkout_dialog_open = False
    st.session_state.compare_packages = False
    st.session_state.agent_run = None
    st.session_state.agent_error = None

header_title, header_theme = st.columns([5, 1], vertical_alignment="center")
with header_title:
    st.title("TripPilot")
with header_theme:
    render_theme_toggle()
st.caption("Опишите поездку своими словами: куда, когда, с кем и на какой бюджет.")

# Чат использует всю доступную ширину, а три карточки — полноценную сетку ниже.
with st.container():
    st.subheader("Диалог")
    history_box = st.container(height=380, border=True, key="chat_history")
    with history_box:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        if st.session_state.get("agent_run"):
            with st.chat_message("assistant"), st.container(key="agent_progress"):
                run = st.session_state.agent_run
                status = st.status(run["stage"], state="running")
                details = status.empty()
                answer = st.empty()
                if run["reply"]:
                    answer.markdown(run["reply"])
                render_agent_progress(status, details, answer)
    if st.session_state.get("agent_error"):
        st.error(st.session_state.agent_error)

    render_question()
    prompt = st.chat_input(
        "Например: к тёплому морю в ноябре, недорого, с ребёнком",
        disabled=bool(st.session_state.get("agent_run")),
    )
    prompt = st.session_state.pop("queued_answer", None) or prompt
    if prompt and not st.session_state.get("agent_run"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        run_agent(sid, text=prompt)
        st.rerun()

render_plan(st.session_state.plan, sid)
