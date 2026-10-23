import asyncio
import uuid
from collections.abc import AsyncIterator

from trip_pilot.agent.actions import AgentAction
from trip_pilot.agent.events import AgentEvent, DeltaEvent, DoneEvent, StageEvent, StepEvent


class StubOrchestrator:
    """Заглушка: проверяет путь UI → API → ядро → UI.

    Настоящий оркестратор (задача 2 в tasks/lead.md) сохранит этот интерфейс:
    сообщение или действие на входе, поток событий на выходе.
    """

    async def handle(self, session_id: uuid.UUID, text: str) -> AsyncIterator[AgentEvent]:
        yield StageEvent(stage="intake")
        yield StepEvent(text="Разбираю запрос")
        await asyncio.sleep(0.3)
        yield StepEvent(text="Агент ещё не подключён: это заглушка")

        reply = f"Принял запрос: «{text}». Скоро здесь появится план поездки."
        for word in reply.split(" "):
            yield DeltaEvent(text=word + " ")
            await asyncio.sleep(0.02)
        yield DoneEvent()

    async def handle_action(
        self, session_id: uuid.UUID, action: AgentAction
    ) -> AsyncIterator[AgentEvent]:
        yield StepEvent(text=f"Получен выбор пакета {action.package_id}: обработка появится позже")
        yield DoneEvent()
