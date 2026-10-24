"""Функции зон ui и data, которые вызывает оркестратор. Контракт лида.

Здесь только сигнатуры. Реализации пишут ui (agent/intent.py, agent/clarifier.py,
services/explanation.py) и data (planning/). Все функции чистые и синхронные: без IO,
«сегодня» передаётся параметром.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from returns.result import Result

from trip_pilot.domain.errors import DomainError
from trip_pilot.domain.offers import Destination, Hotel, Leg, Package, Transfer
from trip_pilot.domain.request import TripRequest
from trip_pilot.domain.trip_state import PendingQuestion


class ParseRequest(Protocol):
    """ui, agent/intent.py: текст → запрос. `base` — уже собранный запрос, новое его дополняет."""

    def __call__(
        self,
        text: str,
        *,
        catalog: list[Destination],
        today: date,
        base: TripRequest | None = None,
    ) -> Result[TripRequest, DomainError]: ...


class ParseChange(Protocol):
    """ui, agent/intent.py: «на 2 дня позже» → патч полей запроса или None, если это не изменение.

    `current` приходит с конкретными датами последнего поиска (`date_from`, `nights`),
    поэтому сдвиг считается от них.
    """

    def __call__(
        self, text: str, current: TripRequest, *, today: date
    ) -> dict[str, Any] | None: ...


class NextQuestion(Protocol):
    """ui, agent/clarifier.py: какого обязательного не хватает (origin, when, children_ages)."""

    def __call__(
        self, request: TripRequest, catalog: list[Destination]
    ) -> PendingQuestion | None: ...


class ApplyAnswer(Protocol):
    """ui, agent/clarifier.py: ответ на заданный вопрос → дополненный запрос.

    None — текст не похож на ответ (пользователь написал что-то своё), тогда оркестратор
    разбирает его как обычное сообщение. Отвечает на все slot, включая destination.
    """

    def __call__(
        self,
        question: PendingQuestion,
        text: str,
        request: TripRequest,
        *,
        catalog: list[Destination],
        today: date,
    ) -> Result[TripRequest, DomainError] | None: ...


class PickDestinations(Protocol):
    """data, planning/inspiration.py: до трёх направлений, если пользователь не знает, куда."""

    def __call__(self, request: TripRequest, catalog: list[Destination]) -> list[Destination]: ...


class SimplePackages(Protocol):
    """data, planning/packages.py: три пакета (economy, balance, comfort).

    В `request` уже конкретные `date_from` и `nights`. Ничего не подошло — `NoResults`,
    не хватает бюджета — `BudgetTooLow`.
    """

    def __call__(
        self,
        request: TripRequest,
        outbound: list[Leg],
        inbound: list[Leg],
        hotels: list[Hotel],
        transfers_by_hotel: dict[int, list[Transfer]],
    ) -> Result[list[Package], DomainError]: ...


class CheckPackage(Protocol):
    """data, planning/itinerary.py: предупреждения о стыковках понятным текстом."""

    def __call__(self, package: Package) -> list[str]: ...


class Explain(Protocol):
    """ui, services/explanation.py: заполняет why, tradeoffs и risks пакета."""

    def __call__(self, package: Package, request: TripRequest) -> Package: ...


@dataclass(frozen=True)
class Toolkit:
    parse_request: ParseRequest
    parse_change: ParseChange
    next_question: NextQuestion
    apply_answer: ApplyAnswer
    pick_destinations: PickDestinations
    simple_packages: SimplePackages
    check_package: CheckPackage
    explain: Explain
