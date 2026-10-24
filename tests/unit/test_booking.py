"""Оформление заказа: все ветки place_order на фейках."""

import asyncio
import uuid

from returns.result import Failure, Success

from tests.fakes import fake_sources, sample_package
from trip_pilot.domain.errors import (
    AlreadyOrdered,
    IdempotencyConflict,
    PackageNotInPlan,
    PlanNotFound,
)
from trip_pilot.domain.trip_state import TripState
from trip_pilot.services.booking import place_order


def setup_plan():
    src = fake_sources()
    state = TripState(
        session_id=uuid.uuid4(),
        packages=[sample_package("p1"), sample_package("p2", destination="sochi")],
    )
    asyncio.run(src.trips.save(state))
    return src, state.session_id


def order(src, session_id, package_id="p1", key="attempt-0001"):
    return asyncio.run(place_order(src.trips, src.orders, session_id, package_id, key))


def test_order_is_saved_into_plan():
    src, session_id = setup_plan()

    result = order(src, session_id)

    assert isinstance(result, Success)
    placed = result.unwrap()
    assert placed.status == "paid"
    assert placed.total == sample_package("p1").total
    state = asyncio.run(src.trips.load(session_id))
    assert state.order == placed
    assert state.selected_package_id == "p1"
    assert state.version == 1


def test_repeat_returns_same_order_even_with_new_key():
    src, session_id = setup_plan()
    first = order(src, session_id, key="attempt-0001").unwrap()
    again = order(src, session_id, key="attempt-0002").unwrap()
    assert again == first
    assert len(src.orders.orders) == 1


def test_no_plan():
    src = fake_sources()
    session_id = uuid.uuid4()
    assert order(src, session_id) == Failure(PlanNotFound(session_id))


def test_unknown_package():
    src, session_id = setup_plan()
    assert order(src, session_id, package_id="p9") == Failure(PackageNotInPlan("p9"))


def test_second_package_after_order_is_rejected():
    src, session_id = setup_plan()
    first = order(src, session_id, package_id="p1").unwrap()
    assert order(src, session_id, package_id="p2", key="attempt-0002") == Failure(
        AlreadyOrdered(first.id)
    )


def test_key_reused_for_other_package_is_conflict():
    src, session_id = setup_plan()
    # Заказ по ключу уже есть в хранилище, но план о нём не знает (например, сбой между шагами).
    asyncio.run(src.orders.create(session_id, sample_package("p1"), "attempt-0001"))
    assert order(src, session_id, package_id="p2") == Failure(IdempotencyConflict("attempt-0001"))
