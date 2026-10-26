from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trip_pilot.adapters.db.engine import create_engine, create_session_factory
from trip_pilot.adapters.db.repositories import SqlOrderRepository, SqlTripStateRepository
from trip_pilot.adapters.llm.openai_compat import make_llm
from trip_pilot.adapters.sources.synthetic import (
    SyntheticDestinationCatalog,
    SyntheticHotelSource,
    SyntheticTransferSource,
    SyntheticTransportSource,
)
from trip_pilot.agent import clarifier, intent, understand
from trip_pilot.agent.orchestrator import AgentDeps, MvpOrchestrator
from trip_pilot.agent.toolkit import Toolkit
from trip_pilot.api import chat, health, trips
from trip_pilot.config import get_settings
from trip_pilot.logs import setup_logging
from trip_pilot.planning import inspiration, itinerary, packages
from trip_pilot.ports import LLM, TripStateRepository
from trip_pilot.rag.retriever import PostgresKnowledgeBase
from trip_pilot.services import explanation

# Функции зоны data, которые вызывает оркестратор. Сигнатуры — в agent/toolkit.py.
TOOLKIT = Toolkit(
    parse_request=intent.parse_request,
    parse_change=intent.parse_change,
    next_question=clarifier.next_question,
    apply_answer=clarifier.apply_answer,
    pick_destinations=inspiration.pick_destinations,
    simple_packages=packages.simple_packages,
    check_package=itinerary.check_package,
    explain=explanation.explain,
    understand=understand.understand,
    narrate=explanation.narrate,
)


def build_orchestrator(
    sessions: async_sessionmaker[AsyncSession],
    trips: TripStateRepository,
    *,
    llm: LLM,
    today: Callable[[], date] = date.today,
) -> MvpOrchestrator:
    """Агент: синтетика из БД (её создаёт bootstrap), база знаний и LLM.

    Без ключа `make_llm` отдаёт заглушку, и агент работает на правилах и шаблонах, как в MVP.
    """
    deps = AgentDeps(
        catalog=SyntheticDestinationCatalog(sessions),
        hotels=SyntheticHotelSource(sessions),
        transport=SyntheticTransportSource(sessions),
        transfers=SyntheticTransferSource(sessions),
        trips=trips,
        toolkit=TOOLKIT,
        llm=llm,
        knowledge=PostgresKnowledgeBase(sessions),
    )
    return MvpOrchestrator(deps, today=today)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Composition root: здесь ядро соединяется с адаптерами.
    settings = get_settings()
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.trips = SqlTripStateRepository(sessions)
    app.state.orders = SqlOrderRepository(sessions)
    app.state.orchestrator = build_orchestrator(sessions, app.state.trips, llm=make_llm(settings))
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    setup_logging(get_settings().log_level)
    app = FastAPI(
        title="TripPilot API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.include_router(health.router)
    app.include_router(chat.router, prefix="/api")
    app.include_router(trips.router, prefix="/api")
    return app


app = create_app()
