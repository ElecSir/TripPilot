import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trip_pilot.adapters.db.chat import ChatMessage, ChatSession
from trip_pilot.adapters.db.orders import ORDER_NUMBER_SEQ, OrderRow, TripStateRow
from trip_pilot.domain.chat import Message, Role
from trip_pilot.domain.offers import Package
from trip_pilot.domain.trip_state import Order, TripState


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_session(self, session_id: uuid.UUID) -> None:
        await self._session.execute(
            insert(ChatSession).values(id=session_id).on_conflict_do_nothing()
        )

    async def add_message(self, session_id: uuid.UUID, role: Role, content: str) -> None:
        self._session.add(ChatMessage(session_id=session_id, role=role, content=content))

    async def list_messages(self, session_id: uuid.UUID) -> list[Message]:
        rows = await self._session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id)
        )
        return [Message(role=row.role, content=row.content) for row in rows]


class SqlTripStateRepository:
    """Порт TripStateRepository: план хранится одним jsonb-снимком на сессию."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def load(self, session_id: uuid.UUID) -> TripState | None:
        async with self._sessions() as db:
            row = await db.get(TripStateRow, session_id)
        return TripState.model_validate(row.data) if row else None

    async def save(self, state: TripState) -> None:
        data = state.model_dump(mode="json")  # Decimal и даты — строками, без потерь
        # Кеш поиска исключён из model_dump (в UI он не нужен), но для пересборки его храним.
        data["cache"] = state.cache.model_dump(mode="json") if state.cache else None
        stmt = insert(TripStateRow).values(
            session_id=state.session_id,
            version=state.version,
            data=data,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[TripStateRow.session_id],
            set_={
                "version": stmt.excluded.version,
                "data": stmt.excluded.data,
                "updated_at": func.now(),
            },
        )
        async with self._sessions() as db:
            await db.execute(stmt)
            await db.commit()


class SqlOrderRepository:
    """Порт OrderRepository: повтор с тем же ключом в той же сессии возвращает тот же заказ."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(
        self, session_id: uuid.UUID, package: Package, idempotency_key: str
    ) -> Order:
        async with self._sessions() as db:
            number = await db.scalar(select(ORDER_NUMBER_SEQ.next_value()))
            now = datetime.now(UTC)
            stmt = (
                insert(OrderRow)
                .values(
                    id=f"TP-{now.year}-{number:06d}",
                    session_id=session_id,
                    package_id=package.id,
                    package=package.model_dump(mode="json"),
                    total=package.total,
                    status="paid",
                    idempotency_key=idempotency_key,
                    created_at=now,
                )
                .on_conflict_do_nothing(constraint="uq_orders_session_key")
                .returning(OrderRow)
            )
            row = await db.scalar(stmt)
            if row is None:  # заказ с этим ключом уже оформлен: это повтор запроса
                row = await db.scalar(
                    select(OrderRow).where(
                        OrderRow.session_id == session_id,
                        OrderRow.idempotency_key == idempotency_key,
                    )
                )
            await db.commit()
        return Order(
            id=row.id,
            package_id=row.package_id,
            total=row.total,
            status=row.status,
            created_at=row.created_at,
        )
