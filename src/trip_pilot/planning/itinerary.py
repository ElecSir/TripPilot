"""Минимальная проверка стыковок пакета: предупреждения понятным текстом. Зона: data."""

from datetime import date, datetime, time, timedelta

from trip_pilot.domain.offers import Package

LATE_ARRIVAL = time(23, 0)  # приезд в отель с этого времени считается поздним
NIGHT_END = time(6, 0)  # время с 00:00 до этого считается ночным (прилёт и выезд в аэропорт)
AIRPORT_BEFORE_DEPARTURE = timedelta(hours=2)  # в аэропорту быть за 2 ч до вылета
LONG_WAIT = timedelta(hours=4)  # дольше столько ждать между выездом из номера и дорогой


def check_package(package: Package) -> list[str]:
    """Предупреждения по стыковкам. Пустой список: замечаний нет.

    Все времена берутся в поясе самого рейса: прилёт в поясе направления,
    вылет в поясе пункта вылета. Так даты сравниваются в местном времени.
    """
    return [
        *_late_arrival(package),
        *_night_arrival(package),
        *_date_mismatch(package),
        *_departure_trip(package),
    ]


def _is_night(moment: datetime) -> bool:
    return moment.time() < NIGHT_END


def _late_arrival(package: Package) -> list[str]:
    arrive = package.outbound.arrive_at
    if _is_night(arrive):  # ночной прилёт разбирает _night_arrival
        return []
    minutes = package.transfer.duration_min if package.transfer else 0
    at_hotel = arrive + timedelta(minutes=minutes)
    if at_hotel.date() > arrive.date() or at_hotel.time() >= LATE_ARRIVAL:
        return [
            f"Поздний приезд в отель: около {at_hotel:%H:%M} по местному времени. "
            "Предупредите отель о позднем заселении."
        ]
    return []


def _night_arrival(package: Package) -> list[str]:
    arrive = package.outbound.arrive_at
    if not _is_night(arrive) or package.check_in != arrive.date():
        return []
    previous = package.check_in - timedelta(days=1)
    return [
        f"Прилёт ночью ({arrive:%d.%m %H:%M}), а отель забронирован только с "
        f"{package.check_in:%d.%m}: до {package.hotel.check_in_time:%H:%M} номера не будет. "
        f"Нужна ещё одна ночь, с {previous:%d.%m}."
    ]


def _date_matches(day: date, moment: datetime) -> bool:
    """Дата отеля совпадает с датой рейса; при ночном рейсе допустим предыдущий день."""
    if day == moment.date():
        return True
    return _is_night(moment) and day == moment.date() - timedelta(days=1)


def _date_mismatch(package: Package) -> list[str]:
    issues = []
    arrive = package.outbound.arrive_at
    depart = package.inbound.depart_at
    if not _date_matches(package.check_in, arrive):
        issues.append(
            f"Дата заезда в отель ({package.check_in:%d.%m}) не совпадает "
            f"с датой прилёта ({arrive:%d.%m}, местное время)."
        )
    if not _date_matches(package.check_out, depart):
        issues.append(
            f"Дата выезда из отеля ({package.check_out:%d.%m}) не совпадает "
            f"с датой вылета ({depart:%d.%m}, местное время)."
        )
    return issues


def _duration_text(delta: timedelta) -> str:
    """«5 ч 30 мин», а не «5.5 ч»: дробные часы с точкой читаются как опечатка."""
    hours, minutes = divmod(round(delta.total_seconds() / 60), 60)
    return f"{hours} ч {minutes} мин" if minutes else f"{hours} ч"


def _departure_trip(package: Package) -> list[str]:
    """Когда придётся выезжать в аэропорт: не ночью и без долгого ожидания после выезда."""
    depart = package.inbound.depart_at
    minutes = package.transfer.duration_min if package.transfer else 0
    leave = depart - AIRPORT_BEFORE_DEPARTURE - timedelta(minutes=minutes)
    issues = []
    if _is_night(leave):
        issues.append(f"Выезжать из отеля в аэропорт придётся ночью, в {leave:%H:%M}.")
    check_out_at = datetime.combine(
        package.check_out, package.hotel.check_out_time, tzinfo=depart.tzinfo
    )
    wait = leave - check_out_at
    if leave.date() == package.check_out and wait > LONG_WAIT:
        issues.append(
            f"Между выездом из номера ({check_out_at:%H:%M}) и дорогой в аэропорт "
            f"({leave:%H:%M}) около {_duration_text(wait)}: "
            "нужен поздний выезд или камера хранения."
        )
    return issues
