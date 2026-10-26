"""Таблица фраз задачи 4 и изменения уже собранного запроса."""

from datetime import date
from decimal import Decimal

import pytest
from returns.result import Failure, Success

from tests.fakes import DESTINATIONS
from trip_pilot.agent.intent import parse_change, parse_request, resolve_city
from trip_pilot.domain.errors import AmbiguousCity, DatesInPast, NoResults, UnknownCity
from trip_pilot.domain.request import Assumption, Party, TripRequest

TODAY = date(2026, 10, 25)
CATALOG = [
    *DESTINATIONS,
    *[
        DESTINATIONS[0].model_copy(update={"slug": slug, "name": name, "iata": None})
        for slug, name in [("spb", "Санкт-Петербург"), ("kazan", "Казань")]
    ],
]

# Сначала примеры и ожидаемые поля, затем реализация. Месяц не превращаем в дату поиска.
PHRASES = [
    ("в ноябре", {"month": 11, "date_from": None}),
    ("в декабре", {"month": 12}),
    ("в январе", {"month": 1}),
    ("в феврале", {"month": 2}),
    ("в марте", {"month": 3}),
    ("в апреле", {"month": 4}),
    ("в мае", {"month": 5}),
    ("в июне", {"month": 6}),
    ("в июле", {"month": 7}),
    ("в августе", {"month": 8}),
    ("в сентябре", {"month": 9}),
    ("в октябре", {"month": 10}),
    ("на майские", {"month": 5, "date_from": None}),
    ("с 5 по 12 декабря", {"date_from": date(2026, 12, 5), "nights": 7}),
    ("с 28 декабря по 4 января", {"date_from": date(2026, 12, 28), "nights": 7}),
    ("с 5 по 12 декабря 2027", {"date_from": date(2027, 12, 5), "nights": 7}),
    ("5 ноября", {"date_from": date(2026, 11, 5)}),
    ("2026-11-14", {"date_from": date(2026, 11, 14)}),
    ("14.11.2026", {"date_from": date(2026, 11, 14)}),
    ("через две недели", {"date_from": date(2026, 11, 8)}),
    ("через 3 дня", {"date_from": date(2026, 10, 28)}),
    ("завтра", {"date_from": date(2026, 10, 26)}),
    ("на неделю", {"nights": 7}),
    ("на выходные", {"nights": 2}),
    ("на 10 дней", {"nights": 10}),
    ("на 3 ночи", {"nights": 3}),
    ("из Москвы", {"origin": "moscow"}),
    ("из Питера", {"origin": "spb"}),
    ("из СПб", {"origin": "spb"}),
    ("из Масквы", {"origin": "moscow"}),
    ("из Казани", {"origin": "kazan"}),
    ("из Санкт-Петербурга", {"origin": "spb"}),
    ("в Сочи", {"destination": "sochi"}),
    ("в Анталью", {"destination": "antalya"}),
    ("из Москвы в Сочи", {"origin": "moscow", "destination": "sochi"}),
    ("вдвоём", {"party.adults": 2}),
    ("втроём", {"party.adults": 3}),
    ("одна", {"party.adults": 1}),
    ("один", {"party.adults": 1}),
    ("с мужем", {"party.adults": 2}),
    ("3 взрослых", {"party.adults": 3}),
    ("с ребёнком 5 лет", {"party.children_ages": [5]}),
    ("с детьми 5 и 8 лет", {"party.children_ages": [5, 8]}),
    ("с ребёнком", {"party.children_ages": [None]}),
    ("с детьми", {"party.children_ages": [None]}),
    ("с собакой", {"party.pets": ["dog"], "must": ["pets_allowed"]}),
    ("с котом", {"party.pets": ["cat"], "must": ["pets_allowed"]}),
    ("с собакой и котом", {"party.pets": ["dog", "cat"], "must": ["pets_allowed"]}),
    ("до 150 000", {"budget": Decimal("150000")}),
    ("150к", {"budget": Decimal("150000")}),
    ("тысяч 100", {"budget": Decimal("100000")}),
    ("бюджет 100 тысяч", {"budget": Decimal("100000")}),
    ("до 150,5к", {"budget": Decimal("150500")}),
    ("бюджет 120000 рублей", {"budget": Decimal("120000")}),
    ("недорого", {"budget": None}),
    ("к тёплому морю", {"tags": ["sea", "warm"]}),
    ("хочу в город", {"tags": ["city"]}),
    ("хочу в горы", {"tags": ["nature"]}),
    ("без пересадок", {"must": ["direct_only"]}),
    ("отель для детей", {"must": ["kids_friendly"]}),
    (
        "из Питера в Сочи в ноябре на неделю вдвоём до 150к",
        {
            "origin": "spb",
            "destination": "sochi",
            "month": 11,
            "nights": 7,
            "party.adults": 2,
            "budget": Decimal("150000"),
        },
    ),
]


