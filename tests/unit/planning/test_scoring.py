"""Скоринг пакета под запрос: вклады, их сумма и человеческие причины."""

from datetime import date
from decimal import Decimal

from tests.fakes import sample_package
from trip_pilot.domain.request import Party, TripRequest
from trip_pilot.planning.scoring import best_by_score, score

TODAY = date(2030, 11, 10)
SEA = TripRequest(tags=["sea"], budget=Decimal("150000"))


def package(**hotel):
    base = sample_package()
    hotel_fields = {"beach_distance_m": 300, "rating": 9.1, "stars": 4, "kids_friendly": True}
    hotel_fields.update(hotel)
    return base.model_copy(update={"hotel": base.hotel.model_copy(update=hotel_fields)})


def test_contributions_add_up_to_total():
    result = score(package(), SEA)
    assert abs(sum(item.score for item in result.contributions) - result.total) < 1e-9
    assert 0 <= result.total <= 1


def test_each_contribution_names_its_factor_and_weight():
    result = score(package(), SEA)
    factors = {item.factor: item for item in result.contributions}
    assert factors["rating"].reason == "рейтинг 9.1"
    assert factors["beach"].reason == "300 м до пляжа"
    assert factors["price"].weight == 0.35
    assert all(item.value >= 0 for item in result.contributions)


def test_factors_that_request_does_not_ask_are_not_counted():
    quiet = TripRequest()  # ни моря, ни детей, ни животных
    result = score(package(), quiet)
    factors = {item.factor for item in result.contributions}
    assert factors == {"price", "rating", "stops", "cancellation"}


def test_kids_and_pets_appear_only_for_such_request():
    request = TripRequest(tags=["sea"], party=Party(children_ages=[5], pets=["dog"]))
    factors = {item.factor for item in score(package(), request).contributions}
    assert {"kids", "pets"} <= factors


def test_hotel_for_kids_scores_higher_than_one_without_mark():
    request = TripRequest(party=Party(children_ages=[5]))
    friendly = score(package(kids_friendly=True), request).total
    neutral = score(package(kids_friendly=False), request).total
    assert friendly > neutral


def test_beach_value_falls_with_distance():
    near = score(package(beach_distance_m=100), SEA)
    far = score(package(beach_distance_m=1800), SEA)
    assert near.total > far.total
    beach = next(item for item in near.contributions if item.factor == "beach")
    assert beach.reason == "100 м до пляжа"


def test_reasons_use_only_short_facts():
    reasons = score(package(), SEA).reasons(limit=2)
    assert len(reasons) == 2
    assert all("₽" in r or "рейтинг" in r or "пляжа" in r for r in reasons)


def test_best_by_score_prefers_value_for_money():
    cheap = package(beach_distance_m=1500, rating=7.0).model_copy(
        update={
            "id": "cheap",
            "total": Decimal("90000"),
            "price_breakdown": {"hotel": Decimal("90000")},
        }
    )
    premium = package(beach_distance_m=200, rating=9.5).model_copy(
        update={
            "id": "premium",
            "total": Decimal("150000"),
            "price_breakdown": {"hotel": Decimal("150000")},
        }
    )
    chosen = best_by_score([cheap, premium], TripRequest(tags=["sea"]))
    assert chosen.id == "cheap"  # оценка на рубль важнее абсолютной оценки
