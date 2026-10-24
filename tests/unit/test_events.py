import asyncio
import uuid

from trip_pilot.agent.events import (
    DeltaEvent,
    DoneEvent,
    QuestionEvent,
    StepEvent,
    parse_event,
    to_sse,
)
from trip_pilot.agent.orchestrator import StubOrchestrator


def test_sse_roundtrip_keeps_event_type():
    events = [
        StepEvent(text="Ищу перелёты"),
        QuestionEvent(text="Сколько лет ребёнку?", options=["до 2", "2–6"]),
        DeltaEvent(text="Привет "),
        DoneEvent(),
    ]
    for event in events:
        line = to_sse(event)
        assert line.startswith("data: ")
        assert line.endswith("\n\n")
        assert parse_event(line.removeprefix("data: ").strip()) == event


def test_stub_orchestrator_streams_reply_and_finishes():
    async def collect():
        orchestrator = StubOrchestrator()
        return [event async for event in orchestrator.handle(uuid.uuid4(), "в Сочи на выходные")]

    events = asyncio.run(collect())

    assert isinstance(events[-1], DoneEvent)
    reply = "".join(e.text for e in events if isinstance(e, DeltaEvent))
    assert "в Сочи на выходные" in reply
