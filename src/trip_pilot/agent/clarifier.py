"""Один уточняющий вопрос и разбор ответа по его slot."""

import re
from datetime import date

from pydantic import ValidationError
from returns.result import Failure, Result, Success

from trip_pilot.agent.intent import (
    MONTHS,
    has_city_clause,
    month_number,
    normalize,
    parse_request,
    parse_when,
    resolve_city,
)
from trip_pilot.domain.errors import DomainError, NoResults
from trip_pilot.domain.offers import Destination
from trip_pilot.domain.request import Assumption, TripRequest
from trip_pilot.domain.trip_state import PendingQuestion

AGE_OPTIONS = {"до 2": 1, "2–6": 4, "7–12": 9, "13–17": 15}


def next_question(request: TripRequest, catalog: list[Destination]) -> PendingQuestion | None:
    """Выбирает один незаполненный слот в порядке origin, when, children_ages."""
    if request.origin is None:
        names = {city.slug: city.name for city in catalog}
        options = [names[slug] for slug in ("moscow", "spb", "kazan") if slug in names]
        return PendingQuestion(slot="origin", text="Откуда вылетаете?", options=options)
    if request.month is None and request.date_from is None:
        # Контракт не передаёт today: календарь используется только для вариантов месяцев.
        month = date.today().month
        options = [MONTHS[(month + offset) % 12].capitalize() for offset in range(3)]
        return PendingQuestion(slot="when", text="Когда хотите поехать?", options=options)
    if None in request.party.children_ages:
        position = request.party.children_ages.index(None) + 1
        return PendingQuestion(
            slot="children_ages",
            text=f"Сколько лет ребёнку №{position}?",
            options=list(AGE_OPTIONS),
        )
    return None


def _with_answer(request: TripRequest, patch: dict) -> Result[TripRequest, DomainError]:
    fields = set(patch)
    assumptions = [item for item in request.assumptions if item.field not in fields]
    try:
        return Success(
            TripRequest.model_validate(request.model_dump() | patch | {"assumptions": assumptions})
        )
    except ValidationError:
        return Failure(NoResults("Ответ не подходит для этого поля поездки"))


def apply_answer(
    question: PendingQuestion,
    text: str,
    request: TripRequest,
    *,
    catalog: list[Destination],
    today: date,
) -> Result[TripRequest, DomainError] | None:
    """Не похожее на ответ сообщение отдаём разборщику нового запроса целиком."""
    low = normalize(text).strip(" .!?")
    if question.slot in ("origin", "destination"):
        raw = re.sub(r"^(?:из|в|во)\s+", "", low)
        if (
            month_number(raw) is not None
            or len(raw.split()) > 3
            or not re.fullmatch(r"[а-яa-z -]+", raw)
            or re.search(
                r"\b(?:хочу|едем|еду|море|с|на|бюджет|спасибо|да|нет|привет|"
                r"горы|город|недорого|в|во|из|через)\b",
                raw,
            )
        ):
            return None
        city = resolve_city(raw, catalog)
        if isinstance(city, Failure):
            return city
        return _with_answer(request, {question.slot: city.unwrap()})
    if question.slot == "when":
        if re.search(r"\b(?:собак\w*|кот\w*|ребен\w*|бюджет|из|хочу)\b", low):
            return None
        if has_city_clause(low):
            return None
        try:
            temporal = parse_when(low, today)
        except (ValueError, OverflowError):
            return Failure(NoResults("Проверьте дату поездки"))
        if temporal is None:
            return None
        # Общий разборщик уже обрабатывает календарные ошибки и даты в прошлом.
        return parse_request(low, catalog=[], today=today, base=request)
    if question.slot == "children_ages":
        if None not in request.party.children_ages:
            return None
        value = low.replace("—", "–").replace("-", "–")
        value = re.sub(r"\s*–\s*", "–", value)
        assumed = value in AGE_OPTIONS
        if assumed:
            age = AGE_OPTIONS[value]
        elif match := re.fullmatch(r"(\d{1,2})(?:\s*(?:лет|год|года))?", value):
            age = int(match[1])
        else:
            return None
        if not 0 <= age <= 17:
            return Failure(NoResults("Возраст ребёнка должен быть от 0 до 17 лет"))
        ages = list(request.party.children_ages)
        position = ages.index(None)
        ages[position] = age
        assumptions = list(request.assumptions)
        if assumed:
            assumptions.append(
                Assumption(
                    field=f"party.children_ages.{position}",
                    value=str(age),
                    reason=f"Для ребёнка №{position + 1} диапазон «{text}» принят за {age} лет",
                )
            )
        party = request.party.model_dump() | {"children_ages": ages}
        return Success(
            TripRequest.model_validate(
                request.model_dump()
                | {
                    "party": party,
                    "assumptions": assumptions,
                }
            )
        )
    return None
