"""Источники данных поверх синтетических таблиц БД. Зона: data.

Реализуют порты DestinationCatalog, HotelSource, TransportSource, TransferSource.
Репозитории только достают кандидатов: фильтры по must (животные, дети, без пересадок)
применяются в planning/. Исключение: физическая невозможность (вместимость трансфера).
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trip_pilot.adapters.db import inventory as orm
from trip_pilot.adapters.db import reference
from trip_pilot.domain.offers import Destination, Hotel, Leg, Transfer
from trip_pilot.domain.request import Party

SessionFactory = async_sessionmaker[AsyncSession]


async def _zones(session: AsyncSession) -> dict[str, ZoneInfo]:
    """Часовой пояс каждого направления: в БД время рейсов хранится в UTC."""
    rows = await session.execute(select(reference.Destination.slug, reference.Destination.timezone))
    return {slug: ZoneInfo(tz) for slug, tz in rows}


class SyntheticDestinationCatalog:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def all(self) -> list[Destination]:
        async with self._sessions() as session:
            query = select(reference.Destination).order_by(reference.Destination.slug)
            rows = (await session.scalars(query)).all()
        return [Destination.model_validate(row, from_attributes=True) for row in rows]


class SyntheticHotelSource:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def search(
        self, destination: str, check_in: date, check_out: date, party: Party
    ) -> list[Hotel]:
        # В синтетике у отелей нет календаря занятости: даты и состав группы не влияют.
        async with self._sessions() as session:
            query = (
                select(orm.Hotel).where(orm.Hotel.destination == destination).order_by(orm.Hotel.id)
            )
            rows = (await session.scalars(query)).all()
        return [Hotel.model_validate(row, from_attributes=True) for row in rows]


class SyntheticTransportSource:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def search(self, origin: str, destination: str, day: date, party: Party) -> list[Leg]:
        """Рейсы и поезда, вылетающие в этот день по местному времени пункта отправления."""
        async with self._sessions() as session:
            zones = await _zones(session)
            if origin not in zones or destination not in zones:
                return []
            start = datetime.combine(day, time.min, tzinfo=zones[origin])
            query = (
                select(orm.TransportLeg)
                .where(
                    orm.TransportLeg.origin == origin,
                    orm.TransportLeg.destination == destination,
                    orm.TransportLeg.depart_at >= start,
                    orm.TransportLeg.depart_at < start + timedelta(days=1),
                )
                .order_by(orm.TransportLeg.depart_at, orm.TransportLeg.id)
            )
            rows = (await session.scalars(query)).all()
        legs = []
        for row in rows:
            leg = Leg.model_validate(row, from_attributes=True)
            legs.append(
                leg.model_copy(
                    update={
                        "depart_at": row.depart_at.astimezone(zones[origin]),
                        "arrive_at": row.arrive_at.astimezone(zones[destination]),
                    }
                )
            )
        return legs


class SyntheticTransferSource:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def search(self, hotel_id: int, arrive_at: datetime, party: Party) -> list[Transfer]:
        # Машины, куда группа не помещается, не возвращаем: это физическая невозможность.
        async with self._sessions() as session:
            query = (
                select(orm.Transfer)
                .where(orm.Transfer.hotel_id == hotel_id)
                .where(orm.Transfer.capacity >= party.travellers)
                .order_by(orm.Transfer.id)
            )
            rows = (await session.scalars(query)).all()
        return [Transfer.model_validate(row, from_attributes=True) for row in rows]
