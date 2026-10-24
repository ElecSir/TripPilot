import logging
import uuid
from collections.abc import AsyncIterator
from typing import Self

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from trip_pilot.adapters.db.repositories import ChatRepository
from trip_pilot.agent.actions import AgentAction
from trip_pilot.agent.events import DeltaEvent, DoneEvent, ErrorEvent, QuestionEvent, to_sse
from trip_pilot.domain.chat import Message

log = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """Сообщение пользователя (`text`) или нажатие кнопки (`action`) — ровно одно из двух."""

    session_id: uuid.UUID
    text: str | None = Field(None, min_length=1, max_length=4000)
    action: AgentAction | None = None

    @model_validator(mode="after")
    def exactly_one(self) -> Self:
        if (self.text is None) == (self.action is None):
            raise ValueError("нужно передать ровно одно из полей: text или action")
        return self


@router.post("/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    """Сообщение или действие → поток событий агента (text/event-stream)."""
    sessions = request.app.state.sessions
    orchestrator = request.app.state.orchestrator

    if req.action is not None:
        events = orchestrator.handle_action(req.session_id, req.action)
    else:
        async with sessions() as db:
            repo = ChatRepository(db)
            await repo.ensure_session(req.session_id)
            await repo.add_message(req.session_id, "user", req.text)
            await db.commit()
        events = orchestrator.handle(req.session_id, req.text)

    async def save_reply(text: str) -> None:
        async with sessions() as db:
            await ChatRepository(db).add_message(req.session_id, "assistant", text)
            await db.commit()

    async def stream() -> AsyncIterator[str]:
        reply: list[str] = []
        try:
            async for event in events:
                if isinstance(event, DeltaEvent):
                    reply.append(event.text)
                elif isinstance(event, QuestionEvent):
                    # Текст вопроса тоже часть ответа: после F5 он должен остаться в чате.
                    reply.append(f"\n\n{event.text}")
                elif isinstance(event, DoneEvent) and reply:
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
