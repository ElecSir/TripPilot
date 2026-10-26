"""Порты: интерфейсы, через которые ядро обращается к внешнему миру.

Реализации живут в adapters/ и rag/ и подставляются в api/main.py; в тестах — tests/fakes.py.
Контракт: меняет только лид.
"""

import uuid
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from trip_pilot.domain.knowledge import KnowledgeHit
from trip_pilot.domain.offers import Destination, Hotel, Leg, Package, Transfer
from trip_pilot.domain.request import Party
from trip_pilot.domain.trip_state import Order, TripState

ChatMessages = list[dict[str, str]]  # [{"role": "user", "content": "..."}]


class LLMUnavailable(Exception):
    """Любой сбой LLM: нет ключа, сеть, таймаут, 401/403, ответ не прошёл схему.

    Адаптер бросает его после своих повторов. Ядро ловит только его и уходит в режим без LLM.
    """


@runtime_checkable
class DestinationCatalog(Protocol):
    async def all(self) -> list[Destination]: ...


@runtime_checkable
class HotelSource(Protocol):
    async def search(
        self, destination: str, check_in: date, check_out: date, party: Party
    ) -> list[Hotel]: ...


@runtime_checkable
class TransportSource(Protocol):
    async def search(self, origin: str, destination: str, day: date, party: Party) -> list[Leg]: ...


@runtime_checkable
class TransferSource(Protocol):
    async def search(self, hotel_id: int, arrive_at: datetime, party: Party) -> list[Transfer]: ...


@runtime_checkable
class KnowledgeBase(Protocol):
    async def search(
        self,
        query: str,
        *,
        destination: str | None = None,
        doc_type: str | None = None,
        limit: int = 5,
    ) -> list[KnowledgeHit]: ...


@runtime_checkable
class LLM(Protocol):
    enabled: bool  # False → методы бросают LLMUnavailable

    async def complete(self, messages: ChatMessages) -> str: ...

    async def structured[T: BaseModel](self, messages: ChatMessages, schema: type[T]) -> T: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class OrderRepository(Protocol):
    async def create(
        self, session_id: uuid.UUID, package: Package, idempotency_key: str
    ) -> Order: ...


@runtime_checkable
class TripStateRepository(Protocol):
    async def load(self, session_id: uuid.UUID) -> TripState | None: ...

    async def save(self, state: TripState) -> None: ...
