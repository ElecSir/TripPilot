"""Понимание сообщения с помощью LLM (этап 1, зона data).

Заглушка лида с сигнатурой из agent/toolkit.py: пока всегда None, и оркестратор разбирает
сообщение правилами, как в MVP. data заменяет тело (задачи 2–3 в tasks/data.md).
"""

from datetime import date

from returns.result import Result

from trip_pilot.domain.errors import DomainError
from trip_pilot.domain.offers import Destination
from trip_pilot.domain.request import TripRequest
from trip_pilot.domain.trip_state import TripState
from trip_pilot.ports import LLM


async def understand(
    text: str,
    state: TripState,
    *,
    catalog: list[Destination],
    today: date,
    llm: LLM,
) -> Result[TripRequest, DomainError] | None:
    """None — «разбери правилами»."""
    return None
