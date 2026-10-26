"""Корзина, Decimal и безопасное повторное оформление заказа."""

from decimal import Decimal
from uuid import UUID

import httpx
import pytest

from tests.fakes import sample_package
from trip_pilot.ui.checkout import (
    breakdown_matches_total,
    breakdown_rows,
    money,
    order_payload,
    pay_once,
    prepare_attempt,
)


@pytest.fixture
def package() -> dict:
    return {
        "id": "demo-comfort",
        "total": "137900.00",
        "price_breakdown": {"flight": "62000.00", "hotel": "66900.00", "transfer": "9000.00"},
    }


def test_breakdown_is_exact_decimal(package: dict) -> None:
    rows = breakdown_rows(package)
    assert rows == [
        ("Перелёты", Decimal("62000.00")),
        ("Проживание", Decimal("66900.00")),
        ("Трансфер", Decimal("9000.00")),
    ]
    assert breakdown_matches_total(package) is True
    assert money("1234.56") == "1 234,56 ₽"
    assert money("137900.00") == "137 900 ₽"


def test_every_breakdown_key_of_real_packages_has_russian_label() -> None:
    package = sample_package().model_dump(mode="json")
    assert [label for label, _ in breakdown_rows(package)] == [
        "Перелёт туда",
        "Перелёт обратно",
        "Проживание",
        "Трансфер",
    ]
    assert breakdown_matches_total(package) is True


def test_missing_or_invalid_breakdown_never_claims_match(package: dict) -> None:
    assert breakdown_matches_total({"total": "100"}) is None
    package["price_breakdown"]["transfer"] = "неизвестно"
    assert breakdown_matches_total(package) is None
    package["price_breakdown"]["transfer"] = "0"
    assert breakdown_matches_total(package) is False


def test_attempt_uuid_is_kept_for_same_package_and_session() -> None:
    first = prepare_attempt(None, "sid-1", "p-1")
    UUID(first["idempotency_key"])
    assert prepare_attempt(first, "sid-1", "p-1") is first
    assert prepare_attempt(first, "sid-1", "p-2")["idempotency_key"] != first[
        "idempotency_key"
    ]
    assert prepare_attempt(first, "sid-2", "p-1")["idempotency_key"] != first[
        "idempotency_key"
    ]


def test_demo_payment_creates_no_api_request_and_is_stable(package: dict) -> None:
    attempt = prepare_attempt(None, "sid-1", package["id"])
    first = pay_once(attempt, package, demo=True)
    second = pay_once(attempt, package, demo=True)
    assert first is second
    assert first["id"].startswith("TP-DEMO-")
    assert first["is_synthetic"] is True
    assert first["total"] == package["total"]
    assert attempt["status"] == "completed"


def test_double_click_does_not_submit_second_order(package: dict) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/api/orders"
        return httpx.Response(
            200,
            json={"id": "TP-2026-000123", "status": "paid", "total": "137900.00"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")
    attempt = prepare_attempt(None, "sid-1", package["id"])
    first = pay_once(attempt, package, demo=False, client=client)
    second = pay_once(attempt, package, demo=False, client=client)
    assert first == second
    assert len(requests) == 1
    assert order_payload(attempt) == {
        "session_id": "sid-1",
        "package_id": package["id"],
        "idempotency_key": attempt["idempotency_key"],
    }


def test_retry_uses_same_key_after_network_error(package: dict) -> None:
    keys = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        key = json.loads(request.content)["idempotency_key"]
        keys.append(key)
        if len(keys) == 1:
            raise httpx.ReadTimeout("сервер не ответил")
        return httpx.Response(
            200, json={"id": "TP-2026-000123", "status": "paid", "total": "137900.00"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")
    attempt = prepare_attempt(None, "sid-1", package["id"])
    with pytest.raises(httpx.ReadTimeout):
        pay_once(attempt, package, demo=False, client=client)
    assert attempt["status"] == "retry"
    pay_once(attempt, package, demo=False, client=client)
    assert len(keys) == 2
    assert keys[0] == keys[1] == attempt["idempotency_key"]
    assert attempt["status"] == "completed"


def test_duplicate_submitting_status_does_not_send_request(package: dict) -> None:
    attempt = prepare_attempt(None, "sid-1", package["id"])
    attempt["status"] = "submitting"
    assert pay_once(attempt, package, demo=False, client=None) is None


def test_non_successful_api_response_does_not_mark_paid(package: dict) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(503)), base_url="http://test"
    )
    attempt = prepare_attempt(None, "sid-1", package["id"])
    with pytest.raises(httpx.HTTPStatusError):
        pay_once(attempt, package, demo=False, client=client)
    assert attempt["status"] == "retry"
    assert attempt["order"] is None
