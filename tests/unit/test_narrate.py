"""Сравнение пакетов с соседями без LLM и живой текст модели с проверкой чисел и ссылок."""

import asyncio
import json
from decimal import Decimal

from tests.fakes import FakeLLM, sample_package
from trip_pilot.domain.knowledge import KnowledgeHit
from trip_pilot.domain.request import TripRequest
from trip_pilot.services.explanation import narrate

KNOWLEDGE = [
    KnowledgeHit(
        text="Песчаные пляжи с пологим входом.",
        title="Анталья",
        heading_path="Анталья › С детьми",
        source="wikivoyage",
        score=1.0,
    )
]


def three_packages():
    """Эконом, Баланс и Комфорт: одинаковый маршрут, разные цена, отель и пляж."""
    base = sample_package("p-economy")
    economy = base.model_copy(
        update={
            "tier": "economy",
            "total": Decimal("100000"),
            "price_breakdown": {"hotel": Decimal("100000")},
            "hotel": base.hotel.model_copy(
                update={"beach_distance_m": 1500, "free_cancellation": False}
            ),
        }
    )
    balance = base.model_copy(
        update={
            "id": "p-balance",
            "tier": "balance",
            "total": Decimal("121000"),
            "price_breakdown": {"hotel": Decimal("121000")},
            "hotel": base.hotel.model_copy(
                update={"beach_distance_m": 700, "free_cancellation": True}
            ),
        }
    )
    comfort = base.model_copy(
        update={
            "id": "p-comfort",
            "tier": "comfort",
            "total": Decimal("142000"),
            "price_breakdown": {"hotel": Decimal("142000")},
            "hotel": base.hotel.model_copy(
                update={
                    "beach_distance_m": 300,
                    "free_cancellation": True,
                    "stars": 5,
                    "rating": 9.3,
                }
            ),
        }
    )
    return [economy, balance, comfort]


def narrated(packages, reply=None, knowledge=KNOWLEDGE, llm=None):
    model = llm or (FakeLLM() if reply is None else FakeLLM([reply]))
    return asyncio.run(
        narrate(packages, TripRequest(), knowledge=knowledge, llm=model)
    )


def test_without_llm_every_package_compares_with_neighbours():
    result = narrated(three_packages(), llm=FakeLLM())
    for package in result:
        text = " ".join([*package.why, *package.tradeoffs])
        assert "«" in text, package.id
        assert "дешевле «" in text or "дороже «" in text or "чем «" in text, package.id


def test_price_and_beach_comparisons_reuse_exact_facts():
    economy = narrated(three_packages(), llm=FakeLLM())[0]
    text = " ".join(economy.tradeoffs)
    assert "на 21 000 ₽ дешевле «Баланс», но без бесплатной отмены отеля" in text
    assert "на 1,2 км дальше от моря, чем «Комфорт»" in text


def test_narrate_does_not_mutate_input_and_works_without_key():
    packages = three_packages()
    before = [package.model_dump() for package in packages]
    result = narrated(packages)
    assert [package.model_dump() for package in packages] == before
    assert len(result) == 3


def test_model_text_is_appended_and_citations_become_sources():
    reply = json.dumps(
        {
            "packages": [
                {
                    "id": "p-balance",
                    "why": ["Ровно 700 м до моря, и отель для детей [S1]."],
                    "sources": [1],
                }
            ]
        },
        ensure_ascii=False,
    )
    result = narrated(three_packages(), reply)
    balance = next(package for package in result if package.id == "p-balance")
    assert "Ровно 700 м до моря, и отель для детей [S1]." in balance.why
    assert balance.sources == KNOWLEDGE
    assert any("дешевле «Комфорт»" in line for line in balance.tradeoffs)  # шаблоны на месте


def test_invented_number_is_dropped_and_templates_stay():
    reply = json.dumps(
        {
            "packages": [
                {
                    "id": "p-economy",
                    "why": ["Всего 999 999 ₽ — и отель рядом с морем."],
                }
            ]
        },
        ensure_ascii=False,
    )
    before = {package.id: package for package in narrated(three_packages(), llm=FakeLLM())}
    result = narrated(three_packages(), reply)
    economy = next(package for package in result if package.id == "p-economy")
    assert economy.why == before["p-economy"].why
    assert economy.sources == []


def test_broken_schema_keeps_template_explanations():
    before = {package.id: package for package in narrated(three_packages(), llm=FakeLLM())}
    result = narrated(three_packages(), "не json")
    for package in result:
        assert package.why == before[package.id].why
        assert package.sources == []


def test_citation_outside_knowledge_is_dropped():
    reply = json.dumps(
        {"packages": [{"id": "p-comfort", "why": ["Тихий пляж [S3]."], "sources": [3]}]},
        ensure_ascii=False,
    )
    before = {package.id: package for package in narrated(three_packages(), llm=FakeLLM())}
    result = narrated(three_packages(), reply)
    comfort = next(package for package in result if package.id == "p-comfort")
    assert comfort.why == before["p-comfort"].why


def test_without_knowledge_model_text_is_kept_but_without_sources():
    reply = json.dumps(
        {"packages": [{"id": "p-comfort", "why": ["До моря 300 м — ближе всех."]}]},
        ensure_ascii=False,
    )
    result = narrated(three_packages(), reply, knowledge=[])
    comfort = next(package for package in result if package.id == "p-comfort")
    assert "До моря 300 м — ближе всех." in comfort.why
    assert comfort.sources == []


def test_one_model_call_for_all_packages():
    class RecordingLLM:
        enabled = True

        def __init__(self):
            self.calls = 0
            self.messages = []

        async def complete(self, messages):
            raise AssertionError("narrate пишет только структурированный ответ")

        async def structured(self, messages, schema):
            self.calls += 1
            self.messages = messages
            return schema.model_validate({"packages": []})

        async def embed(self, texts):
            raise AssertionError("объяснения не считают эмбеддинги")

    llm = RecordingLLM()
    narrated(three_packages(), llm=llm)
    assert llm.calls == 1
    prompt = llm.messages[0]["content"]
    for package_id in ("p-economy", "p-balance", "p-comfort"):
        assert package_id in prompt
    assert "[S1]" in prompt and "Анталья › С детьми" in prompt
