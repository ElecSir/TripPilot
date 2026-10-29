"""Чтение SSE в фоне: поток не зависит от перерисовок Streamlit."""

import logging
from queue import Empty, SimpleQueue
from threading import Event, Thread

import httpx

from trip_pilot.agent.events import AgentEvent, DoneEvent, ErrorEvent, parse_event

LOGGER = logging.getLogger(__name__)


class AgentStream:
    """Рабочий поток только читает HTTP; состояние экрана меняет основной поток."""

    def __init__(self, client: httpx.Client, payload: dict) -> None:
        self._events: SimpleQueue[AgentEvent] = SimpleQueue()
        self._finished = Event()
        self.error: str | None = None
        Thread(target=self._read, args=(client, payload), daemon=True).start()

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    def wait(self, timeout: float) -> bool:
        """Ожидание для тестов; экран читает очередь без блокировки."""
        return self._finished.wait(timeout)

    def drain(self) -> list[AgentEvent]:
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except Empty:
                return events

    def _read(self, client: httpx.Client, payload: dict) -> None:
        try:
            with client.stream("POST", "/api/chat", json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    event = parse_event(line.removeprefix("data: "))
                    self._events.put(event)
                    if isinstance(event, (DoneEvent, ErrorEvent)):
                        return
                raise ValueError("Поток завершился без итогового события")
        except Exception:
            LOGGER.exception("Не удалось дочитать ответ агента")
            self.error = "Не удалось получить ответ агента. Повторите попытку позже."
        finally:
            self._finished.set()
