"""Понимание сообщения: черновик от LLM и его проверка кодом (этап 1, зона data).

LLM не собирает `TripRequest` сама: она заполняет `RequestDraft` — что именно сказал человек, —
а `apply_draft` проверяет черновик теми же правилами, что и разборщик, и собирает запрос.
Так модель не подсунет несуществующий город, прошедшую дату или отрицательный бюджет.

`understand` (задача 3) зовёт LLM и передаёт её ответ в `apply_draft`; пока здесь заглушка лида.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from returns.result import Failure, Result, Success

from trip_pilot.agent.intent import parse_when, resolve_city, resolve_place
from trip_pilot.domain.errors import DatesInPast, DomainError, NoResults
from trip_pilot.domain.offers import Destination
from trip_pilot.domain.request import Assumption, ChildAge, MustFlag, Party, Pet, TripRequest
from trip_pilot.domain.trip_state import TripState
from trip_pilot.ports import LLM

# Насколько сдвигается бюджет по «подешевле» / «подороже», как в parse_change.
_LESS = Decimal("0.8")
_MORE = Decimal("1.2")


class RequestDraft(BaseModel):
    """Что человек сказал: черновик LLM. Чего не сказал — `None`, додумывать нельзя.

    Даты — текстом, как их назвал человек («15 марта», «2026-11-14»), а не `date`:
    только так видно, был ли назван год. Разбирает их `parse_when`, поэтому правило
    «без года → ближайшая будущая, прошедшая → DatesInPast» работает как в разборщике.
    """

    origin: str | None = None  # город отправления: название, алиас или slug
    destination: str | None = None  # город или страна: название, алиас или slug
    month: int | None = Field(None, ge=1, le=12)  # «в ноябре»: месяц без точных дат
    date_from: str | None = None  # заезд: «15 марта», «2026-11-14», «14.11»
    date_to: str | None = None  # выезд: вместе с date_from даёт nights
    nights: int | None = Field(None, ge=1, le=30)
    adults: int | None = Field(None, ge=1)
    children_ages: list[ChildAge | None] | None = None  # None внутри списка — возраст не назван
    pets: list[Pet] | None = None
    budget: Decimal | None = None  # сумма на всех, ₽
    budget_change: Literal["less", "more"] | None = None  # «подешевле» / «подороже»
    shift_days: int | None = None  # «на 2 дня позже» → +2; считается от последнего поиска
    tags: list[str] | None = None
    must: list[MustFlag] | None = None


def _place(raw: str, catalog: list[Destination]) -> Result[str, DomainError]:
    """Куда: точный slug, город или страна. Страна с несколькими направлениями — AmbiguousCity."""
    value = raw.strip().lower().replace("ё", "е")
    if any(destination.slug == value for destination in catalog):
        return Success(value)
    return resolve_place(raw, catalog)


def _draft_date(raw: str, today: date) -> Result[date, DomainError]:
    """Дата из черновика: без года — ближайшая будущая, прошедшая — DatesInPast."""
    parsed = parse_when(raw, today)
    if parsed is None or parsed.get("date_from") is None:
        return Failure(NoResults(f"не понял дату «{raw}»"))
    start = parsed["date_from"]
    if start < today:
        return Failure(DatesInPast(start))
    return Success(start)


def _dates(
    draft: RequestDraft, state: TripState, base: TripRequest, today: date
) -> Result[dict[str, Any], DomainError]:
    patch: dict[str, Any] = {}
    start: date | None = None
    if draft.date_from is not None:
        found = _draft_date(draft.date_from, today)
        if isinstance(found, Failure):
            return found
        start = found.unwrap()
        patch["date_from"] = start
        patch["month"] = None
    elif draft.month is not None:
        if draft.month < today.month:
            return Failure(DatesInPast(date(today.year, draft.month, 1)))
        patch["month"] = draft.month
        patch["date_from"] = None
    if draft.date_to is not None:
        found = _draft_date(draft.date_to, today)
        if isinstance(found, Failure):
            return found
        if start is None:
            return Failure(NoResults("названа дата выезда без даты заезда"))
        nights = (found.unwrap() - start).days
        if nights < 1:
            return Failure(NoResults("дата выезда не позже даты заезда"))
        patch["nights"] = nights
    elif draft.nights is not None:
        patch["nights"] = draft.nights
    if draft.shift_days is not None:
        if draft.date_from is not None:
            return Failure(NoResults("не понял даты: и точная дата, и сдвиг"))
        anchor = state.search.check_in if state.search else base.date_from
        if anchor is None:
            return Failure(NoResults("не от чего считать сдвиг дат"))
        shifted = anchor + timedelta(days=draft.shift_days)
        if shifted < today:
            return Failure(DatesInPast(shifted))
        patch["date_from"] = shifted
        patch["month"] = None
    return Success(patch)


def _party(draft: RequestDraft, base: TripRequest) -> Party:
    return Party(
        adults=draft.adults if draft.adults is not None else base.party.adults,
        children_ages=(
            list(draft.children_ages)
            if draft.children_ages is not None
            else list(base.party.children_ages)
        ),
        pets=list(draft.pets) if draft.pets is not None else list(base.party.pets),
    )


def apply_draft(
    draft: RequestDraft, state: TripState, *, catalog: list[Destination], today: date
) -> Result[TripRequest, DomainError]:
    """Черновик → запрос. Чистая функция: без LLM и IO, новое ложится поверх `state.request`."""
    base = state.request or TripRequest()
    patch: dict[str, Any] = {}
    assumptions: list[Assumption] = []

    if draft.origin is not None:
        city = resolve_city(draft.origin, catalog)
        if isinstance(city, Failure):
            return city
        patch["origin"] = city.unwrap()

    if draft.destination is not None:
        place = _place(draft.destination, catalog)
        if isinstance(place, Failure):
            return place
        patch["destination"] = place.unwrap()

    dates = _dates(draft, state, base, today)
    if isinstance(dates, Failure):
        return dates
    patch.update(dates.unwrap())

    if draft.budget is not None:
        if draft.budget <= 0:
            return Failure(NoResults("бюджет должен быть больше нуля"))
        patch["budget"] = draft.budget
    elif draft.budget_change is not None:
        if base.budget is None:
            return Failure(NoResults("бюджет не назван: не от чего считать изменение"))
        factor = _LESS if draft.budget_change == "less" else _MORE
        amount = (base.budget * factor).quantize(Decimal("0.01"))
        patch["budget"] = amount
        share = "−20%" if draft.budget_change == "less" else "+20%"
        word = "меньше" if draft.budget_change == "less" else "больше"
        assumptions.append(
            Assumption(field="budget", value=str(amount), reason=f"«бюджет {word}» → {share}")
        )

    party = _party(draft, base)
    if party != base.party:
        patch["party"] = party

    must = list(base.must)
    if draft.pets:
        must = list(dict.fromkeys([*must, "pets_allowed"]))
    if draft.must:
        must = list(dict.fromkeys([*must, *draft.must]))
    if must != base.must:
        patch["must"] = must

    if draft.tags:
        patch["tags"] = list(dict.fromkeys([*base.tags, *draft.tags]))

    if assumptions:
        patch["assumptions"] = [*base.assumptions, *assumptions]

    try:
        request = TripRequest.model_validate(base.model_dump() | patch)
    except ValidationError as error:
        return Failure(NoResults(f"запрос не проходит проверку: {error.error_count()} поля"))
    if request.date_from is not None and request.date_from < today:
        return Failure(DatesInPast(request.date_from))
    return Success(request)


async def understand(
    text: str,
    state: TripState,
    *,
    catalog: list[Destination],
    today: date,
    llm: LLM,
) -> Result[TripRequest, DomainError] | None:
    """None — «разбери правилами». Тело заменит задача 3 (промпт + llm.structured)."""
    return None
