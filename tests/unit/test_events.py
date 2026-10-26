from trip_pilot.agent.events import (
    DeltaEvent,
    DoneEvent,
    QuestionEvent,
    StepEvent,
    parse_event,
    to_sse,
)


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
