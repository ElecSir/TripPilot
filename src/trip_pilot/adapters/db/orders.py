"""Состояние плана поездки и заказы. Зона: лид."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Numeric, Sequence, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trip_pilot.adapters.db.base import Base

# Порядковый номер заказа в TP-<год>-<6 цифр>. Пропуски номеров допустимы.
ORDER_NUMBER_SEQ = Sequence("order_number_seq")


class TripStateRow(Base):
    """План поездки одним jsonb-снимком TripState: модель плана меняется без миграций."""

    __tablename__ = "trip_state"

    session_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    version: Mapped[int]
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OrderRow(Base):
    __tablename__ = "orders"
    __table_args__ = (
        # Ключ идемпотентности уникален в пределах сессии; индекс покрывает и поиск по session_id.
        UniqueConstraint("session_id", "idempotency_key", name="uq_orders_session_key"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[uuid.UUID]
    package_id: Mapped[str] = mapped_column(Text)
    package: Mapped[dict[str, Any]] = mapped_column(JSONB)  # снимок пакета на момент оплаты
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
