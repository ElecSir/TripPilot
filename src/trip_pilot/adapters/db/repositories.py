import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from trip_pilot.adapters.db.chat import ChatMessage, ChatSession
from trip_pilot.domain.chat import Message, Role


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
