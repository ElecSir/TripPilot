"""Репозитории плана и заказов на настоящем Postgres.

Запуск: docker compose --profile tests run --rm tests
Без переменной INTEGRATION тесты пропускаются, поэтому обычный pytest их не трогает.
"""

import asyncio
import os
import re
import uuid

import pytest
from returns.result import Success

from tests.fakes import sample_package
from trip_pilot.adapters.db.engine import create_engine, create_session_factory
from trip_pilot.adapters.db.repositories import SqlOrderRepository, SqlTripStateRepository
from trip_pilot.config import get_settings
from trip_pilot.domain.trip_state import TripState
from trip_pilot.services.booking import place_order

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION"),
    reason="нужна БД: docker compose --profile tests run --rm tests",
)


def on_db(scenario):
    """Каждый тест — в своём event loop со своим пулом соединений."""

    async def wrapper():
        engine = create_engine(get_settings().database_url)
        try:
            sessions = create_session_factory(engine)
            return await scenario(SqlTripStateRepository(sessions), SqlOrderRepository(sessions))
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


def test_trip_state_roundtrip_and_upsert():
    async def scenario(trips, _):
        state = TripState(session_id=uuid.uuid4(), packages=[sample_package()])
        assert await trips.load(state.session_id) is None

        await trips.save(state)
        assert await trips.load(state.session_id) == state

        await trips.save(state.model_copy(update={"version": 1, "stage": "compare"}))
        loaded = await trips.load(state.session_id)
        assert (loaded.version, loaded.stage) == (1, "compare")

    on_db(scenario)


def test_orders_are_numbered_and_idempotent_per_session():
    async def scenario(_, orders):
        session, other_session = uuid.uuid4(), uuid.uuid4()
        package = sample_package()
        first = await orders.create(session, package, "attempt-0001")
        again = await orders.create(session, package, "attempt-0001")
        second = await orders.create(session, package, "attempt-0002")
        foreign = await orders.create(other_session, package, "attempt-0001")

        assert re.fullmatch(r"TP-\d{4}-\d{6}", first.id)
        assert again == first
        assert second.id != first.id
        assert foreign.id != first.id  # ключ уникален только в пределах сессии
        assert first.total == package.total
        assert first.created_at.tzinfo is not None

    on_db(scenario)


def test_place_order_on_db():
    async def scenario(trips, orders):
        state = TripState(session_id=uuid.uuid4(), packages=[sample_package("p1")])
        await trips.save(state)

        result = await place_order(trips, orders, state.session_id, "p1", "attempt-0001")

        assert isinstance(result, Success)
        saved = await trips.load(state.session_id)
        assert saved.order == result.unwrap()

    on_db(scenario)
