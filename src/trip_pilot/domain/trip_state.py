"""Состояние плана поездки. JSON этой модели уходит в событие plan — контракт лида с ui."""

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel

from trip_pilot.domain.offers import Package
from trip_pilot.domain.request import TripRequest


class PendingQuestion(BaseModel):
    """Вопрос, на который агент ждёт ответа: по нему UI восстанавливает кнопки после F5."""

    text: str
    options: list[str] = []


class Order(BaseModel):
    id: str  # TP-<год>-<6 цифр>
    package_id: str
    total: Decimal
    status: Literal["paid", "cancelled"]
    created_at: AwareDatetime


class TripState(BaseModel):
    session_id: uuid.UUID
    version: int = 0
    stage: str = "intake"
    request: TripRequest | None = None
    packages: list[Package] = []
    pending_question: PendingQuestion | None = None
    selected_package_id: str | None = None
    order: Order | None = None

    def package(self, package_id: str) -> Package | None:
        return next((p for p in self.packages if p.id == package_id), None)
