"""Конкретные даты поиска из того, что сказал пользователь. В MVP — простое правило.

Позже data заменит его гибкими датами (самое дешёвое окно), интерфейс останется тем же.
"""

from datetime import date, timedelta

from trip_pilot.agent.texts import MONTHS_NOMINATIVE, day
from trip_pilot.domain.request import Assumption, TripRequest
from trip_pilot.domain.trip_state import SearchWindow

DEFAULT_NIGHTS = 7
MIN_LEAD_DAYS = 3  # раньше чем через 3 дня поездку не предлагаем
SATURDAY = 5


def first_saturday(month: int, today: date) -> date:
    """Ближайшая суббота указанного месяца не раньше чем через MIN_LEAD_DAYS дней.

    Месяц в этом году уже прошёл или все его субботы слишком близко — берём следующий год.
    """
    earliest = today + timedelta(days=MIN_LEAD_DAYS)
    year = today.year if month >= today.month else today.year + 1
    for y in (year, year + 1):
        d = date(y, month, 1)
        d += timedelta(days=(SATURDAY - d.weekday()) % 7)
        while d.month == month:
            if d >= earliest:
                return d
            d += timedelta(days=7)
    raise AssertionError("в каждом месяце следующего года есть подходящая суббота")


def resolve_window(request: TripRequest, today: date) -> SearchWindow | None:
    """Даты для поиска и допущения о них. None — о времени поездки ничего не известно."""
    assumptions = []
    nights = request.nights
    if nights is None:
        nights = DEFAULT_NIGHTS
        assumptions.append(
            Assumption(field="nights", value=str(nights), reason="длительность не указана — неделя")
        )

    check_in = request.date_from
    if check_in is None:
        if request.month is None:
            return None
        check_in = first_saturday(request.month, today)
        month = MONTHS_NOMINATIVE[request.month].lower()
        assumptions.append(
            Assumption(
                field="date_from",
                value=check_in.isoformat(),
                reason=f"{month} → заезд в ближайшую субботу, {day(check_in)}",
            )
        )

    return SearchWindow(
        check_in=check_in,
        check_out=check_in + timedelta(days=nights),
        nights=nights,
        assumptions=assumptions,
    )
