"""Оформление заказа по пакету из текущего плана. Оплата имитируется: заказ сразу «paid»."""

import uuid

from returns.result import Failure, Result, Success

from trip_pilot.domain.errors import (
    AlreadyOrdered,
    BookingError,
    IdempotencyConflict,
    PackageNotInPlan,
    PlanNotFound,
)
from trip_pilot.domain.trip_state import Order
from trip_pilot.ports import OrderRepository, TripStateRepository


async def place_order(
    trips: TripStateRepository,
    orders: OrderRepository,
    session_id: uuid.UUID,
    package_id: str,
    idempotency_key: str,
) -> Result[Order, BookingError]:
    state = await trips.load(session_id)
    if state is None:
        return Failure(PlanNotFound(session_id))

    package = state.package(package_id)
    if package is None:
        return Failure(PackageNotInPlan(package_id))

    # Один оплаченный заказ на план: повтор по тому же пакету возвращает его же.
    if state.order is not None:
        if state.order.package_id == package_id:
            return Success(state.order)
        return Failure(AlreadyOrdered(state.order.id))

    order = await orders.create(session_id, package, idempotency_key)
    if order.package_id != package_id:
        return Failure(IdempotencyConflict(idempotency_key))

    await trips.save(
        state.model_copy(
            update={"order": order, "selected_package_id": package_id, "version": state.version + 1}
        )
    )
    return Success(order)