def field_value(value, path):
    for part in path.split("."):
        value = getattr(value, part)
    return value


@pytest.mark.parametrize(("text", "expected"), PHRASES, ids=[text for text, _ in PHRASES])
def test_request_phrase_table(text, expected):
    result = parse_request(text, catalog=CATALOG, today=TODAY)
    assert isinstance(result, Success), result
    request = result.unwrap()
    for path, value in expected.items():
        assert field_value(request, path) == value


@pytest.mark.parametrize("text", ["2026-10-24", "24.10.2026", "5 января 2026"])
def test_past_dates_return_domain_error(text):
    result = parse_request(text, catalog=CATALOG, today=TODAY)
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), DatesInPast)


@pytest.mark.parametrize("text", ["31 ноября", "на 0 ночей", "на 31 день", "бюджет 0"])
def test_invalid_input_returns_failure_instead_of_exception(text):
    result = parse_request(text, catalog=CATALOG, today=TODAY)
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), NoResults)


def test_unknown_and_ambiguous_city_and_catalog_only_aliases():
    assert isinstance(resolve_city("Урюпинск", CATALOG).failure(), UnknownCity)
    duplicate = CATALOG[0].model_copy(update={"slug": "other-moscow"})
    assert isinstance(resolve_city("Москва", [CATALOG[0], duplicate]).failure(), AmbiguousCity)
    assert isinstance(resolve_city("Питер", DESTINATIONS).failure(), UnknownCity)
    assert isinstance(parse_request("из Урюпинска", catalog=CATALOG, today=TODAY), Failure)


def test_base_is_preserved_without_mutation_and_explicit_values_replace_assumptions():
    base = TripRequest(
        origin="moscow",
        date_from=date(2026, 11, 7),
        nights=7,
        budget=150000,
        party=Party(adults=3, children_ages=[8]),
        tags=["sea"],
        must=["direct_only"],
        assumptions=[Assumption(field="budget", value="150000", reason="пример")],
    )
    before = base.model_dump()
    updated = parse_request(
        "в декабре до 100к с собакой", catalog=CATALOG, today=TODAY, base=base
    ).unwrap()
    assert updated.month == 12 and updated.date_from is None
    assert updated.origin == "moscow" and updated.nights == 7
    assert updated.budget == Decimal(100000)
    assert updated.party == Party(adults=3, children_ages=[8], pets=["dog"])
    assert updated.must == ["direct_only", "pets_allowed"]
    assert updated.assumptions == []
    assert base.model_dump() == before


def test_default_party_and_qualitative_budget_are_transparent():
    request = parse_request("недорого в ноябре", catalog=CATALOG, today=TODAY).unwrap()
    assert {item.field for item in request.assumptions} == {"party", "budget"}
    assert request.budget is None
    assert request.date_from is None and request.nights is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("на два дня позже", {"date_from": date(2026, 11, 9)}),
        ("на 3 дня раньше", {"date_from": date(2026, 11, 4)}),
        ("бюджет меньше", {"budget": Decimal("120000.00")}),
        ("до 100к", {"budget": Decimal("100000")}),
        ("без пересадок", {"must": ["kids_friendly", "direct_only"]}),
        ("с нами едет собака", {"party": Party(adults=3, children_ages=[5], pets=["dog"])}),
        ("а в декабре?", {"month": 12, "date_from": None}),
    ],
)
def test_change_patch_uses_current_values(text, expected):
    current = TripRequest(
        date_from=date(2026, 11, 7),
        nights=7,
        budget=150000,
        party=Party(adults=3, children_ages=[5]),
        must=["kids_friendly"],
    )
    before = current.model_dump()
    patch = parse_change(text, current, today=TODAY)
    assert patch is not None
    updated = TripRequest.model_validate(current.model_dump() | patch)
    for path, value in expected.items():
        assert field_value(updated, path) == value
    assert current.model_dump() == before
    if text == "бюджет меньше":
        assert any(item.field == "budget" and item.reason for item in updated.assumptions)


