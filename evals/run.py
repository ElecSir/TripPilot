"""Оценка качества разбора запросов и поиска по базе знаний.

Запуск из корня проекта:
    python -m evals.run
"""

import argparse
import asyncio
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import yaml
from returns.result import Failure, Success
from sqlalchemy import select

from trip_pilot.adapters.db.engine import create_engine, create_session_factory
from trip_pilot.adapters.db.reference import Destination as DestinationRow
from trip_pilot.adapters.llm.openai_compat import make_llm
from trip_pilot.agent.intent import parse_change, parse_request
from trip_pilot.agent.understand import understand
from trip_pilot.config import get_settings
from trip_pilot.domain.offers import Destination
from trip_pilot.domain.request import TripRequest
from trip_pilot.domain.trip_state import TripState
from trip_pilot.rag import retriever
from trip_pilot.rag.retriever import search

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "evals" / "cases"
TOP_K = 5


def load_yaml(path: Path) -> list[dict]:
    """Загрузить YAML-файл со списком тестовых случаев."""
    with path.open(encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not isinstance(data, list):
        raise ValueError(f"{path}: ожидался YAML-список")

    return data


def expected_value(request: TripRequest, field: str):
    """Получить поле из TripRequest, в том числе вложенные поля Party."""
    if field == "adults":
        return request.party.adults
    if field == "children_ages":
        return request.party.children_ages
    if field == "pets":
        return request.party.pets
    if field == "budget":
        return request.budget
    return getattr(request, field)


def normalize_value(value):
    """Привести даты и Decimal к строкам для сопоставления с YAML."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    if value is None:
        return None
    return str(value) if value.__class__.__name__ == "Decimal" else value


def check_expected(request: TripRequest, expected: dict) -> list[str]:
    """Вернуть список несовпадений с ожидаемыми полями."""
    errors = []

    for field, expected_item in expected.items():
        actual = normalize_value(expected_value(request, field))
        wanted = normalize_value(expected_item)
        if field == "budget" and actual is not None and wanted is not None:
            # «150500» и «150500.0» — одна сумма: деньги сравниваются как Decimal.
            actual, wanted = Decimal(str(actual)), Decimal(str(wanted))

        if actual != wanted:
            errors.append(f"{field}: ожидалось {wanted!r}, получено {actual!r}")

    return errors


async def evaluate_parse(catalog: list[Destination]) -> tuple[int, int, list[str]]:
    """Проверить rule-based разбор по evals/cases/parse.yaml."""
    cases = load_yaml(CASES_DIR / "parse.yaml")
    passed = 0
    errors = []

    for number, case in enumerate(cases, start=1):
        today = date.fromisoformat(str(case["today"]))
        base = TripRequest.model_validate(case["base"]) if case.get("base") else None

        # Как в оркестраторе: сначала изменение прошлого запроса, затем полный разбор.
        patch = parse_change(case["text"], base, today=today) if base is not None else None
        if patch:
            result = Success(TripRequest.model_validate(base.model_dump() | patch))
        else:
            result = parse_request(
                case["text"],
                catalog=catalog,
                today=today,
                base=base,
            )

        if isinstance(result, Failure):
            errors.append(f"[parse #{number}] {case['text']!r}: {result.failure()}")
            continue

        mismatches = check_expected(result.unwrap(), case["expect"])
        if mismatches:
            errors.append(
                f"[parse #{number}] {case['text']!r}: " + "; ".join(mismatches)
            )
        else:
            passed += 1

    return passed, len(cases), errors


async def evaluate_understand(
    catalog: list[Destination],
    llm,
    *,
    limit: int | None = None,
    pause: float = 0.0,
) -> tuple[int, int, list[str]]:
    """Дополнительная проверка LLM-разбора; запускается при наличии API-ключа.

    `limit` — сколько кейсов взять равномерно по набору, `pause` — секунд между запросами:
    у бесплатных моделей OpenRouter лимит 20 запросов в минуту и 50 в день.
    """
    cases = list(enumerate(load_yaml(CASES_DIR / "parse.yaml"), start=1))
    if limit is not None and limit < len(cases):
        cases = cases[:: max(1, len(cases) // limit)][:limit]
    passed = 0
    errors = []

    for index, (number, case) in enumerate(cases):
        if index and pause:
            await asyncio.sleep(pause)
        today = date.fromisoformat(str(case["today"]))
        base = TripRequest.model_validate(case["base"]) if case.get("base") else None
        state = TripState(session_id=uuid4(), request=base)

        try:
            result = await understand(
                case["text"],
                state,
                catalog=catalog,
                today=today,
                llm=llm,
            )
        except Exception as error:
            errors.append(f"[understand #{number}] {case['text']!r}: {error}")
            continue

        # None означает, что LLM предлагает разобрать запрос правилами.
        # Такой случай не считаем успешным LLM-разбором.
        if result is None:
            errors.append(
                f"[understand #{number}] {case['text']!r}: LLM вернула None"
            )
            continue

        if isinstance(result, Failure):
            errors.append(
                f"[understand #{number}] {case['text']!r}: {result.failure()}"
            )
            continue

        mismatches = check_expected(result.unwrap(), case["expect"])
        if mismatches:
            errors.append(
                f"[understand #{number}] {case['text']!r}: "
                + "; ".join(mismatches)
            )
        else:
            passed += 1

    return passed, len(cases), errors


def retrieval_metrics(results: list[list], cases: list[dict]) -> dict[str, float]:
    """Recall@5 и MRR по ожидаемому заголовку раздела."""
    hits = 0
    reciprocal_ranks = []

    for retrieved, case in zip(results, cases, strict=True):
        expected = case["expected_section"].casefold()
        rank = next(
            (
                position
                for position, item in enumerate(retrieved, start=1)
                if expected in (item.chunk.heading_path or "").casefold()
            ),
            None,
        )

        if rank is not None:
            hits += 1
            reciprocal_ranks.append(1 / rank)
        else:
            reciprocal_ranks.append(0.0)

    total = len(cases)
    if total == 0:
        return {"Recall@5": 0.0, "MRR": 0.0}

    return {
        "Recall@5": hits / total,
        "MRR": sum(reciprocal_ranks) / total,
    }


async def evaluate_retrieval(session_factory) -> dict[str, dict[str, float]]:
    """Сравнить FTS-only с текущим гибридным поиском."""
    cases = load_yaml(CASES_DIR / "retrieval.yaml")
    fts_results = []
    hybrid_results = []

    # FTS-only: подменяем LLM заглушкой на время этого набора запросов.
    original_get_llm = retriever._get_llm

    class DisabledLLM:
        enabled = False

    try:
        retriever._get_llm = lambda: DisabledLLM()

        async with session_factory() as session:
            for case in cases:
                hits = await search(
                    session,
                    case["query"],
                    destination=case.get("destination"),
                    limit=TOP_K,
                )
                fts_results.append(hits)
    finally:
        retriever._get_llm = original_get_llm

    # Гибридный режим использует текущий клиент из настроек.
    async with session_factory() as session:
        for case in cases:
            hits = await search(
                session,
                case["query"],
                destination=case.get("destination"),
                limit=TOP_K,
            )
            hybrid_results.append(hits)

    return {
        "FTS": retrieval_metrics(fts_results, cases),
        "Hybrid": retrieval_metrics(hybrid_results, cases),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Оценка RAG и разбора запросов")
    parser.add_argument(
        "--llm-understand",
        action="store_true",
        help="дополнительно проверить LLM-разбор запросов (может расходовать токены)",
    )
    parser.add_argument("--limit", type=int, help="сколько кейсов LLM-разбора взять")
    parser.add_argument("--pause", type=float, default=0.0, help="секунд между запросами к LLM")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            rows = (await session.scalars(
                select(DestinationRow)
            )).all()

        catalog = [
            Destination(
                slug=row.slug,
                name=row.name,
                country=row.country,
                iata=row.iata,
                lat=row.lat,
                lon=row.lon,
                timezone=row.timezone,
                tags=row.tags,
                warm_months=row.warm_months,
            )
            for row in rows
        ]

        parse_passed, parse_total, parse_errors = await evaluate_parse(catalog)
        print("\nРазбор запросов (rules)")
        print(f"Успешно: {parse_passed}/{parse_total}")

        for error in parse_errors:
            print(f"  - {error}")

        retrieval = await evaluate_retrieval(session_factory)
        print("\nПоиск по базе знаний")
        print(f"{'Режим':<12} {'Recall@5':>10} {'MRR':>10}")
        for mode, metrics in retrieval.items():
            print(
                f"{mode:<12} {metrics['Recall@5']:>10.3f} "
                f"{metrics['MRR']:>10.3f}"
            )

        if args.llm_understand:
            llm = make_llm(settings)
            if not llm.enabled:
                print("\nLLM-разбор пропущен: API-ключ не настроен.")
            else:
                passed, total, errors = await evaluate_understand(
                    catalog, llm, limit=args.limit, pause=args.pause
                )
                print("\nРазбор запросов (LLM)")
                print(f"Успешно: {passed}/{total}")
                for error in errors:
                    print(f"  - {error}")

        print("\nКонфигурация")
        print(json.dumps({
            "llm_enabled": settings.llm_enabled,
            "retrieval_cases": len(load_yaml(CASES_DIR / "retrieval.yaml")),
            "parse_cases": len(load_yaml(CASES_DIR / "parse.yaml")),
        }, ensure_ascii=False, indent=2))

        if retrieval["Hybrid"]["Recall@5"] < retrieval["FTS"]["Recall@5"]:
            print(
                "\nОшибка: Recall@5 гибридного поиска ниже, "
                "чем у полнотекстового."
            )
            return 1

        return 0 if parse_passed == parse_total else 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))