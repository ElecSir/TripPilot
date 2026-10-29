"""Безопасная HTML-разметка корзины на основе данных выбранного пакета."""

from datetime import date
from html import escape

from trip_pilot.ui.checkout import breakdown_rows, money
from trip_pilot.ui.plan_view import hotel_details, sources_text, transfer_text


def _html(value: object) -> str:
    """Экранирует значения каталога перед включением в разметку."""
    return escape(str(value), quote=True)


def travel_dates(package: dict) -> str:
    """Форматирует даты заезда и выезда, не додумывая отсутствующие значения."""
    dates = []
    for key in ("check_in", "check_out"):
        raw = package.get(key)
        if not raw:
            continue
        try:
            dates.append(date.fromisoformat(str(raw)).strftime("%d.%m.%Y"))
        except ValueError:
            dates.append(str(raw))
    return " — ".join(dates) if dates else "Даты уточняются"


def guests_text(request: dict) -> str:
    """Показывает состав поездки без предположений о возрасте и количестве гостей."""
    party = request.get("party") or {}
    parts = [f"Взрослых: {party.get('adults', '—')}"]
    children = party.get("children_ages") or []
    if children:
        parts.append(f"Детей: {len(children)}")
    pets = party.get("pets") or []
    if pets:
        parts.append(f"Животных: {len(pets)}")
    return " · ".join(parts)


def _detail(icon: str, label: str, content: str, caption: str = "") -> str:
    """Один пункт состава пакета с названием и подписью."""
    meta = f'<div class="trip-detail-meta">{caption}</div>' if caption else ""
    return (
        '<div class="trip-detail-item">'
        f'<span class="trip-detail-icon" aria-hidden="true">{icon}</span>'
        '<div class="trip-detail-body">'
        f'<div class="trip-detail-label">{label}</div>'
        f'<div class="trip-detail-value">{content}</div>{meta}'
        "</div></div>"
    )


def cart_details_html(package: dict, request: dict, outbound: str, inbound: str, *,
                      compact: bool = False) -> str:
    """Состав поездки; текст рейсов передаётся из UI и экранируется."""
    hotel = package.get("hotel") or {}
    stars = hotel.get("stars")
    hotel_name = _html(hotel.get("name") or "Отель уточняется")
    if stars is not None:
        hotel_name += f' <span class="trip-hotel-stars">· {_html(stars)}★</span>'
    transfer_label = transfer_text(package.get("transfer"))
    meta = f"{travel_dates(package)} · {package.get('nights', '—')} ночей"
    conditions = hotel_details(hotel)
    if conditions:
        meta += f" · {conditions}"
    parts = [
        '<div class="trip-basket-section-label">Состав поездки</div>',
        '<div class="trip-detail-stack">',
        _detail("🏨", "Отель", hotel_name, _html(meta)),
        _detail("👥", "Путешественники", _html(guests_text(request))),
    ]
    if not compact:
        parts.extend([
            _detail("✈️", "Перелёт туда", _html(outbound)),
            _detail("🛬", "Перелёт обратно", _html(inbound)),
        ])
    parts.append(_detail("🚐", "Трансфер", _html(transfer_label)))
    parts.append("</div>")
    if sources := sources_text(package):
        why = "".join(f"<li>{_html(point)}</li>" for point in package.get("why") or [])
        if why:
            parts.append(f'<div class="trip-detail-label">Почему подходит</div><ul>{why}</ul>')
        parts.append(f'<div class="trip-detail-meta">{_html(sources)}</div>')
    return "".join(parts)


def cart_prices_html(package: dict) -> str:
    """Детализация стоимости без вычисления цены из интерфейса."""
    rows = breakdown_rows(package)
    parts = [
        '<div class="trip-prices-panel">',
        '<div class="trip-basket-section-label">Стоимость поездки</div>',
    ]
    if rows:
        for label, amount in rows:
            parts.append(
                '<div class="trip-price-row">'
                f'<span>{_html(label)}</span><span>{_html(money(amount))}</span>'
                "</div>"
            )
    else:
        parts.append('<p class="trip-price-muted">Разбивка стоимости пока недоступна.</p>')
    parts.extend([
        '<div class="trip-price-total">',
        '<span>Итого</span>',
        f'<strong>{_html(money(package.get("total")))}</strong>',
        "</div>",
        '<div class="trip-price-caption">За всех путешественников</div>',
        "</div>",
    ])
    return "".join(parts)


def cart_header_html(tier: str) -> str:
    """Шапка корзины для отдельной панели с границами."""
    return (
        '<div class="trip-basket-marker">'
        '<div class="trip-basket-heading">'
        '<div class="trip-basket-kicker">Выбранный вариант</div>'
        '<h3>🛒 Корзина</h3>'
        f'<div class="trip-basket-subtitle">Пакет «{_html(tier)}»</div>'
        "</div>"
        '<span class="trip-basket-selected">Выбран</span>'
        "</div>"
    )
