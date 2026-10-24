"""Минимальная проверка стыковок пакета: предупреждения понятным текстом. Зона: data."""

from datetime import date, datetime, time, timedelta

from trip_pilot.domain.offers import Package

LATE_ARRIVAL = time(23, 0)  # приезд в отель с этого времени считается поздним
NIGHT_END = time(6, 0)  # прилёт с 00:00 до этого времени считается ночным
AIRPORT_MARGIN = timedelta(hours=3)


def check_package(package: Package) -> list[str]:
    """Предупреждения по стыковкам. Пустой список: замечаний нет.

    Все времена берутся в поясе самого рейса: прилёт в поясе направления,
    вылет в поясе пункта вылета. Так даты сравниваются в местном времени.
    """
    return [
        *_late_arrival(package),
        *_night_arrival(package),
        *_date_mismatch(package),
        *_departure_margin(package),
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


def _departure_margin(package: Package) -> list[str]:
    depart = package.inbound.depart_at
    check_out_at = datetime.combine(
        package.check_out, package.hotel.check_out_time, tzinfo=depart.tzinfo
    )
    if depart < check_out_at + AIRPORT_MARGIN:
        return [
            f"Вылет в {depart:%H:%M} раньше, чем выезд из отеля ({check_out_at:%H:%M}) + 3 ч. "
            "Уточните время выезда и дорогу до аэропорта."
        ]
    return []
