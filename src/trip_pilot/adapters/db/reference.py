"""Справочник направлений. Зона: data."""

from sqlalchemy import Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from trip_pilot.adapters.db.base import Base


class Destination(Base):
    __tablename__ = "destination"
    __table_args__ = (
        Index(
            "ix_destination_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(Text)
    country: Mapped[str] = mapped_column(Text)
    iata: Mapped[str | None] = mapped_column(String(3))
    lat: Mapped[float]
    lon: Mapped[float]
    timezone: Mapped[str] = mapped_column(Text)  # IANA-зона, например Europe/Moscow
    is_synthetic: Mapped[bool] = mapped_column(server_default=text("false"))
