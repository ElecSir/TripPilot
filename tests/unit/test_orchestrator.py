"""Сценарии MvpOrchestrator на фейках.

Функции зон ui и data здесь заменены простыми версиями на правилах: тест проверяет
логику оркестратора (какой шаг, какой вопрос, что сохраняется), а не качество разбора.
"""

import asyncio
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal

from returns.result import Failure, Success

from tests.fakes import fake_sources
from trip_pilot.agent.actions import SelectPackage
from trip_pilot.agent.dates import first_saturday, resolve_window
from trip_pilot.agent.events import (
    DeltaEvent,
    DoneEvent,
    PlanEvent,
    QuestionEvent,
    StageEvent,
    StepEvent,
)
from trip_pilot.agent.orchestrator import AgentDeps, MvpOrchestrator, places_of
from trip_pilot.agent.toolkit import Toolkit
from trip_pilot.domain.errors import BudgetTooLow, NoResults, UnknownCity
from trip_pilot.domain.offers import Package
from trip_pilot.domain.request import Party, TripRequest
from trip_pilot.domain.trip_state import Order, PendingQuestion, TripState

TODAY = date(2026, 10, 24)  # суббота; ближайшая подходящая суббота ноября — 7-е
CITIES = {"москв": "moscow", "сочи": "sochi", "анталь": "antalya"}
MONTHS = {"ноябр": 11, "декабр": 12}
AGES = {"до 2": 1, "2–6": 4, "7–12": 9, "13–17": 15}


# --- Простые версии функций ui и data -------------------------------------------------------

def city(word: str) -> str | None:
    return next((slug for stem, slug in CITIES.items() if word.startswith(stem)), None)


def parse_request(text, *, catalog, today, base=None):
    low, update = text.lower(), {}
    if m := re.search(r"из (\w+)", low):
        if (slug := city(m.group(1))) is None:
            return Failure(UnknownCity(m.group(1)))
        update["origin"] = slug
    if m := re.search(r"в (\w+)", low):
        if slug := city(m.group(1)):
            update["destination"] = slug
    for stem, month in MONTHS.items():
        if stem in low:
            update["month"] = month
    if "с ребёнком" in low:
        update["party"] = Party(children_ages=[None])
    if m := re.search(r"до ([\d ]+)", low):
        update["budget"] = Decimal(m.group(1).replace(" ", ""))
    return Success((base or TripRequest()).model_copy(update=update))


def parse_change(text, current, *, today):
    if m := re.search(r"на (\d+) дня позже", text):
        return {"date_from": current.date_from + timedelta(days=int(m.group(1)))}
    return None


def next_question(request, catalog):
    if request.origin is None:
        return PendingQuestion(slot="origin", text="Откуда полетите?", options=["Москва"])
    if None in request.party.children_ages:
        return PendingQuestion(
            slot="children_ages", text="Сколько лет ребёнку?", options=list(AGES)
        )
    return None


def apply_answer(question, text, request, *, catalog, today):
    names = {d.name: d.slug for d in catalog}
    if question.slot in ("origin", "destination") and text in names:
        return Success(request.model_copy(update={question.slot: names[text]}))
    if question.slot == "children_ages" and text in AGES:
        ages = [AGES[text] if a is None else a for a in request.party.children_ages]
        party = request.party.model_copy(update={"children_ages": ages})
        return Success(request.model_copy(update={"party": party}))
    return None


def pick_destinations(request, catalog):
    return [d for d in catalog if "sea" in d.tags]


def simple_packages(request, outbound, inbound, hotels, transfers_by_hotel):
    if not (outbound and inbound and hotels):
        return Failure(NoResults("нет рейсов или отелей"))
    out, back = min(outbound, key=lambda leg: leg.price), min(inbound, key=lambda leg: leg.price)
    packages = []
    for tier, hotel in zip(("economy", "balance", "comfort"),
                           sorted(hotels, key=lambda h: h.price_per_night), strict=False):
        transfer = (transfers_by_hotel.get(hotel.id) or [None])[0]
        breakdown = {
            "flights": (out.price + back.price) * request.party.travellers,
            "hotel": hotel.price_per_night * request.nights,
            "transfer": transfer.price * 2 if transfer else Decimal(0),
        }
        packages.append(Package(
            id=f"p{len(packages) + 1}", tier=tier, destination=request.destination,
            outbound=out, inbound=back, hotel=hotel, transfer=transfer,
            check_in=request.date_from, check_out=request.date_from + timedelta(request.nights),
            nights=request.nights, total=sum(breakdown.values()), price_breakdown=breakdown,
        ))
    cheapest = min(p.total for p in packages)
    if request.budget is not None and cheapest > request.budget:
        return Failure(BudgetTooLow(request.budget, cheapest))
    return Success(packages)


