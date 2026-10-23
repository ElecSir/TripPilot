import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from trip_pilot.adapters.db.repositories import ChatRepository
from trip_pilot.agent.events import DeltaEvent, DoneEvent, ErrorEvent, to_sse
from trip_pilot.domain.chat import Message

log = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    session_id: uuid.UUID
    text: str = Field(min_length=1, max_length=4000)


@router.post("/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    """Сообщение пользователя → поток событий агента (text/event-stream)."""
    sessions = request.app.state.sessions
    orchestrator = request.app.state.orchestrator

    async with sessions() as db:
        repo = ChatRepository(db)
        await repo.ensure_session(req.session_id)
        await repo.add_message(req.session_id, "user", req.text)
        await db.commit()

    async def save_reply(text: str) -> None:
        async with sessions() as db:
            await ChatRepository(db).add_message(req.session_id, "assistant", text)
            await db.commit()

    async def stream() -> AsyncIterator[str]:
        reply: list[str] = []
        try:
            async for event in orchestrator.handle(req.text):
                if isinstance(event, DeltaEvent):
                    reply.append(event.text)
                elif isinstance(event, DoneEvent):
                    # Сохраняем до отправки done: клиент вправе сразу закрыть соединение.
                    await save_reply("".join(reply).strip())
                yield to_sse(event)
        except Exception:
            log.exception("Агент упал на сообщении сессии %s", req.session_id)
            yield to_sse(ErrorEvent(text="Внутренняя ошибка агента, попробуйте ещё раз"))

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/{session_id}/messages")
async def history(session_id: uuid.UUID, request: Request) -> list[Message]:
    """История диалога: UI восстанавливает её после перезагрузки страницы."""
    async with request.app.state.sessions() as db:
        return await ChatRepository(db).list_messages(session_id)
