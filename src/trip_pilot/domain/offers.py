"""Предложения: направления, отели, перелёты, трансферы и собранные из них пакеты.

Контракт: наполняет data, читают все. Деньги — Decimal, время — с часовым поясом.
"""

from datetime import date, time
from decimal import Decimal
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, Field, model_validator

Meal = Literal["RO", "BB", "HB", "AI"]  # без питания, завтрак, полупансион, всё включено
Tier = Literal["economy", "balance", "comfort"]


class Destination(BaseModel):
    slug: str
    name: str
    country: str
    iata: str | None = None
    lat: float
    lon: float
    timezone: str  # IANA-зона
    tags: list[str] = []
    warm_months: list[int] = []


class Hotel(BaseModel):
    id: int
    destination: str
    name: str
    stars: int = Field(ge=1, le=5)
    price_per_night: Decimal = Field(gt=0)  # за номер
    meal: Meal
    free_cancellation: bool
    pets_allowed: bool
    kids_friendly: bool
    beach_distance_m: int | None = None
    check_in_time: time
    check_out_time: time
    rating: float = Field(ge=0, le=10)
    is_synthetic: bool = True


class Leg(BaseModel):
    """Перелёт или поезд в одну сторону."""

    id: int
    mode: Literal["flight", "train"]
    origin: str
    destination: str
    depart_at: AwareDatetime  # в часовом поясе пункта отправления
    arrive_at: AwareDatetime  # в часовом поясе пункта прибытия
    price: Decimal = Field(gt=0)  # за одного пассажира
    stops: int = Field(0, ge=0)
    carrier: str
    baggage_included: bool
    pets_allowed: bool
    is_synthetic: bool = True

    @model_validator(mode="after")
    def arrives_after_departure(self) -> Self:
        if self.arrive_at <= self.depart_at:
            raise ValueError("прибытие должно быть позже отправления")
        return self

    @property
    def duration_min(self) -> int:
        return int((self.arrive_at - self.depart_at).total_seconds() // 60)


class Transfer(BaseModel):
    id: int
    destination: str
    hotel_id: int
    kind: Literal["taxi", "shuttle"]
    duration_min: int = Field(gt=0)
    price: Decimal = Field(ge=0)  # за машину в одну сторону
    capacity: int = Field(ge=1)
    pets_allowed: bool


class Package(BaseModel):
    """Готовый вариант поездки: туда, отель, трансфер, обратно."""

    id: str
    tier: Tier
    destination: str
    outbound: Leg
    inbound: Leg
    hotel: Hotel
    transfer: Transfer | None = None
    check_in: date
    check_out: date
    nights: int = Field(ge=1)
    total: Decimal = Field(gt=0)  # перелёты × пассажиры + отель × ночи + трансфер × 2
    # Ключи: hotel, outbound (перелёт туда), inbound (обратно), transfer. Подписи для людей — в UI.
    price_breakdown: dict[str, Decimal] = {}
    issues: list[str] = []  # предупреждения проверки стыковок
    why: list[str] = []
    tradeoffs: list[str] = []
    risks: list[str] = []

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (self.check_out - self.check_in).days != self.nights:
            raise ValueError("nights не совпадает с датами заезда и выезда")
        if self.price_breakdown and sum(self.price_breakdown.values()) != self.total:
            raise ValueError("total не равен сумме price_breakdown")
        return self
