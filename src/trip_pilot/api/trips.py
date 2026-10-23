"""План поездки и заказы.

Контракт для ui зафиксирован; реализация — задачи 1 и 4 в tasks/lead.md.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from trip_pilot.domain.trip_state import Order, TripState

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
async def get_trip(session_id: uuid.UUID) -> TripState:
    """Текущий план поездки: по нему UI восстанавливает панель и кнопки вопроса после F5."""
    # Хранение плана — задача 1. До неё у любой сессии плана нет, и это законный ответ контракта.
    raise HTTPException(status.HTTP_404_NOT_FOUND, "План для этой сессии ещё не создан")


@router.post(
    "/orders",
    status_code=status.HTTP_201_CREATED,
    responses={501: {"description": "Оформление заказа ещё не реализовано"}},
)
async def create_order(req: OrderRequest) -> Order:
    """Имитация оплаты выбранного пакета. Идемпотентно по `idempotency_key`."""
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Оформление заказа появится в задаче 4")
