"""Оркестратор агента.

MvpOrchestrator — линейный сценарий: каждое сообщение обновляет запрос и досчитывает то,
чего не хватает. Ход: загрузить план → обработать → сохранить → done. Собирается
с настоящими адаптерами и функциями зон в api/main.py.

Изменение условий не начинает поиск с нуля: заново ищется только то, что от изменения зависит
(agent/replanner.py), остальное берётся из кеша прошлого поиска, а человеку показывается,
что поменялось.

Этап 1: если LLM доступна, сообщение сначала понимает `understand`, а объяснения дописывает
`narrate`. Любой сбой LLM (`LLMUnavailable`) — тот же ход на правилах и шаблонах, как в MVP.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel
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
from trip_pilot.agent.replanner import describe_changes, reused_step, search_needs
from trip_pilot.agent.toolkit import Toolkit
from trip_pilot.domain.errors import DomainError, NoResults
from trip_pilot.domain.knowledge import KnowledgeHit
from trip_pilot.domain.offers import Destination, Package
from trip_pilot.domain.request import TripRequest
from trip_pilot.domain.trip_state import PendingQuestion, SearchCache, TripState
from trip_pilot.ports import (
    LLM,
    ChatMessages,
    DestinationCatalog,
    HotelSource,
    KnowledgeBase,
    LLMUnavailable,
    TransferSource,
    TransportSource,
    TripStateRepository,
)

log = logging.getLogger(__name__)


class NoLLM:
    """LLM не подключена: ведёт себя как адаптер без ключа — каждый вызов бросает LLMUnavailable."""

    enabled = False

    async def complete(self, messages: ChatMessages) -> str:
        raise LLMUnavailable("LLM не подключена")

    async def structured[T: BaseModel](self, messages: ChatMessages, schema: type[T]) -> T:
        raise LLMUnavailable("LLM не подключена")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise LLMUnavailable("LLM не подключена")


class AnsweredLLM:
    """Обёртка LLM, которая помнит, ответила ли модель хоть раз.

    По ней оркестратор пишет шаг «с помощью ИИ» только по факту, а не потому, что ключ задан:
    функция data может вернуть результат правил, не позвав модель.
    """

    def __init__(self, llm: LLM) -> None:
        self._llm = llm
        self.enabled = llm.enabled
        self.answered = False

    async def complete(self, messages: ChatMessages) -> str:
        reply = await self._llm.complete(messages)
        self.answered = True
        return reply

    async def structured[T: BaseModel](self, messages: ChatMessages, schema: type[T]) -> T:
        reply = await self._llm.structured(messages, schema)
        self.answered = True
        return reply

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = await self._llm.embed(texts)
        self.answered = True
        return vectors


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
    """Всё, что нужно оркестратору: порты (данные, хранилище плана) и функции зоны data."""

    catalog: DestinationCatalog
    hotels: HotelSource
    transport: TransportSource
    transfers: TransferSource
    trips: TripStateRepository
    toolkit: Toolkit
    # Этап 1. Без них — режим MVP: правила, шаблоны, объяснения без базы знаний.
    llm: LLM = field(default_factory=NoLLM)
    knowledge: KnowledgeBase | None = None


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

        # 1. Обновить запрос. С LLM — понимание моделью; без неё или при сбое — правила:
        #    ответ на вопрос → изменение плана → новое сообщение.
        #    Шаг «с помощью ИИ» — только если модель действительно ответила.
        if self._uses_llm(self._tk.understand):
            yield StepEvent(text="Разбираю запрос")
        updated, by_ai = await self._understand(state, text, catalog, today)
        if by_ai:
            yield StepEvent(text="Запрос разобран с помощью ИИ")
        if updated is None:
            updated = self._update_request(state, text, catalog, today)
        match updated:
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

        # 3. Поиск. При изменении условий заново ищется только то, что от них зависит
        #    (agent/replanner.py), остальное берётся из кеша прошлого поиска. Независимое —
        #    параллельно.
        yield StageEvent(stage="search")
        origin, dest, party = request.origin, request.destination, request.party
        cache = state.cache
        needs = search_needs(cache, request, window)
        if (reused := reused_step(needs)) is not None:
            yield StepEvent(text=reused)
        steps = texts.search_steps(names.get(origin, origin), names.get(dest, dest), window)
        searches: dict[str, Awaitable[list[Any]]] = {}
        if needs.outbound:
            searches["перелёты туда"] = self._deps.transport.search(
                origin, dest, window.check_in, party
            )
        if needs.inbound:
            searches["перелёты обратно"] = self._deps.transport.search(
                dest, origin, window.check_out, party
            )
        if needs.hotels:
            searches["отели"] = self._deps.hotels.search(
                dest, window.check_in, window.check_out, party
            )
        for needed, step in zip((needs.outbound, needs.inbound, needs.hotels), steps, strict=True):
            if needed:
                yield StepEvent(text=step)
        found, failed = await self._gather(searches)
        for name in failed:
            yield StepEvent(text=texts.source_failed(name))
        fresh = dict(zip(searches, found, strict=True))
        # Что не искали заново, есть в кеше: без кеша search_needs требует искать всё.
        outbound = fresh["перелёты туда"] if needs.outbound else cache.outbound
        inbound = fresh["перелёты обратно"] if needs.inbound else cache.inbound
        hotels = fresh["отели"] if needs.hotels else cache.hotels

        if needs.transfers:
            transfers_by_hotel = {}
            if outbound and hotels:
                arrive_at = min(leg.arrive_at for leg in outbound)
                yield StepEvent(text=f"Ищу трансферы до {len(hotels)} отелей")
                found, transfers_failed = await self._gather({
                    str(h.id): self._deps.transfers.search(h.id, arrive_at, party) for h in hotels
                })
                transfers_by_hotel = {h.id: t for h, t in zip(hotels, found, strict=True)}
                if transfers_failed:
                    failed.append("трансферы")
                    yield StepEvent(text=texts.source_failed("трансферы"))
        else:
            transfers_by_hotel = cache.transfers_by_hotel
        # Упавший источник дал пустой список: такой поиск не кешируем, в следующий раз — заново.
        new_cache = None if failed else SearchCache(
            origin=origin, destination=dest, check_in=window.check_in,
            check_out=window.check_out, travellers=party.travellers, outbound=outbound,
            inbound=inbound, hotels=hotels, transfers_by_hotel=transfers_by_hotel,
        )

        # 4. Пакеты: сборка, проверки и объяснения — функции data.
        yield StepEvent(text="Собираю пакеты и проверяю стыковки")
        search_request = request.model_copy(
            update={"date_from": window.check_in, "nights": window.nights}
        )
        built = self._tk.simple_packages(
            search_request, outbound, inbound, hotels, transfers_by_hotel
        )
        previous, previous_window = state.packages, state.search
        state = state.model_copy(
            update={
                "search": window, "packages": [], "selected_package_id": None, "cache": new_cache,
            }
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
        packages, by_ai = await self._narrate(packages, search_request)
        if by_ai:
            yield StepEvent(text="Объяснения написаны с помощью ИИ")
        state = state.model_copy(update={"packages": packages})
        yield StageEvent(stage="compare")
        changed = describe_changes(previous, packages, previous_window, window) if previous else []
        summary = texts.plan_summary(
            names.get(origin, origin), names.get(dest, dest), window, packages
        ) + texts.changes(changed)
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

    def _uses_llm(self, function: object | None) -> bool:
        return function is not None and self._deps.llm.enabled

    async def _understand(
        self, state: TripState, text: str, catalog: list[Destination], today: date
    ) -> tuple[Result[TripRequest, DomainError] | None, bool]:
        """Понимание моделью и «ответила ли модель». None — разбирать правилами."""
        understand = self._tk.understand
        if understand is None or not self._deps.llm.enabled:
            return None, False
        llm = AnsweredLLM(self._deps.llm)
        try:
            result = await understand(text, state, catalog=catalog, today=today, llm=llm)
        except LLMUnavailable as error:
            log.warning("LLM недоступна, разбираю запрос правилами: %s", error)
            return None, False
        return result, result is not None and llm.answered

    async def _narrate(
        self, packages: list[Package], request: TripRequest
    ) -> tuple[list[Package], bool]:
        """Объяснения всех пакетов разом и «ответила ли модель». Без LLM — тоже: сравнения."""
        narrate = self._tk.narrate
        if narrate is None:
            return packages, False
        knowledge = await self._knowledge(request)
        llm = AnsweredLLM(self._deps.llm)
        try:
            return await narrate(packages, request, knowledge=knowledge, llm=llm), llm.answered
        except LLMUnavailable as error:
            log.warning("LLM недоступна, оставляю шаблонные объяснения: %s", error)
            return packages, False

    async def _knowledge(self, request: TripRequest) -> list[KnowledgeHit]:
        """Фрагменты базы знаний. Как упавший источник: без них объяснения беднее, но ход идёт."""
        if self._deps.knowledge is None or request.destination is None:
            return []
        try:
            return await self._deps.knowledge.context(request, request.destination)
        except Exception:
            log.warning("База знаний не ответила", exc_info=True)
            return []

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
        question = self._tk.next_question(request, catalog, today=today)
        if question is not None:
            return question
        # Запасные вопросы на случай, если уточнитель что-то пропустил.
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
