"""План поездки и заказы."""

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from returns.result import Failure, Success

from trip_pilot.domain.errors import (
    AlreadyOrdered,
    IdempotencyConflict,
    PackageNotInPlan,
    PlanNotFound,
)
from trip_pilot.domain.trip_state import Order, TripState
from trip_pilot.services.booking import place_order

router = APIRouter(tags=["trips"])


class OrderRequest(BaseModel):
    session_id: uuid.UUID
    package_id: str
    # Повтор с тем же ключом возвращает тот же заказ: двойной клик не создаёт второй.
    idempotency_key: str = Field(min_length=8, max_length=64)


@router.get(
    "/trips/{session_id}",
    responses={404: {"description": "План для этой сессии ещё не создан"}},
)
async def get_trip(session_id: uuid.UUID, request: Request) -> TripState:
    """Текущий план поездки: по нему UI восстанавливает панель и кнопки вопроса после F5."""
    state = await request.app.state.trips.load(session_id)
    if state is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "План для этой сессии ещё не создан")
    return state


@router.post(
    "/orders",
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Нет плана или пакета в плане"},
        409: {"description": "По плану уже оформлен другой заказ или ключ занят"},
    },
)
async def create_order(req: OrderRequest, request: Request) -> Order:
    """Имитация оплаты пакета из текущего плана. Идемпотентно по `idempotency_key`."""
    result = await place_order(
        request.app.state.trips,
        request.app.state.orders,
        req.session_id,
        req.package_id,
        req.idempotency_key,
    )
    match result:
        case Success(order):
            return order
        case Failure(PlanNotFound()):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "План для этой сессии не найден")
        case Failure(PackageNotInPlan(package_id=package_id)):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Пакета {package_id} нет в плане")
        case Failure(AlreadyOrdered(order_id=order_id)):
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"По этому плану уже оформлен заказ {order_id}"
            )
        case Failure(IdempotencyConflict()):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Этот idempotency_key уже использован для другого пакета"
            )
    raise RuntimeError(f"Необработанный результат оформления заказа: {result}")
