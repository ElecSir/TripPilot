"""Тесты проверки стыковок: по одному на каждое правило и один на местные часовые пояса."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from trip_pilot.domain.offers import Hotel, Leg, Package, Transfer
from trip_pilot.planning.itinerary import check_package

MSK = ZoneInfo("Europe/Moscow")
BKK = ZoneInfo("Asia/Bangkok")

HOTEL = Hotel(
    id=1, destination="sochi", name="Тест", stars=3, price_per_night=Decimal("5000"),
    meal="BB", free_cancellation=True, pets_allowed=False, kids_friendly=True,
    check_in_time=time(14), check_out_time=time(12), rating=8.0,
)


def _transfer(minutes: int) -> Transfer:
    return Transfer(
        id=1, destination="sochi", hotel_id=1, kind="taxi", duration_min=minutes,
        price=Decimal("1500"), capacity=4, pets_allowed=False,
    )


def _package(
    arrive: datetime,
    depart: datetime,
    check_in: date,
    check_out: date,
    transfer_min: int | None = 30,
) -> Package:
    outbound = Leg(
        id=1, mode="flight", origin="moscow", destination="sochi",
        depart_at=arrive - timedelta(hours=3), arrive_at=arrive, price=Decimal("8000"),
        carrier="Тест", baggage_included=True, pets_allowed=True,
    )
    inbound = Leg(
        id=2, mode="flight", origin="sochi", destination="moscow",
        depart_at=depart, arrive_at=depart + timedelta(hours=3), price=Decimal("8000"),
        carrier="Тест", baggage_included=True, pets_allowed=True,
    )
    return Package(
        id="t", tier="economy", destination="sochi", outbound=outbound, inbound=inbound,
        hotel=HOTEL, transfer=_transfer(transfer_min) if transfer_min else None,
        check_in=check_in, check_out=check_out, nights=(check_out - check_in).days,
        total=Decimal("1000"),
    )


def _msk(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=MSK)


def test_clean_package_has_no_issues():
    package = _package(_msk(10, 15), _msk(15, 16), date(2026, 11, 10), date(2026, 11, 15))
    assert check_package(package) == []


def test_late_arrival_with_transfer():
    # прилёт 22:30 + трансфер 45 мин → 23:15
    package = _package(
        _msk(10, 22, 30), _msk(15, 16), date(2026, 11, 10), date(2026, 11, 15), transfer_min=45
    )
    issues = check_package(package)
    assert len(issues) == 1
    assert "Поздний приезд" in issues[0]


def test_arrival_before_23_with_transfer_is_fine():
    package = _package(
        _msk(10, 22, 0), _msk(15, 16), date(2026, 11, 10), date(2026, 11, 15), transfer_min=30
    )
    assert check_package(package) == []


def test_night_arrival_needs_extra_night():
    # прилёт 02:00 10-го, отель с 10-го: номера до 14:00 не будет
    package = _package(_msk(10, 2), _msk(15, 16), date(2026, 11, 10), date(2026, 11, 15))
    issues = check_package(package)
    assert len(issues) == 1
    assert "ночью" in issues[0]


def test_night_arrival_with_previous_night_booked_is_fine():
    package = _package(_msk(10, 2), _msk(15, 16), date(2026, 11, 9), date(2026, 11, 15))
    assert check_package(package) == []


def test_check_in_date_mismatch():
    package = _package(_msk(10, 15), _msk(15, 16), date(2026, 11, 11), date(2026, 11, 15))
    issues = check_package(package)
    assert len(issues) == 1
    assert "не совпадает" in issues[0]
    assert "заезда" in issues[0]


def test_check_out_date_mismatch():
    package = _package(_msk(10, 15), _msk(16, 16), date(2026, 11, 10), date(2026, 11, 15))
    issues = check_package(package)
    assert len(issues) == 1
    assert "не совпадает" in issues[0]
    assert "выезда" in issues[0]


def test_dates_are_compared_in_local_timezone():
    # 01:30 11-го по Бангкоку — это ещё 10-е по UTC; сравнивать нужно по местному времени
    arrive = datetime(2026, 11, 11, 1, 30, tzinfo=BKK)
    package = _package(arrive, _msk(16, 16), date(2026, 11, 11), date(2026, 11, 16))
    issues = check_package(package)
    assert len(issues) == 1
    assert "ночью" in issues[0]  # только ночной прилёт, без «не совпадает»


def test_night_departure_to_airport():
    # вылет 04:00, трансфер 30 мин: выезжать нужно в 01:30
    package = _package(_msk(10, 15), _msk(15, 4), date(2026, 11, 10), date(2026, 11, 15))
    issues = check_package(package)
    assert len(issues) == 1
    assert "ночью" in issues[0]
    assert "01:30" in issues[0]


def test_departure_at_six_in_the_morning_is_not_night():
    # вылет 08:30, трансфер 30 мин: выезд ровно в 06:00
    package = _package(_msk(10, 15), _msk(15, 8, 30), date(2026, 11, 10), date(2026, 11, 15))
    assert check_package(package) == []


def test_long_wait_after_check_out():
    # выезд из номера в 12:00, в аэропорт выезжать в 17:30: ждать 5,5 ч
    package = _package(_msk(10, 15), _msk(15, 20), date(2026, 11, 10), date(2026, 11, 15))
    issues = check_package(package)
    assert len(issues) == 1
    assert "камера хранения" in issues[0]
    assert "5.5" in issues[0]


def test_wait_of_exactly_four_hours_is_fine():
    # в аэропорт выезжать в 16:00: ровно 4 ч после выезда из номера
    package = _package(_msk(10, 15), _msk(15, 18, 30), date(2026, 11, 10), date(2026, 11, 15))
    assert check_package(package) == []


def test_departure_without_transfer_uses_only_airport_margin():
    # без трансфера выезд в 14:00 при вылете в 16:00
    package = _package(
        _msk(10, 15), _msk(15, 16), date(2026, 11, 10), date(2026, 11, 15), transfer_min=None
    )
    assert check_package(package) == []
