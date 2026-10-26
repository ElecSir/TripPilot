"""Инвентарь: отели, перелёты и поезда, трансферы. Зона: data."""

from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, SmallInteger, String, Text, Time, text
from sqlalchemy.orm import Mapped, mapped_column

from trip_pilot.adapters.db.base import Base


class Hotel(Base):
    __tablename__ = "hotel"
    __table_args__ = (Index("ix_hotel_destination", "destination"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    destination: Mapped[str] = mapped_column(String(64), ForeignKey("destination.slug"))
    name: Mapped[str] = mapped_column(Text)
    stars: Mapped[int] = mapped_column(SmallInteger)
    price_per_night: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # за номер
    meal: Mapped[str] = mapped_column(String(2))  # RO | BB | HB | AI
    free_cancellation: Mapped[bool]
    pets_allowed: Mapped[bool]
    kids_friendly: Mapped[bool]
    beach_distance_m: Mapped[int | None]
    check_in_time: Mapped[time] = mapped_column(Time)
    check_out_time: Mapped[time] = mapped_column(Time)
    rating: Mapped[float]
    is_synthetic: Mapped[bool] = mapped_column(server_default=text("true"))


class TransportLeg(Base):
    """Перелёт или поезд в одну сторону. Время в БД хранится как timestamptz (UTC)."""

    __tablename__ = "transport_leg"
    __table_args__ = (Index("ix_transport_leg_route", "origin", "destination", "depart_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(16))  # flight | train
    origin: Mapped[str] = mapped_column(String(64), ForeignKey("destination.slug"))
    destination: Mapped[str] = mapped_column(String(64), ForeignKey("destination.slug"))
    depart_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    arrive_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # за одного пассажира
    stops: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    carrier: Mapped[str] = mapped_column(Text)
    baggage_included: Mapped[bool]
    pets_allowed: Mapped[bool]
    is_synthetic: Mapped[bool] = mapped_column(server_default=text("true"))


class Transfer(Base):
    __tablename__ = "transfer"
    __table_args__ = (Index("ix_transfer_hotel_id", "hotel_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    destination: Mapped[str] = mapped_column(String(64), ForeignKey("destination.slug"))
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotel.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # taxi | shuttle
    duration_min: Mapped[int]
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # за машину в одну сторону
    capacity: Mapped[int] = mapped_column(SmallInteger)
    pets_allowed: Mapped[bool]
    is_synthetic: Mapped[bool] = mapped_column(server_default=text("true"))
