"""Доменные ошибки для Railway Oriented Programming.

Функции ядра возвращают Result из библиотеки returns: Success(значение) или Failure(ошибка).
Каждая ошибка — сигнал для диалога: агент превращает её в вопрос, варианты или объяснение.
Инфраструктурные сбои (БД, сеть, LLM) сюда не относятся: это обычные исключения.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class MissingSlot:
    slot: Literal["origin", "when", "children_ages"]


@dataclass(frozen=True)
class UnknownCity:
    raw: str


@dataclass(frozen=True)
class AmbiguousCity:
    raw: str
    candidates: tuple[str, ...]  # slug'и похожих городов


@dataclass(frozen=True)
class DatesInPast:
    start: date


@dataclass(frozen=True)
class BudgetTooLow:
    budget: Decimal
    min_total: Decimal  # сколько стоит самый дешёвый подходящий вариант


@dataclass(frozen=True)
class NoResults:
    reason: str


# Ошибки оформления заказа.


@dataclass(frozen=True)
class PlanNotFound:
    session_id: uuid.UUID


@dataclass(frozen=True)
class PackageNotInPlan:
    package_id: str


@dataclass(frozen=True)
class AlreadyOrdered:
    order_id: str  # по плану уже оформлен заказ на другой пакет


@dataclass(frozen=True)
class IdempotencyConflict:
    key: str  # ключ уже использован для другого пакета


BookingError = PlanNotFound | PackageNotInPlan | AlreadyOrdered | IdempotencyConflict

RequestError = MissingSlot | UnknownCity | AmbiguousCity | DatesInPast | BudgetTooLow | NoResults

DomainError = RequestError | BookingError
