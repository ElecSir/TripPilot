"""Агент приложения на синтетике из Postgres: тот же путь, что в docker compose up.

Запуск: docker compose --profile tests run --rm tests
Синтетику создаёт bootstrap на 90 дней вперёд от сегодня, поэтому даты в запросе относительные.
"""

import asyncio
import os
import uuid

import pytest
from returns.result import Success

from trip_pilot.adapters.db.engine import create_engine, create_session_factory
from trip_pilot.adapters.db.repositories import SqlOrderRepository, SqlTripStateRepository
from trip_pilot.agent.actions import SelectPackage
from trip_pilot.api.main import build_orchestrator
from trip_pilot.config import get_settings
from trip_pilot.services.booking import place_order

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION"),
    reason="нужна БД: docker compose --profile tests run --rm tests",
)


async def drain(events) -> None:
    async for _ in events:
        pass


def test_app_agent_plans_and_books_on_synthetic_inventory():
    async def scenario():
        engine = create_engine(get_settings().database_url)
        try:
            sessions = create_session_factory(engine)
            trips = SqlTripStateRepository(sessions)
            agent = build_orchestrator(sessions, trips)
            session = uuid.uuid4()

            request = "Из Москвы в Анталью через две недели на неделю вдвоём"
            await drain(agent.handle(session, request))
            planned = await trips.load(session)
            package_id = planned.packages[0].id
            await drain(agent.handle_action(session, SelectPackage(package_id=package_id)))
            order = await place_order(
                trips, SqlOrderRepository(sessions), session, package_id, "e2e-attempt-0001"
            )
            return planned, await trips.load(session), order
        finally:
            await engine.dispose()

    planned, final, order = asyncio.run(scenario())

    assert planned.search.nights == 7
    assert planned.packages
    assert all(p.hotel.is_synthetic and p.outbound.is_synthetic for p in planned.packages)
    assert all(p.why for p in planned.packages)
    assert isinstance(order, Success)
    assert final.order.id == order.unwrap().id
    assert final.selected_package_id == planned.packages[0].id
