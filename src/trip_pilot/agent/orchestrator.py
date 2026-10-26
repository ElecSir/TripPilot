"""Оркестратор агента.

StubOrchestrator — заглушка, работает в приложении, пока зоны ui и data не влили свои функции.
MvpOrchestrator — линейный сценарий MVP без LLM: каждое сообщение обновляет запрос
и досчитывает то, чего не хватает. Ход: загрузить план → обработать → сохранить → done.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from returns.result import Failure, Result, Success

from trip_pilot.agent import texts
from trip_pilot.agent.actions import AgentAction, SelectPackage
from trip_pilot.agent.dates import resolve_window
from trip_pilot.agent.events import (
    AgentEvent,
    DeltaEvent,
    DoneEvent,
    PlanEvent,
    QuestionEvent,
    StageEvent,
    StepEvent,
)
from trip_pilot.agent.toolkit import Toolkit
from trip_pilot.domain.errors import DomainError, NoResults
from trip_pilot.domain.offers import Destination
from trip_pilot.domain.request import TripRequest
from trip_pilot.domain.trip_state import PendingQuestion, TripState
from trip_pilot.ports import (
    DestinationCatalog,
    HotelSource,
    TransferSource,
    TransportSource,
    TripStateRepository,
)

log = logging.getLogger(__name__)


class StubOrchestrator:
    """Заглушка: проверяет путь UI → API → ядро → UI. Интерфейс тот же, что у MvpOrchestrator."""

    async def handle(self, session_id: uuid.UUID, text: str) -> AsyncIterator[AgentEvent]:
        yield StageEvent(stage="intake")
        yield StepEvent(text="Разбираю запрос")
        await asyncio.sleep(0.3)
        yield StepEvent(text="Агент ещё не подключён: это заглушка")

        reply = f"Принял запрос: «{text}». Скоро здесь появится план поездки."
        for word in reply.split(" "):
            yield DeltaEvent(text=word + " ")
            await asyncio.sleep(0.02)
        yield DoneEvent()

    async def handle_action(
        self, session_id: uuid.UUID, action: AgentAction
    ) -> AsyncIterator[AgentEvent]:
        yield StepEvent(text=f"Получен выбор пакета {action.package_id}: обработка появится позже")
        yield DoneEvent()


def places_of(state: TripState, names: dict[str, str]) -> dict[str, str]:
    """Названия всех мест плана: откуда, куда и пункты рейсов. Неизвестный slug — как есть."""
    slugs: set[str] = set()
    if state.request is not None:
        slugs.update(s for s in (state.request.origin, state.request.destination) if s)
    for package in state.packages:
        slugs.add(package.destination)
        for leg in (package.outbound, package.inbound):
            slugs.update((leg.origin, leg.destination))
    return {slug: names.get(slug, slug) for slug in sorted(slugs)}


@dataclass(frozen=True)
class AgentDeps:
    """Всё, что нужно оркестратору: порты (данные, хранилище плана) и функции зон ui и data."""

    catalog: DestinationCatalog
    hotels: HotelSource
    transport: TransportSource
    transfers: TransferSource
    trips: TripStateRepository
    toolkit: Toolkit


class MvpOrchestrator:
    def __init__(self, deps: AgentDeps, today: Callable[[], date] = date.today) -> None:
        self._deps = deps
        self._tk = deps.toolkit
        self._today = today

    async def handle(self, session_id: uuid.UUID, text: str) -> AsyncIterator[AgentEvent]:
        state = await self._load(session_id)
        catalog = await self._deps.catalog.all()
        names = {d.slug: d.name for d in catalog}
        today = self._today()
        yield StageEvent(stage="intake")

        if state.order is not None:
            for event in await self._close(state, texts.already_ordered(state.order)):
                yield event
            return

        # 1. Обновить запрос: ответ на вопрос → изменение плана → новое сообщение.
        match self._update_request(state, text, catalog, today):
            case Failure(error):
                reply = texts.error_text(error, names)
                for event in await self._close(state, reply, question=state.pending_question):
                    yield event
                return
            case Success(request):
                pass

        if request == state.request and state.packages:
            for event in await self._close(state, texts.nothing_changed()):
                yield event
            return
        state = state.model_copy(update={"request": request})

        # 2. Не хватает обязательного — спрашиваем одно, самое важное.
        question = self._next_question(request, catalog, today)
        if question is not None:
            stage = "inspire" if question.slot == "destination" else "clarify"
            yield StageEvent(stage=stage)
            for event in await self._close(state, "", stage=stage, question=question):
                yield event
            return
        window = resolve_window(request, today)
        if request.destination is None or request.origin is None or window is None:
            error = NoResults("не нашлось направлений под эти условия")
            for event in await self._close(state, texts.error_text(error, names)):
                yield event
            return

        # 3. Поиск: всё, что не зависит друг от друга, — параллельно.
        yield StageEvent(stage="search")
        origin, dest, party = request.origin, request.destination, request.party
        for step in texts.search_steps(names.get(origin, origin), names.get(dest, dest), window):
            yield StepEvent(text=step)
        (outbound, inbound, hotels), failed = await self._gather({
            "перелёты туда": self._deps.transport.search(origin, dest, window.check_in, party),
            "перелёты обратно": self._deps.transport.search(dest, origin, window.check_out, party),
            "отели": self._deps.hotels.search(dest, window.check_in, window.check_out, party),
        })
        for name in failed:
            yield StepEvent(text=texts.source_failed(name))

        transfers_by_hotel = {}
        if outbound and hotels:
            arrive_at = min(leg.arrive_at for leg in outbound)
            yield StepEvent(text=f"Ищу трансферы до {len(hotels)} отелей")
            found, failed = await self._gather({
                str(h.id): self._deps.transfers.search(h.id, arrive_at, party) for h in hotels
            })
            transfers_by_hotel = {h.id: t for h, t in zip(hotels, found, strict=True)}
            if failed:
                yield StepEvent(text=texts.source_failed("трансферы"))

        # 4. Пакеты: сборка и проверки — у data, объяснения — у ui.
        yield StepEvent(text="Собираю пакеты и проверяю стыковки")
        search_request = request.model_copy(
            update={"date_from": window.check_in, "nights": window.nights}
        )
        built = self._tk.simple_packages(
            search_request, outbound, inbound, hotels, transfers_by_hotel
        )
        state = state.model_copy(
            update={"search": window, "packages": [], "selected_package_id": None}
        )
        match built:
            case Failure(error):
                for event in await self._close(state, texts.error_text(error, names)):
                    yield event
                return
            case Success(packages):
                pass

        packages = [
            self._tk.explain(
                p.model_copy(update={"issues": self._tk.check_package(p)}), search_request
            )
            for p in packages
        ]
        state = state.model_copy(update={"packages": packages})
        yield StageEvent(stage="compare")
        summary = texts.plan_summary(
            names.get(origin, origin), names.get(dest, dest), window, packages
        )
        for event in await self._close(state, summary, stage="compare"):
            yield event

    async def handle_action(
        self, session_id: uuid.UUID, action: AgentAction
    ) -> AsyncIterator[AgentEvent]:
        state = await self._load(session_id)
        match action:
            case SelectPackage(package_id=package_id):
                package = state.package(package_id)
                if state.order is not None:
                    events = await self._close(state, texts.already_ordered(state.order))
                elif package is None:
                    events = await self._close(state, texts.unknown_package())
                else:
                    yield StageEvent(stage="checkout")
                    state = state.model_copy(update={"selected_package_id": package_id})
                    events = await self._close(
                        state, texts.package_selected(package), stage="checkout"
                    )
            case _:
                events = await self._close(state, texts.unknown_package())
        for event in events:
            yield event

    async def _load(self, session_id: uuid.UUID) -> TripState:
        return await self._deps.trips.load(session_id) or TripState(session_id=session_id)

    def _update_request(
        self, state: TripState, text: str, catalog: list[Destination], today: date
    ) -> Result[TripRequest, DomainError]:
        base = state.request or TripRequest()
        if state.pending_question is not None:
            answered = self._tk.apply_answer(
                state.pending_question, text, base, catalog=catalog, today=today
            )
            if answered is not None:
                return answered
        if state.request is not None and state.search is not None:
            # Изменение считается от дат последнего поиска, а записывается в запрос пользователя.
            current = state.request.model_copy(
                update={"date_from": state.search.check_in, "nights": state.search.nights}
            )
            patch = self._tk.parse_change(text, current, today=today)
            if patch:
                return Success(TripRequest.model_validate(state.request.model_dump() | patch))
        return self._tk.parse_request(text, catalog=catalog, today=today, base=state.request)

    def _next_question(
        self, request: TripRequest, catalog: list[Destination], today: date
    ) -> PendingQuestion | None:
        question = self._tk.next_question(request, catalog)
        if question is not None:
            return question
        # Запасные вопросы на случай, если уточнитель ui что-то пропустил.
        if request.origin is None:
            return texts.origin_question(catalog)
        if request.destination is None:
            options = self._tk.pick_destinations(request, catalog)
            return texts.destination_question(options) if options else None
        if resolve_window(request, today) is None:
            return texts.when_question(today)
        return None

    async def _gather(
        self, calls: dict[str, Awaitable[list[Any]]]
    ) -> tuple[list[list[Any]], list[str]]:
        """Параллельные вызовы источников. Упавший источник даёт пустой список, а не крах хода."""
        results = await asyncio.gather(*calls.values(), return_exceptions=True)
        values, failed = [], []
        for name, result in zip(calls, results, strict=True):
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                log.warning("Источник «%s» не ответил: %r", name, result)
                failed.append(name)
                values.append([])
            else:
                values.append(result)
        return values, failed

    async def _close(
        self,
        state: TripState,
        reply: str,
        *,
        stage: str | None = None,
        question: PendingQuestion | None = None,
    ) -> list[AgentEvent]:
        """Завершение хода: версия + 1, план сохраняется ДО done — клиент может сразу уйти."""
        catalog = await self._deps.catalog.all()
        update: dict[str, Any] = {
            "version": state.version + 1,
            "pending_question": question,
            "places": places_of(state, {d.slug: d.name for d in catalog}),
        }
        if stage is not None:
            update["stage"] = stage
        state = state.model_copy(update=update)
        await self._deps.trips.save(state)

        events: list[AgentEvent] = [PlanEvent(data=state.model_dump(mode="json"))]
        if reply:
            events.append(DeltaEvent(text=reply))
        if question is not None:
            events.append(QuestionEvent(text=question.text, options=question.options))
        events.append(DoneEvent())
        return events
