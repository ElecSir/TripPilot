"""Функции зоны data, которые вызывает оркестратор. Контракт лида.

Здесь только сигнатуры. Реализации пишет data: понимание запроса и объяснения (agent/intent.py,
agent/clarifier.py, agent/understand.py, services/explanation.py; до этапа 1 их вела ui)
и подбор (planning/).

Правила и шаблоны — чистые синхронные функции: без IO, «сегодня» передаётся параметром.
На них держится режим без LLM. `understand` и `narrate` (этап 1) — асинхронные: они зовут LLM,
а при её сбое возвращаются к правилам и шаблонам.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from returns.result import Result

from trip_pilot.domain.errors import DomainError
from trip_pilot.domain.knowledge import KnowledgeHit
from trip_pilot.domain.offers import Destination, Hotel, Leg, Package, Transfer
from trip_pilot.domain.request import TripRequest
from trip_pilot.domain.trip_state import PendingQuestion, TripState
from trip_pilot.ports import LLM


class ParseRequest(Protocol):
    """data, agent/intent.py: текст → запрос. `base` — уже собранный запрос, новое его дополняет."""

    def __call__(
        self,
        text: str,
        *,
        catalog: list[Destination],
        today: date,
        base: TripRequest | None = None,
    ) -> Result[TripRequest, DomainError]: ...


class ParseChange(Protocol):
    """data, agent/intent.py: «на 2 дня позже» → патч полей запроса или None, если это не изменение.

    `current` приходит с конкретными датами последнего поиска (`date_from`, `nights`),
    поэтому сдвиг считается от них.
    """

    def __call__(
        self, text: str, current: TripRequest, *, today: date
    ) -> dict[str, Any] | None: ...


class NextQuestion(Protocol):
    """data, agent/clarifier.py: какого обязательного не хватает (origin, when, children_ages).

    `today` нужен для вариантов месяцев в вопросе «Когда?».
    """

    def __call__(
        self, request: TripRequest, catalog: list[Destination], *, today: date
    ) -> PendingQuestion | None: ...


class ApplyAnswer(Protocol):
    """data, agent/clarifier.py: ответ на заданный вопрос → дополненный запрос.

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
    """data, services/explanation.py: заполняет why, tradeoffs и risks пакета."""

    def __call__(self, package: Package, request: TripRequest) -> Package: ...


class Understand(Protocol):
    """data, agent/understand.py: сообщение → новый запрос с помощью LLM (этап 1).

    LLM заполняет черновик, код его проверяет. None — LLM недоступна или её ответ
    не прошёл проверку: оркестратор разбирает сообщение правилами, как в MVP.
    """

    async def __call__(
        self,
        text: str,
        state: TripState,
        *,
        catalog: list[Destination],
        today: date,
        llm: LLM,
    ) -> Result[TripRequest, DomainError] | None: ...


class Narrate(Protocol):
    """data, services/explanation.py: объяснения всех пакетов плана разом (этап 1).

    Вызывается всегда, после `explain`. Без LLM — сравнение пакетов друг с другом шаблоном,
    с LLM — ещё и живой текст со ссылками [S1] на `knowledge` (их кладут в `package.sources`).
    Числа в тексте — только из фактов пакета.
    """

    async def __call__(
        self,
        packages: list[Package],
        request: TripRequest,
        *,
        knowledge: list[KnowledgeHit],
        llm: LLM,
    ) -> list[Package]: ...


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
    # Этап 1. Не заданы — оркестратор работает как в MVP: правила и шаблоны.
    understand: Understand | None = None
    narrate: Narrate | None = None
