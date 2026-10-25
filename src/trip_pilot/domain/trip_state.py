"""Состояние плана поездки. JSON этой модели уходит в событие plan — контракт лида с ui."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from trip_pilot.domain.offers import Package
from trip_pilot.domain.request import Assumption, TripRequest

# О чём агент спросил. По slot ответ разбирается без угадывания: «2–6» — это возраст ребёнка.
QuestionSlot = Literal["origin", "when", "children_ages", "destination"]


class PendingQuestion(BaseModel):
    """Вопрос, на который агент ждёт ответа: по нему UI восстанавливает кнопки после F5."""

    slot: QuestionSlot
    text: str
    options: list[str] = []


class SearchWindow(BaseModel):
    """Конкретные даты, по которым шёл поиск, и что агент при этом додумал сам.

    В запросе остаётся то, что сказал пользователь («в ноябре»); здесь — во что это превратилось
    («с 7 по 14 ноября»). Так новое «в декабре» не спорит со старой датой из прошлого поиска.
    """

    check_in: date
    check_out: date
    nights: int = Field(ge=1)
    assumptions: list[Assumption] = []


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
    request: TripRequest | None = None  # что сказал пользователь
    search: SearchWindow | None = None  # даты последнего поиска
    packages: list[Package] = []
    # Названия мест плана: slug → «Москва». В запросе и рейсах места — slug, имя UI берёт отсюда.
    places: dict[str, str] = {}
    pending_question: PendingQuestion | None = None
    selected_package_id: str | None = None
    order: Order | None = None

    def package(self, package_id: str) -> Package | None:
        return next((p for p in self.packages if p.id == package_id), None)
