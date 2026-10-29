"""Содержимое и безопасность разметки корзины."""

import pytest

from trip_pilot.ui.cart_view import (
    cart_details_html,
    cart_header_html,
    cart_prices_html,
    guests_text,
    travel_dates,
)


def test_cart_header_escapes_untrusted_tier() -> None:
    html = cart_header_html('<script>alert("x")</script>')
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert 'class="trip-basket-marker"' in html
    assert "Корзина" in html


def test_cart_details_group_trip_components_and_escape_content() -> None:
    package = {
        "hotel": {"name": "Тест & <отель>", "stars": 5},
        "check_in": "2026-11-14", "check_out": "2026-11-21", "nights": 7,
        "transfer": {"kind": "taxi", "duration_min": 35, "capacity": 4,
                     "price": "1800", "pets_allowed": True},
    }
    request = {"party": {"adults": 2, "children_ages": [5], "pets": ["dog"]}}
    html = cart_details_html(package, request, "Рейс <1>", "Рейс <2>")
    assert "14.11.2026 — 21.11.2026" in html
    assert "2" in html and "Детей: 1" in html and "Животных: 1" in html
    assert "Тест &amp; &lt;отель&gt;" in html
    assert "Такси · 35 мин · мест: 4 · 1 800 ₽ за машину в одну сторону" in html
    assert "Рейс &lt;1&gt;" in html
    assert "Рейс &lt;2&gt;" in html
    assert "<отель>" not in html
    assert "<transfer>" not in html
    assert 'class="trip-detail-stack"' in html
    assert "5★" in html


def test_compact_checkout_shows_hotels_and_costs_without_flights() -> None:
    package = {"hotel": {"name": "Отель"}, "transfer": None}
    html = cart_details_html(package, {}, "туда", "обратно", compact=True)
    assert "Отель" in html
    assert "Трансфер" in html
    assert "туда" not in html
    assert "обратно" not in html


def test_price_markup_contains_breakdown_and_full_total() -> None:
    package = {
        "price_breakdown": {"flights": "72000", "hotel": "87500", "transfer": "10000"},
        "total": "169500.00",
    }
    html = cart_prices_html(package)
    assert "Перелёты" in html
    assert "Проживание" in html
    assert "Трансфер" in html
    assert "72 000 ₽" in html
    assert "169 500 ₽" in html
    assert 'class="trip-price-total"' in html
    assert "За всех путешественников" in html


def test_unknown_breakdown_label_is_escaped() -> None:
    html = cart_prices_html({"total": "10", "price_breakdown": {"<x>": "10"}})
    assert "&lt;x&gt;" in html
    assert "<x>" not in html


def test_incomplete_plan_does_not_assume_dates_or_guests() -> None:
    assert travel_dates({}) == "Даты уточняются"
    assert guests_text({}) == "Взрослых: —"


@pytest.mark.parametrize("compact", [True, False])
def test_sources_follow_explanation_and_escape_untrusted_content(compact: bool) -> None:
    package = {
        "why": ["Подходит <семьям> [S1]"],
        "sources": [{"title": "<script>Анталья</script>", "heading_path": "С детьми & море",
                     "source": "synthetic"}],
    }
    html = cart_details_html(package, {}, "туда", "обратно", compact=compact)
    assert "Почему подходит" in html
    assert "Подходит &lt;семьям&gt; [S1]" in html
    assert "Источники: [S1] &lt;script&gt;Анталья&lt;/script&gt;" in html
    assert "С детьми &amp; море (синтетика)" in html
    assert html.index("Подходит") < html.index("Источники:")
    assert "<script>" not in html
    package["sources"] = []
    html = cart_details_html(package, {}, "туда", "обратно", compact=compact)
    assert "Источники:" not in html
    assert "Почему подходит" not in html
