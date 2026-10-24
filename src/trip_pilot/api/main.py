from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from trip_pilot.adapters.db.engine import create_engine, create_session_factory
from trip_pilot.adapters.db.repositories import SqlOrderRepository, SqlTripStateRepository
from trip_pilot.agent.orchestrator import StubOrchestrator
from trip_pilot.api import chat, health, trips
from trip_pilot.config import get_settings
from trip_pilot.logs import setup_logging


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
    app.state.orchestrator = StubOrchestrator()
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
