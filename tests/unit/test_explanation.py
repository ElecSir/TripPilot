"""Каждое объяснение подтверждается конкретным полем пакета или запроса."""

from decimal import Decimal

from tests.fakes import sample_package
from trip_pilot.domain.request import Party, TripRequest
from trip_pilot.services.explanation import explain


def test_explanation_uses_real_hotel_flights_transfer_and_issues_without_mutation():
    package = sample_package().model_copy(update={"issues": ["Позднее прибытие"]})
    before = package.model_dump()
    explained = explain(package, TripRequest(budget=Decimal("150000")))
    text = " ".join([*explained.why, *explained.tradeoffs, *explained.risks])
    assert "700 м" in text
    assert "Пересадок туда: 1" in text
    assert "Пересадок обратно: 1" in text
    assert "Позднее прибытие" in explained.risks
    assert "Без бесплатной отмены отеля" in explained.risks
    assert "Прямой" not in text
    assert "билетов" not in text  # данных о возвратности билетов нет в контракте
    assert "чем комфорт" not in text  # соседние пакеты не переданы в функцию
    assert package.model_dump() == before


def test_direct_legs_and_free_cancellation_are_not_inferred_from_tier():
    package = sample_package()
    out = package.outbound.model_copy(update={"stops": 0})
    hotel = package.hotel.model_copy(update={"free_cancellation": True})
    package = package.model_copy(update={"outbound": out, "hotel": hotel})
    explained = explain(package, TripRequest(must=["direct_only"]))
    text = " ".join(explained.why)
    assert "Прямой перелёт туда" in text and "6 ч 30 мин" in text
    assert "Прямой перелёт обратно" not in text
    assert "Бесплатная отмена отеля" in text
    assert any("без пересадок" in risk for risk in explained.risks)


def test_budget_difference_is_exact_decimal_and_nullable_transfer_is_honest():
    package = sample_package().model_copy(update={"total": Decimal("123456.78"), "transfer": None})
    explained = explain(package, TripRequest(budget=Decimal("100000")))
    assert "Превышение бюджета: 23 456,78 ₽" in explained.tradeoffs
    assert "Трансфер не включён" in explained.tradeoffs
    assert not any("в бюджете" in line.lower() for line in explained.why)


def test_children_and_pets_claims_require_every_relevant_component():
    package = sample_package()
    request = TripRequest(party=Party(children_ages=[5], pets=["dog"]))
    explained = explain(package, request)
    assert "Отель подходит для детей" in explained.why
    assert any("отель" in risk and "животных" in risk for risk in explained.risks)
    hotel = package.hotel.model_copy(update={"pets_allowed": True, "kids_friendly": False})
    transfer = package.transfer.model_copy(update={"pets_allowed": True})
    explained = explain(package.model_copy(update={"hotel": hotel, "transfer": transfer}), request)
    assert "Можно с животными во всех включённых компонентах" in explained.why
    assert any("детей" in risk for risk in explained.risks)


def test_beach_distance_and_synthetic_warning_are_conditional():
    package = sample_package()
    package = package.model_copy(
        update={
            "hotel": package.hotel.model_copy(
                update={"beach_distance_m": None, "is_synthetic": False}
            ),
            "outbound": package.outbound.model_copy(update={"is_synthetic": False}),
            "inbound": package.inbound.model_copy(update={"is_synthetic": False}),
        }
    )
    explained = explain(package, TripRequest())
    assert not any("пляжа" in line for line in explained.why)
    assert not any("Синтетические" in line for line in explained.risks)
    assert explain(explained, TripRequest()) == explained
