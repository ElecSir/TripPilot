"""Корзина и идемпотентное оформление заказа через API."""

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

BREAKDOWN_LABELS = {
    "outbound": "Перелёт туда",
    "inbound": "Перелёт обратно",
    "flight": "Перелёты",
    "flights": "Перелёты",
    "hotel": "Проживание",
    "transfer": "Трансфер",
    "insurance": "Страховка",
    "taxes": "Налоги и сборы",
    "fees": "Сборы",
    "other": "Прочие расходы",
}


def money(value: object) -> str:
    """Форматирует Decimal в рублях без потери копеек."""
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            return "Цена уточняется"
    except (InvalidOperation, TypeError, ValueError):
        return "Цена уточняется"
    formatted = f"{amount:,.2f}".replace(",", " ")
    if formatted.endswith(".00"):
        formatted = formatted[:-3]
    else:
        formatted = formatted.replace(".", ",")
    return f"{formatted} ₽"


def breakdown_rows(package: dict[str, Any]) -> list[tuple[str, Decimal]]:
    """Читает только заявленные компоненты цены, неизвестные ключи не теряет."""
    breakdown = package.get("price_breakdown") or {}
    if not isinstance(breakdown, dict):
        return []
    rows = []
    for key, value in breakdown.items():
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if amount.is_finite():
            label = BREAKDOWN_LABELS.get(str(key), str(key).replace("_", " ").capitalize())
            rows.append((label, amount))
    return rows


def breakdown_matches_total(package: dict[str, Any]) -> bool | None:
    """None означает, что проверить сумму по исходным данным нельзя."""
    breakdown = package.get("price_breakdown")
    if not isinstance(breakdown, dict) or not breakdown:
        return None
    rows = breakdown_rows(package)
    if len(rows) != len(breakdown):
        return None
    try:
        total = Decimal(str(package["total"]))
    except (InvalidOperation, TypeError, KeyError, ValueError):
        return None
    if not total.is_finite():
        return None
    return sum((amount for _, amount in rows), Decimal("0")) == total


def prepare_attempt(
    previous: dict[str, Any] | None, session_id: str, package_id: str
) -> dict[str, Any]:
    """Повторное открытие/повтор оплаты сохраняют тот же ключ для пакета и сессии."""
    if (
        previous
        and previous.get("session_id") == session_id
        and previous.get("package_id") == package_id
    ):
        return previous
    return {
        "session_id": session_id,
        "package_id": package_id,
        "idempotency_key": str(uuid.uuid4()),
        "status": "ready",
        "order": None,
    }


def order_payload(attempt: dict[str, Any]) -> dict[str, str]:
    """Передаём API только поля из согласованного контракта."""
    return {
        "session_id": attempt["session_id"],
        "package_id": attempt["package_id"],
        "idempotency_key": attempt["idempotency_key"],
    }


def pay_once(
    attempt: dict[str, Any],
    package: dict[str, Any],
    *,
    demo: bool,
    client: httpx.Client | None = None,
) -> dict[str, Any] | None:
    """Не отправляет повторный POST при наличии заказа; после сбоя повторяет с тем же UUID."""
    if attempt.get("order") is not None:
        return attempt["order"]
    if attempt.get("status") == "submitting":
        return None

    attempt["status"] = "submitting"
    try:
        if demo:
            # Деморежим никогда не обращается к /api/orders.
            short_id = uuid.UUID(attempt["idempotency_key"]).hex[:12].upper()
            order = {
                "id": f"TP-DEMO-{short_id}",
                "status": "paid",
                "total": str(package["total"]),
                "is_synthetic": True,
                "source": "synthetic",
                "package_id": attempt["package_id"],
            }
        else:
            if client is None:
                raise ValueError("Не задан API-клиент для оформления заказа")
            response = client.post("/api/orders", json=order_payload(attempt))
            response.raise_for_status()
            order = response.json()
            if not isinstance(order, dict) or not order.get("id") or not order.get("status"):
                raise ValueError("API вернул некорректный ответ на оформление заказа")
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        # После сетевой ошибки неизвестно, успел ли сервер создать заказ.
        # Никогда не генерируем новый idempotency_key для повтора.
        attempt["status"] = "retry"
        raise

    attempt["order"] = order
    attempt["status"] = "completed"
    return order
