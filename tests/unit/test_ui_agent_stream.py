"""Фоновое чтение SSE: порядок событий, закрытие соединения и ошибки."""

import json
from threading import Event

import httpx
import pytest

from trip_pilot.agent.events import DeltaEvent, DoneEvent, ErrorEvent, StageEvent
from trip_pilot.ui.agent_stream import AgentStream


def test_stream_waits_in_background_and_keeps_event_order() -> None:
    waiting = Event()
    release = Event()
    closed = Event()
    requests = []

    class SlowResponse(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"type":"stage","stage":"search"}\n\n'
            waiting.set()
            assert release.wait(3)
            yield b'data: {"type":"delta","text":"ready"}\n\n'
            yield b'data: {"type":"done"}\n\n'
            raise AssertionError("После done поток больше не читается")

        def close(self):
            closed.set()

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, stream=SlowResponse())

    payload = {"session_id": "test", "action": {"type": "select_package", "package_id": "p1"}}
    with httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler)) as client:
        stream = AgentStream(client, payload)
        try:
            assert waiting.wait(2)
            assert not stream.finished
            assert stream.drain() == [StageEvent(stage="search")]
            assert stream.drain() == []
        finally:
            release.set()
        assert stream.wait(2)
        assert stream.drain() == [DeltaEvent(text="ready"), DoneEvent()]
        assert stream.error is None
        assert closed.is_set()
        assert requests == [payload]


@pytest.mark.parametrize(("status", "content"), [
    (503, b"unavailable"),
    (200, b'data: {"type":"delta","text":"unfinished"}\n\n'),
    (200, b'data: invalid json\n\n'),
])
def test_stream_reports_transport_invalid_event_and_truncation(status, content) -> None:
    def handler(request):
        return httpx.Response(status, content=content)

    with httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler)) as client:
        stream = AgentStream(client, {"session_id": "test", "text": "hello"})
        assert stream.wait(2)
        assert stream.finished
        assert stream.error == "Не удалось получить ответ агента. Повторите попытку позже."


def test_agent_error_is_preserved_without_waiting_for_done() -> None:
    with httpx.Client(base_url="http://api", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text='data: {"type":"error","text":"failed"}\n\n')
    )) as client:
        stream = AgentStream(client, {"session_id": "test", "text": "hello"})
        assert stream.wait(2)
        assert stream.drain() == [ErrorEvent(text="failed")]
        assert stream.error is None
