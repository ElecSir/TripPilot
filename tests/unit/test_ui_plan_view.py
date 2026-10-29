"""Образец и отображение полей реального TripState в UI."""

import json
from pathlib import Path

import pytest

from tests.fakes import sample_package
from trip_pilot.domain.trip_state import TripState
from trip_pilot.ui.cart_view import cart_details_html
from trip_pilot.ui.checkout import breakdown_matches_total
from trip_pilot.ui.plan_view import (
    TIER_LABELS,
    assumption_label,
    flight_text,
    has_synthetic_offers,
    hotel_details,
    plan_assumptions,
    sources_text,
    transfer_text,
)

SAMPLE_PATH = Path(__file__).parents[2] / "src/trip_pilot/ui/sample_plan.json"


def test_sample_plan_validates_as_trip_state() -> None:
    payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    state = TripState.model_validate(payload)
    # Никакие старые поля не должны незаметно исчезать при валидации.
    assert state.model_dump(mode="json") == payload
    assert [package.tier for package in state.packages] == ["economy", "balance", "comfort"]
    assert state.places["moscow"] == "Москва"
    assert state.search is not None
    for package in state.packages:
        assert package.sources
        assert all(hit.source == "synthetic" for hit in package.sources)
        assert breakdown_matches_total(package.model_dump(mode="json")) is True
        assert package.hotel.is_synthetic
        assert package.outbound.is_synthetic
        assert package.inbound.is_synthetic
        assert package.nights == state.search.nights
        assert package.check_in == state.search.check_in
        assert package.check_out == state.search.check_out


def test_contract_package_renders_flights_transfer_and_hotel() -> None:
    package = sample_package().model_dump(mode="json")
    places = {"moscow": "Москва", "antalya": "Анталья"}
    outbound = flight_text(package["outbound"], places)
    inbound = flight_text(package["inbound"], places)
    assert "Москва → Анталья" in outbound
    assert "Анталья → Москва" in inbound
    assert "10.11 19:10" in outbound
    assert "(местное время)" in outbound
    assert "+0300" not in outbound
    assert "Пересадок: 1" in outbound
    assert "Демо Авиа" in outbound
    assert "багаж не включён" in outbound
    assert "уточняются" not in outbound
    transfer = transfer_text(package["transfer"])
    assert "Такси" in transfer
    assert "1 800 ₽ за машину в одну сторону" in transfer
    assert "мест: 4" in transfer
    assert "Всё включено" in hotel_details(package["hotel"])
    assert "Без бесплатной отмены" in hotel_details(package["hotel"])
    html = cart_details_html(package, {}, outbound, inbound)
    assert "Москва → Анталья" in html
    assert "Анталья → Москва" in html
    assert "Такси" in html
    assert "Всё включено" in html
    assert "Заезд 14:00, выезд 12:00" in html


def test_direct_train_preserves_each_local_time_and_unknown_slug() -> None:
    leg = sample_package().outbound.model_dump(mode="json")
    leg.update(
        mode="train", origin="unknown", destination="kazan", stops=0,
        depart_at="2030-11-10T22:00:00+03:00",
        arrive_at="2030-11-11T06:00:00+04:00", baggage_included=True,
    )
    text = flight_text(leg, {"kazan": "Казань"})
    assert "Поезд: unknown → Казань" in text
    assert "10.11 22:00 → 11.11 06:00 (местное время)" in text
    assert "+0300" not in text and "+0400" not in text
    assert "без пересадок" in text
    assert "багаж включён" in text


def test_nullable_transfer_and_shuttle() -> None:
    assert transfer_text(None) == "Трансфер не включён"
    package = sample_package().model_dump(mode="json")
    package["transfer"]["kind"] = "shuttle"
    package["transfer"]["price"] = "0"
    assert "Шаттл" in transfer_text(package["transfer"])
    assert "0 ₽" in transfer_text(package["transfer"])
    package["transfer"] = None
    assert "Трансфер не включён" in cart_details_html(package, {}, "туда", "обратно")


@pytest.mark.parametrize(("field", "value", "expected"), [
    ("origin", "kazan", "Город вылета: Казань"),
    ("destination", "sochi", "Направление: Сочи"),
    ("origin", "unknown", "Город вылета: unknown"),
    ("nights", "10", "10 ночей"),
    ("nights", "21", "21 ночь"),
    ("nights", "2", "2 ночи"),
    ("nights", "12", "12 ночей"),
    ("nights", "на неделю", "на неделю"),
    ("date_from", "2030-11-10", "10.11.2030"),
    ("party", "2 взрослых", "2 взрослых"),
    ("party.children_ages.0", "4", "Ребёнку №1: 4 года"),
    ("party.children_ages.1", "1", "Ребёнку №2: 1 год"),
    ("party.children_ages.0", "0", "Ребёнку №1: 0 лет"),
    ("party.children_ages.2", "11", "Ребёнку №3: 11 лет"),
    ("party.children_ages.0", "12", "Ребёнку №1: 12 лет"),
    ("party.children_ages.0", "2–6", "Ребёнку №1: 2–6"),
])
def test_assumption_uses_actual_value(field: str, value: str, expected: str) -> None:
    assert assumption_label({"field": field, "value": value}, {
        "kazan": "Казань", "sochi": "Сочи",
    }) == expected


def test_request_and_search_assumptions_are_combined() -> None:
    origin = {"field": "origin", "value": "kazan", "reason": "Город не указан"}
    nights = {"field": "nights", "value": "10", "reason": "Длительность не указана"}
    assert plan_assumptions({
        "request": {"assumptions": [origin]}, "search": {"assumptions": [nights]},
    }) == [origin, nights]
    assert plan_assumptions({"request": None, "search": None}) == []


def test_contract_tier_labels() -> None:
    assert TIER_LABELS == {"economy": "Эконом", "balance": "Баланс", "comfort": "Комфорт"}


def test_sources_keep_reference_order_headings_and_synthetic_label() -> None:
    package = {"sources": [
        {"title": "Анталья", "heading_path": "Анталья › С детьми", "source": "synthetic"},
        {"title": "Казань", "heading_path": "Транспорт", "source": "wikivoyage"},
        {"title": "Москва", "heading_path": None, "source": "wikivoyage"},
        {"title": "Сочи", "heading_path": "Сочи", "source": "wikivoyage"},
    ]}
    assert sources_text(package) == (
        "Источники: [S1] Анталья › С детьми (синтетика), "
        "[S2] Казань › Транспорт, [S3] Москва, [S4] Сочи"
    )
    assert sources_text({}) == ""
    assert sources_text({"sources": []}) == ""


@pytest.mark.parametrize("component", ["hotel", "outbound", "inbound"])
def test_synthetic_label_uses_offer_flags(component: str) -> None:
    assert has_synthetic_offers({"packages": [{component: {"is_synthetic": True}}]})
    assert not has_synthetic_offers({"packages": [{component: {"is_synthetic": False}}]})
    assert not has_synthetic_offers({"packages": [{}]})
    assert not has_synthetic_offers({})
