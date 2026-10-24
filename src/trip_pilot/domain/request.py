"""Запрос путешественника в структурированном виде. Контракт: собирает ui, читают лид и data."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Pet = Literal["dog", "cat", "other"]
# Жёсткие ограничения: нарушать нельзя, ослаблять — только с согласия пользователя.
MustFlag = Literal["pets_allowed", "direct_only", "kids_friendly"]
ChildAge = Annotated[int, Field(ge=0, le=17)]


class Assumption(BaseModel):
    """То, что агент додумал сам. UI показывает это чипом, пользователь может поправить."""

    field: str
    value: str
    reason: str  # «"на неделю" → 7 ночей»


class Party(BaseModel):
    adults: int = Field(2, ge=1)
    children_ages: list[ChildAge | None] = []  # None — ребёнок есть, возраст ещё не известен
    pets: list[Pet] = []

    @property
    def travellers(self) -> int:
        """Число пассажиров: на столько умножается цена перелёта."""
        return self.adults + len(self.children_ages)


class TripRequest(BaseModel):
    origin: str | None = None  # slug из data/reference/destinations.json
    destination: str | None = None  # None → агент предлагает направления
    month: int | None = Field(None, ge=1, le=12)  # если точных дат нет
    date_from: date | None = None
    nights: int | None = Field(None, ge=1, le=30)
    party: Party = Field(default_factory=Party)
    budget: Decimal | None = Field(None, gt=0)  # на всех, ₽
    tags: list[str] = []  # "sea", "city", "nature", "warm", "winter"
    must: list[MustFlag] = []
    assumptions: list[Assumption] = []