def check_package(package):
    return ["рейс с пересадкой"] if package.outbound.stops else []


def explain(package, request):
    return package.model_copy(update={"why": [f"{package.hotel.stars}★ {package.hotel.name}"]})


TOOLKIT = Toolkit(
    parse_request=parse_request, parse_change=parse_change, next_question=next_question,
    apply_answer=apply_answer, pick_destinations=pick_destinations,
    simple_packages=simple_packages, check_package=check_package, explain=explain,
)


# --- Обвязка ---------------------------------------------------------------------------------

class Dialog:
    def __init__(self, hotels=None):
        self.src = fake_sources()
        deps = AgentDeps(
            catalog=self.src.catalog, hotels=hotels or self.src.hotels,
            transport=self.src.transport, transfers=self.src.transfers,
            trips=self.src.trips, toolkit=TOOLKIT,
        )
        self.agent = MvpOrchestrator(deps, today=lambda: TODAY)
        self.session = uuid.uuid4()

    def say(self, text):
        return asyncio.run(self._collect(self.agent.handle(self.session, text)))

    def press(self, package_id):
        action = SelectPackage(package_id=package_id)
        return asyncio.run(self._collect(self.agent.handle_action(self.session, action)))

    @property
    def state(self):
        return asyncio.run(self.src.trips.load(self.session))

    @staticmethod
    async def _collect(events):
        return [e async for e in events]


def of(events, kind):
    return [e for e in events if isinstance(e, kind)]


def reply(events):
    return "".join(e.text for e in of(events, DeltaEvent))


def stages(events):
    return [e.stage for e in of(events, StageEvent)]


class BrokenHotels:
    async def search(self, *args, **kwargs):
        raise ConnectionError("отели недоступны")


# --- Сценарии --------------------------------------------------------------------------------

def test_asks_one_question_and_saves_it():
    d = Dialog()
    events = d.say("Хочу на море в ноябре")

    assert stages(events) == ["intake", "clarify"]
    [question] = of(events, QuestionEvent)
    assert question.options == ["Москва"]
    assert isinstance(events[-1], DoneEvent)
    assert d.state.pending_question.slot == "origin"
    assert d.state.version == 1


def test_button_answers_lead_to_plan():
    d = Dialog()
    d.say("Хочу на море в ноябре")

    events = d.say("Москва")  # кнопка на вопрос «откуда»
    assert stages(events)[-1] == "inspire"
    assert of(events, QuestionEvent)[0].options == ["Сочи", "Анталья"]
    assert of(events, PlanEvent)[0].data["places"] == {"moscow": "Москва"}

    events = d.say("Анталья")  # кнопка на вопрос «куда»
    assert stages(events)[-2:] == ["search", "compare"]
    assert "Ищу перелёты Москва → Анталья на 7 ноября" in [e.text for e in of(events, StepEvent)]
    assert "Нашёл 3 варианта" in reply(events)
    assert d.state.pending_question is None


def test_full_request_gives_plan_and_keeps_user_intent():
    d = Dialog()
    events = d.say("Из Москвы в Анталью в ноябре")

    [plan] = of(events, PlanEvent)
    assert [p["tier"] for p in plan.data["packages"]] == ["economy", "balance", "comfort"]
    # Названия всех мест плана: UI показывает их вместо slug из рейсов и запроса.
    assert plan.data["places"] == {"antalya": "Анталья", "moscow": "Москва"}
    state = d.state
    assert state.search.check_in == date(2026, 11, 7)
    assert state.search.check_out == date(2026, 11, 14)
    assert {a.field for a in state.search.assumptions} == {"nights", "date_from"}
    assert state.request.date_from is None  # в запросе — то, что сказал пользователь: «в ноябре»
    assert state.packages[0].why == ["3★ Лара Сан"]  # объяснение от ui
    # Самый дешёвый рейс у фейков — вечерний с пересадкой: проверка data это отметила.
    assert state.packages[0].issues == ["рейс с пересадкой"]
    assert state.stage == "compare"
    # План сохранён до done: событие plan и сохранённое состояние совпадают.
    assert plan.data["version"] == state.version == 1


