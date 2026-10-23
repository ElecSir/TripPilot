import asyncio
from collections.abc import AsyncIterator

from trip_pilot.agent.events import AgentEvent, DeltaEvent, DoneEvent, StageEvent, StepEvent


class StubOrchestrator:
    """Заглушка этапа 0: проверяет путь UI → API → ядро → UI.

    Настоящий агент (машина стадий) появится на этапе 1 с тем же интерфейсом:
    принимает текст, отдаёт поток событий.
    """

    async def handle(self, text: str) -> AsyncIterator[AgentEvent]:
        yield StageEvent(stage="intake")
        yield StepEvent(text="Разбираю запрос")
        await asyncio.sleep(0.3)
        yield StepEvent(text="Агент ещё не подключён: это заглушка этапа 0")

        reply = f"Принял запрос: «{text}». Скоро здесь появится план поездки."
        for word in reply.split(" "):
            yield DeltaEvent(text=word + " ")
            await asyncio.sleep(0.02)
        yield DoneEvent()
