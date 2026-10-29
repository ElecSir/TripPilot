"""Общее форматирование контрактных полей для карточек и корзины."""

from datetime import date, datetime

from trip_pilot.ui.checkout import money

TIER_LABELS = {"economy": "Эконом", "balance": "Баланс", "comfort": "Комфорт"}
MEAL_LABELS = {"RO": "Без питания", "BB": "Завтрак", "HB": "Полупансион", "AI": "Всё включено"}


def place_name(slug: str, places: dict[str, str] | None = None) -> str:
    """Если имя отсутствует в плане, оставляем исходный slug."""
    return (places or {}).get(slug, slug)


def flight_text(flight: dict | None, places: dict[str, str] | None = None) -> str:
    """Показывает местное время каждого пункта без числового смещения."""
    if not flight:
        return "Данные о рейсе уточняются"
    try:
        departure = datetime.fromisoformat(flight["depart_at"])
        arrival = datetime.fromisoformat(flight["arrive_at"])
        origin = place_name(flight["origin"], places)
        destination = place_name(flight["destination"], places)
        mode = "Поезд" if flight.get("mode") == "train" else "Перелёт"
        stops = flight["stops"]
        route_type = "без пересадок" if stops == 0 else f"Пересадок: {stops}"
        baggage = "багаж включён" if flight.get("baggage_included") else "багаж не включён"
        return (
            f"{mode}: {origin} → {destination} · "
            f"{departure:%d.%m %H:%M} → {arrival:%d.%m %H:%M} (местное время) · "
            f"{route_type} · {flight.get('carrier', '—')} · {baggage}"
        )
    except (KeyError, TypeError, ValueError):
        return "Данные о рейсе уточняются"


def transfer_text(transfer: dict | None) -> str:
    """Цена трансфера по контракту дана за машину в одну сторону."""
    if transfer is None:
        return "Трансфер не включён"
    kind = {"taxi": "Такси", "shuttle": "Шаттл"}.get(transfer.get("kind"), "Трансфер")
    pets = "можно с животными" if transfer.get("pets_allowed") else "без животных"
    return (
        f"{kind} · {transfer.get('duration_min', '—')} мин · "
        f"мест: {transfer.get('capacity', '—')} · {money(transfer.get('price'))} "
        f"за машину в одну сторону · {pets}"
    )


def hotel_details(hotel: dict) -> str:
    """Условия отеля берём только из явно переданных полей."""
    parts = []
    if hotel.get("meal"):
        parts.append(MEAL_LABELS.get(hotel["meal"], hotel["meal"]))
    if "rating" in hotel:
        parts.append(f"Рейтинг: {hotel['rating']}/10")
    if "free_cancellation" in hotel:
        parts.append("Бесплатная отмена" if hotel["free_cancellation"] else "Без бесплатной отмены")
    if "pets_allowed" in hotel:
        parts.append("Можно с животными" if hotel["pets_allowed"] else "Без животных")
    if "kids_friendly" in hotel:
        parts.append("Подходит детям" if hotel["kids_friendly"] else "Не ориентирован на детей")
    if hotel.get("beach_distance_m") is not None:
        parts.append(f"До пляжа: {hotel['beach_distance_m']} м")
    if hotel.get("check_in_time") and hotel.get("check_out_time"):
        parts.append(f"Заезд {hotel['check_in_time'][:5]}, выезд {hotel['check_out_time'][:5]}")
    return " · ".join(parts)


def plan_assumptions(plan: dict) -> list[dict]:
    """Допущения запроса и поиска дополняют друг друга."""
    return (
        ((plan.get("request") or {}).get("assumptions") or [])
        + ((plan.get("search") or {}).get("assumptions") or [])
    )


def has_synthetic_offers(plan: dict) -> bool:
    """Метка демо сохраняется и после подключения настоящего API."""
    return any(
        (package.get(component) or {}).get("is_synthetic", False)
        for package in plan.get("packages") or []
        for component in ("hotel", "outbound", "inbound")
    )


def assumption_label(assumption: dict, places: dict[str, str] | None = None) -> str:
    """Подпись зависит от реального value, а не от примера запроса."""
    field = assumption.get("field", "")
    value = str(assumption.get("value", ""))
    if field.startswith("party.children_ages."):
        index = field.removeprefix("party.children_ages.")
        if index.isdigit():
            label = f"Ребёнку №{int(index) + 1}"
            if value.isdigit():
                age = int(value)
                suffix = "лет"
                if age % 10 == 1 and age % 100 != 11:
                    suffix = "год"
                elif age % 10 in (2, 3, 4) and age % 100 not in (12, 13, 14):
                    suffix = "года"
                return f"{label}: {value} {suffix}"
            return f"{label}: {value}"
    if field in ("origin", "destination"):
        label = "Город вылета" if field == "origin" else "Направление"
        return f"{label}: {place_name(value, places)}"
    if field == "nights" and value.isdigit():
        count = int(value)
        suffix = "ночей"
        if count % 10 == 1 and count % 100 != 11:
            suffix = "ночь"
        elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
            suffix = "ночи"
        return f"{value} {suffix}"
    if field == "date_from":
        try:
            return date.fromisoformat(value).strftime("%d.%m.%Y")
        except ValueError:
            return value
    return value


def sources_text(package: dict) -> str:
    """Номера источников соответствуют порядку ссылок [S1], [S2] в объяснении."""
    labels = []
    for index, hit in enumerate(package.get("sources") or [], start=1):
        title = hit["title"]
        heading = hit.get("heading_path")
        if heading and heading != title:
            title = heading if heading.startswith(f"{title} › ") else f"{title} › {heading}"
        synthetic = " (синтетика)" if hit.get("source") == "synthetic" else ""
        labels.append(f"[S{index}] {title}{synthetic}")
    return "Источники: " + ", ".join(labels) if labels else ""