def test_change_shifts_dates_from_last_search():
    d = Dialog()
    d.say("Из Москвы в Анталью в ноябре")
    events = d.say("а если на 2 дня позже?")

    assert d.state.search.check_in == date(2026, 11, 9)
    assert d.state.request.date_from == date(2026, 11, 9)  # теперь дата названа явно
    assert {a.field for a in d.state.search.assumptions} == {"nights"}
    assert "9–16 ноября" in reply(events)


def test_new_month_replaces_previous_search_dates():
    d = Dialog()
    d.say("Из Москвы в Анталью в ноябре")
    d.say("а в декабре?")
    assert d.state.search.check_in == date(2026, 12, 5)


def test_same_request_does_not_search_again():
    d = Dialog()
    d.say("Из Москвы в Анталью в ноябре")
    events = d.say("Из Москвы в Анталью в ноябре")
    assert not of(events, StepEvent)
    assert "План выше" in reply(events)


def test_unknown_city_keeps_pending_question():
    d = Dialog()
    d.say("Хочу на море в ноябре")
    events = d.say("из Урюпинска")

    assert "Не знаю город «урюпинска»" in reply(events)
    assert of(events, QuestionEvent)[0].text == "Откуда полетите?"  # кнопки снова на месте
    assert d.state.pending_question.slot == "origin"


def test_child_age_button():
    d = Dialog()
    events = d.say("Из Москвы в Сочи в ноябре с ребёнком")
    assert of(events, QuestionEvent)[0].text == "Сколько лет ребёнку?"

    d.say("2–6")
    assert d.state.request.party.children_ages == [4]
    assert len(d.state.packages) == 3


def test_budget_too_low_is_explained():
    d = Dialog()
    events = d.say("Из Москвы в Анталью в ноябре до 10 000")
    assert "не укладываемся" in reply(events)
    assert "84 800 ₽" in reply(events)
    assert d.state.packages == []


def test_failed_source_is_reported_not_crashed():
    d = Dialog(hotels=BrokenHotels())
    events = d.say("Из Москвы в Анталью в ноябре")
    steps = [e.text for e in of(events, StepEvent)]
    assert "Источник «отели» не ответил, продолжаю без него" in steps
    assert "ничего не нашлось" in reply(events)
    assert isinstance(events[-1], DoneEvent)


def test_select_package():
    d = Dialog()
    d.say("Из Москвы в Анталью в ноябре")

    events = d.press("p2")
    assert stages(events) == ["checkout"]
    assert of(events, PlanEvent)[0].data["places"]["antalya"] == "Анталья"
    assert "Выбран пакет «Баланс»" in reply(events)
    assert d.state.selected_package_id == "p2"

    assert "Такого варианта нет" in reply(d.press("p9"))


def test_after_order_agent_does_not_replan():
    d = Dialog()
    d.say("Из Москвы в Анталью в ноябре")
    state = d.state
    order = Order(
        id="TP-2026-000001", package_id="p1", total=state.packages[0].total, status="paid",
        created_at="2026-10-24T12:00:00+03:00",
    )
    asyncio.run(d.src.trips.save(state.model_copy(update={"order": order})))

    events = d.say("а в декабре?")
    assert "Заказ TP-2026-000001 уже оформлен" in reply(events)
    assert d.state.search.check_in == date(2026, 11, 7)


def test_places_keep_unknown_slug_as_is():
    state = TripState(
        session_id=uuid.uuid4(), request=TripRequest(origin="moscow", destination="atlantis")
    )
    assert places_of(state, {"moscow": "Москва"}) == {"atlantis": "atlantis", "moscow": "Москва"}


# --- Даты ------------------------------------------------------------------------------------

def test_first_saturday_rules():
    assert first_saturday(11, TODAY) == date(2026, 11, 7)
    assert first_saturday(3, TODAY) == date(2027, 3, 6)  # март уже прошёл — следующий год
    assert first_saturday(10, date(2026, 10, 29)) == date(2027, 10, 2)  # субботы октября близко
    assert first_saturday(11, date(2026, 11, 5)) == date(2026, 11, 14)  # 7-е ближе 3 дней


def test_resolve_window():
    assert resolve_window(TripRequest(), TODAY) is None
    window = resolve_window(TripRequest(date_from=date(2026, 12, 1), nights=3), TODAY)
    assert (window.check_out, window.assumptions) == (date(2026, 12, 4), [])
