"""Тексты агента в MVP: короткие шаблоны. Только факты из запроса и пакетов, без выдуманных чисел.

Объяснения по каждому пакету (why, tradeoffs, risks) пишет ui в services/explanation.py.
"""

from datetime import date
from decimal import Decimal

from trip_pilot.domain.errors import (
    AmbiguousCity,
    BudgetTooLow,
    DatesInPast,
    DomainError,
    MissingSlot,
    NoResults,
    UnknownCity,
)
from trip_pilot.domain.offers import Destination, Package
from trip_pilot.domain.trip_state import Order, PendingQuestion, SearchWindow

MONTHS_NOMINATIVE = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
    7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}
MONTHS_GENITIVE = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}
TIERS = {"economy": "Эконом", "balance": "Баланс", "comfort": "Комфорт"}
NBSP = " "


def money(amount: Decimal) -> str:
    return f"{amount:,.0f}".replace(",", NBSP) + f"{NBSP}₽"


def day(d: date) -> str:
    return f"{d.day} {MONTHS_GENITIVE[d.month]}"


def period(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{start.day}–{end.day} {MONTHS_GENITIVE[end.month]}"
    return f"{day(start)} – {day(end)}"


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def destination_question(options: list[Destination]) -> PendingQuestion:
    return PendingQuestion(
        slot="destination",
        text="Куда поедем? Вот что подходит под ваш запрос:",
        options=[d.name for d in options],
    )


ORIGIN_SUGGESTIONS = ("moscow", "spb", "kazan")


def origin_question(catalog: list[Destination]) -> PendingQuestion:
    """Запасной вопрос о городе вылета, если уточнитель ui его не задал."""
    names = {d.slug: d.name for d in catalog}
    return PendingQuestion(
        slot="origin",
        text="Откуда полетите?",
        options=[names[s] for s in ORIGIN_SUGGESTIONS if s in names],
    )


def when_question(today: date) -> PendingQuestion:
    """Запасной вопрос о времени поездки, если уточнитель ui его не задал."""
    months = [(today.month + i - 1) % 12 + 1 for i in range(1, 4)]
    return PendingQuestion(
        slot="when",
        text="Когда планируете поездку?",
        options=[MONTHS_NOMINATIVE[m] for m in months],
    )


def error_text(error: DomainError, names: dict[str, str]) -> str:
    match error:
        case UnknownCity(raw=raw):
            return f"Не знаю город «{raw}». Напишите иначе, например «Сочи» или «Анталья»."
        case AmbiguousCity(raw=raw, candidates=candidates):
            variants = ", ".join(names.get(c, c) for c in candidates)
            return f"«{raw}» — это {variants}? Уточните, пожалуйста."
        case DatesInPast(start=start):
            return f"{day(start).capitalize()} уже прошло. Когда планируете поездку?"
        case MissingSlot():
            return "Не хватает данных для поиска. Откуда и когда планируете поездку?"
        case NoResults(reason=reason):
            return (
                f"Под эти условия ничего не нашлось: {reason}. "
                "Попробуйте другие даты, бюджет или направление."
            )
        case BudgetTooLow(budget=budget, min_total=min_total):
            return (
                f"В бюджет {money(budget)} не укладываемся: самый дешёвый вариант — "
                f"{money(min_total)}. Увеличим бюджет или поменяем даты?"
            )
    return "Не получилось обработать запрос. Попробуйте сформулировать иначе."


def plan_summary(
    origin: str, destination: str, window: SearchWindow, packages: list[Package]
) -> str:
    totals = [p.total for p in packages]
    found = f"{len(packages)} {plural(len(packages), 'вариант', 'варианта', 'вариантов')}"
    prices = money(min(totals)) if len(set(totals)) == 1 else (
        f"от {money(min(totals))} до {money(max(totals))}"
    )
    return (
        f"Нашёл {found}: {origin} → {destination}, {period(window.check_in, window.check_out)}, "
        f"{prices}. Сравнение — в панели справа. Выберите пакет или напишите, что поменять."
    )


def nothing_changed() -> str:
    return "План выше. Выберите пакет или напишите, что поменять: даты, бюджет, состав."


def package_selected(package: Package) -> str:
    return (
        f"Выбран пакет «{TIERS[package.tier]}»: {package.hotel.name}, "
        f"{period(package.check_in, package.check_out)}, итого {money(package.total)}. "
        "Оформляем? Нажмите «Оформить»."
    )


def unknown_package() -> str:
    return "Такого варианта нет в текущем плане. Обновите страницу и выберите снова."


def already_ordered(order: Order) -> str:
    return (
        f"Заказ {order.id} уже оформлен на {money(order.total)}. "
        "Изменения после покупки появятся позже."
    )


def search_steps(origin: str, destination: str, window: SearchWindow) -> list[str]:
    return [
        f"Ищу перелёты {origin} → {destination} на {day(window.check_in)}",
        f"Ищу обратные перелёты на {day(window.check_out)}",
        f"Ищу отели: {destination}, {period(window.check_in, window.check_out)}",
    ]


def source_failed(name: str) -> str:
    return f"Источник «{name}» не ответил, продолжаю без него"
