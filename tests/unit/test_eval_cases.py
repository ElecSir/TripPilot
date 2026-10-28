"""Кейсы оценки разбора: формат, полнота таблицы PR #13 и совпадение с правилами.

Файл `evals/cases/parse.yaml` — данные для прогона оценки (его делает rag). Этот тест
не заменяет прогон, а держит кейсы честными: правила обязаны давать ровно то, что записано.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from returns.result import Success

from trip_pilot.agent.intent import parse_change, parse_request
from trip_pilot.domain.offers import Destination
from trip_pilot.domain.request import Party, TripRequest

ROOT = Path(__file__).parents[2]
CASES_PATH = ROOT / "evals" / "cases" / "parse.yaml"
# CI гоняет тесты в dev-образе, а `COPY evals ./evals` добавляет rag своим PR
# (задача 5 в tasks/rag.md). Пока папки нет в образе — кейсы проверяем локально.
if not CASES_PATH.exists():
    pytest.skip("кейсов нет в образе: COPY evals делает rag", allow_module_level=True)
CASES = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
CATALOG = [
    Destination.model_validate(row)
    for row in json.loads(
        (ROOT / "data" / "reference" / "destinations.json").read_text(encoding="utf-8")
    )
]
# Поля состава живут в Party, остальные — в самом запросе.
PARTY_FIELDS = {"adults", "children_ages", "pets"}
# Фразы из таблицы PR #13: каждая обязана быть среди кейсов.
PR13 = (
    "в Турцию",
    "во Вьетнам",
    "в начале декабря",
    "в конце ноября",
    "в бюджете 100к",
    "в Шарм",
    "на Пхукет",
    "15 марта",
    "с 3 по 10 января",
    "с 5 до 12 декабря",
    "на один день позже",
    "на две недели",
    "на пять дней",
    "подешевле",
    "дешевле",
)


def request_from(values: dict) -> TripRequest:
    fields: dict = {key: value for key, value in values.items() if key not in PARTY_FIELDS}
    if "date_from" in fields:
        fields["date_from"] = date.fromisoformat(str(fields["date_from"]))
    if "budget" in fields:
        fields["budget"] = Decimal(str(fields["budget"]))
    party = {key: values[key] for key in PARTY_FIELDS if key in values}
    if party:
        fields["party"] = Party(**party)
    return TripRequest(**fields)


def parsed(case: dict) -> TripRequest:
    today = date.fromisoformat(case["today"])
    if "base" in case:
        base = request_from(case["base"])
        patch = parse_change(case["text"], base, today=today)
        assert patch, f"изменение не разобрано: {case['text']}"
        return TripRequest.model_validate(base.model_dump() | patch)
    result = parse_request(case["text"], catalog=CATALOG, today=today)
    assert isinstance(result, Success), f"не разобрано: {case['text']}: {result}"
    return result.unwrap()


def matches(actual: object, expected: object) -> bool:
    if isinstance(actual, Decimal):
        return actual == Decimal(str(expected))
    if isinstance(actual, date):
        return actual == date.fromisoformat(str(expected))
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(
            matches(item, want) for item, want in zip(actual, expected, strict=True)
        )
    return actual == expected


def test_cases_file_is_complete():
    assert len(CASES) >= 60, "нужно не меньше 60 кейсов"
    for case in CASES:
        assert case["text"].strip(), case
        assert case["today"], case
        assert case["expect"], f"пустой expect: {case['text']}"


def test_all_pr13_phrases_are_covered():
    texts = " | ".join(case["text"] for case in CASES)
    missing = [phrase for phrase in PR13 if phrase not in texts]
    assert not missing, f"нет кейсов для фраз PR #13: {missing}"


@pytest.mark.parametrize("case", CASES, ids=[case["text"] for case in CASES])
def test_rules_reproduce_every_expected_field(case):
    request = parsed(case)
    for field, expected in case["expect"].items():
        holder = request.party if field in PARTY_FIELDS else request
        actual = getattr(holder, field)
        assert matches(actual, expected), (
            f"{case['text']}: {field} = {actual!r}, ждали {expected!r}"
        )