def test_unrelated_or_inapplicable_change_returns_none():
    for text in ["спасибо", "привет", "на два дня позже", "бюджет меньше"]:
        assert parse_change(text, TripRequest(), today=TODAY) is None


def test_request_is_deterministic_and_no_defaults_accumulate():
    first = parse_request("в ноябре", catalog=CATALOG, today=TODAY).unwrap()
    second = parse_request("в ноябре", catalog=CATALOG, today=TODAY, base=first).unwrap()
    assert first == second


def test_partial_party_updates_preserve_adult_assumption_until_explicit_answer():
    first = parse_request("в ноябре", catalog=CATALOG, today=TODAY).unwrap()
    with_pet = parse_request("с собакой", catalog=CATALOG, today=TODAY, base=first).unwrap()
    assert with_pet.assumptions == first.assumptions
    explicit = parse_request("вдвоём", catalog=CATALOG, today=TODAY, base=with_pet).unwrap()
    assert not any(item.field == "party" for item in explicit.assumptions)


def test_pet_removal_is_specific_and_relative_pronoun_is_not_a_cat():
    base = TripRequest(party=Party(pets=["cat", "dog"]), must=["pets_allowed", "direct_only"])
    updated = parse_request("без кота", catalog=CATALOG, today=TODAY, base=base).unwrap()
    assert updated.party.pets == ["dog"] and "pets_allowed" in updated.must
    updated = parse_request("без животных", catalog=CATALOG, today=TODAY, base=base).unwrap()
    assert updated.party.pets == [] and updated.must == ["direct_only"]
    updated = parse_request("отель который подходит", catalog=CATALOG, today=TODAY).unwrap()
    assert updated.party.pets == []


def test_child_age_range_is_not_taken_as_exact_age_or_budget():
    request = parse_request("с ребёнком до 2 лет", catalog=CATALOG, today=TODAY).unwrap()
    assert request.party.children_ages == [None]
    assert request.budget is None


def test_mixed_city_change_is_left_for_parser_with_catalog():
    current = TripRequest(destination="antalya", budget=200000, month=11)
    assert parse_change("в Сочи до 150к", current, today=TODAY) is None
    updated = parse_request("в Сочи до 150к", catalog=CATALOG, today=TODAY, base=current).unwrap()
    assert updated.destination == "sochi" and updated.budget == Decimal(150000)


def test_non_month_words_with_ma_prefix_do_not_crash_date_parser():
    request = parse_request("нужно 5 маленьких чемоданов", catalog=CATALOG, today=TODAY).unwrap()
    assert request.month is None and request.date_from is None


def test_child_count_and_old_age_assumptions_are_handled_explicitly():
    request = parse_request("с двумя детьми", catalog=CATALOG, today=TODAY).unwrap()
    assert request.party.children_ages == [None, None]
    request = parse_request("с детьми", catalog=CATALOG, today=TODAY).unwrap()
    assert any(item.field == "party.children_count" for item in request.assumptions)
    request.assumptions.append(
        Assumption(
            field="party.children_ages.0",
            value="4",
            reason="диапазон",
        )
    )
    updated = parse_request(
        "с детьми 5 и 8 лет", catalog=CATALOG, today=TODAY, base=request
    ).unwrap()
    assert updated.party.children_ages == [5, 8]
    assert [item.field for item in updated.assumptions] == ["party"]
