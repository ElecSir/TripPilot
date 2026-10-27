"""Короткие объяснения: шаблоны по фактам пакета, сравнение соседей и живой текст от LLM."""

import json
import re
from decimal import Decimal
from pathlib import Path
from string import Template

from pydantic import BaseModel, ValidationError

from trip_pilot.agent.texts import TIERS
from trip_pilot.domain.knowledge import KnowledgeHit
from trip_pilot.domain.offers import Package
from trip_pilot.domain.request import TripRequest
from trip_pilot.ports import LLM, ChatMessages, LLMUnavailable


def _money(amount: Decimal) -> str:
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",").removesuffix(",00") + " ₽"


def _duration(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return f"{hours} ч {rest} мин" if rest else f"{hours} ч"


def explain(package: Package, request: TripRequest) -> Package:
    """Соседние пакеты не переданы: сравнительные числа не придумываем."""
    why, tradeoffs, risks = [], [], list(package.issues)
    hotel = package.hotel
    for direction, leg in (("туда", package.outbound), ("обратно", package.inbound)):
        if leg.stops == 0:
            mode = "перелёт" if leg.mode == "flight" else "поезд"
            why.append(f"Прямой {mode} {direction}: {_duration(leg.duration_min)}")
        else:
            tradeoffs.append(f"Пересадок {direction}: {leg.stops}")
            if "direct_only" in request.must:
                risks.append(f"Маршрут {direction} нарушает условие «без пересадок»")
    if hotel.free_cancellation:
        why.append("Бесплатная отмена отеля")
    else:
        risks.append("Без бесплатной отмены отеля")
    if request.party.children_ages or "kids_friendly" in request.must:
        if hotel.kids_friendly:
            why.append("Отель подходит для детей")
        else:
            risks.append("Отель не отмечен как подходящий для детей")
    if request.party.pets or "pets_allowed" in request.must:
        components = [
            ("отель", hotel),
            ("рейс туда", package.outbound),
            ("рейс обратно", package.inbound),
        ]
        if package.transfer:
            components.append(("трансфер", package.transfer))
        restricted = [name for name, component in components if not component.pets_allowed]
        if restricted:
            risks.extend(f"Компонент «{name}» не допускает животных" for name in restricted)
        else:
            why.append("Можно с животными во всех включённых компонентах")
    if hotel.beach_distance_m is not None:
        why.append(f"До пляжа: {hotel.beach_distance_m} м")
    why.append(f"Отель {hotel.stars}★, рейтинг {hotel.rating}/10")
    if request.budget is not None:
        if package.total <= request.budget:
            why.append(f"Стоимость {_money(package.total)} — в бюджете {_money(request.budget)}")
        else:
            tradeoffs.append(f"Превышение бюджета: {_money(package.total - request.budget)}")
    if package.transfer is None:
        tradeoffs.append("Трансфер не включён")
    if hotel.is_synthetic or package.outbound.is_synthetic or package.inbound.is_synthetic:
        risks.append("Синтетические предложения: цены и расписание демонстрационные")
    return package.model_copy(
        update={
            "why": list(dict.fromkeys(why)),
            "tradeoffs": list(dict.fromkeys(tradeoffs)),
            "risks": list(dict.fromkeys(risks)),
        },
        deep=True,
    )


# Сравнение с соседями: числа берём только из полей пакетов, ничего не додумываем.
_MIN_GAP_M = 100  # разница в метрах меньше этой — не различие, о ней молчим
_NARRATE_PROMPT = Path(__file__).parent.parent / "agent" / "prompts" / "narrate.md"
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_THOUSANDS = re.compile(r"(?<=\d)[\s\u00a0](?=\d)")
_CITATION = re.compile(r"\[S(\d+)\]")


class _PackageText(BaseModel):
    """Живой текст по одному пакету: ровно то, что вернула модель."""

    id: str
    why: list[str] = []
    tradeoffs: list[str] = []
    risks: list[str] = []
    sources: list[int] = []  # номера фрагментов [S1]…, на которые есть ссылки


class _Narration(BaseModel):
    packages: list[_PackageText] = []


def _tier(package: Package) -> str:
    return f"«{TIERS[package.tier]}»"


def _distance(meters: int) -> str:
    if meters >= 1000:
        return f"{meters / 1000:.1f}".replace(".", ",") + " км"
    return f"{meters} м"


def _drawback(chosen: Package, other: Package) -> str | None:
    """Чем выбранный пакет хуже соседа: первый настоящий минус, без выдумок."""
    if other.hotel.free_cancellation and not chosen.hotel.free_cancellation:
        return "без бесплатной отмены отеля"
    if other.transfer is not None and chosen.transfer is None:
        return "без трансфера"
    if other.hotel.kids_friendly and not chosen.hotel.kids_friendly:
        return "отель не для детей"
    if other.hotel.stars > chosen.hotel.stars:
        return f"отель на {other.hotel.stars - chosen.hotel.stars}★ проще"
    gap = round(other.hotel.rating - chosen.hotel.rating, 1)
    if gap >= 0.3:
        return f"рейтинг ниже на {gap}".replace(".", ",")
    return None


def _advantage(chosen: Package, other: Package) -> str | None:
    """Чем выбранный пакет лучше соседа — зеркало `_drawback`."""
    if chosen.hotel.free_cancellation and not other.hotel.free_cancellation:
        return "бесплатная отмена отеля"
    if chosen.transfer is not None and other.transfer is None:
        return "трансфер включён"
    if chosen.hotel.kids_friendly and not other.hotel.kids_friendly:
        return "отель для детей"
    if chosen.hotel.stars > other.hotel.stars:
        return f"отель на {chosen.hotel.stars - other.hotel.stars}★ лучше"
    gap = round(chosen.hotel.rating - other.hotel.rating, 1)
    if gap >= 0.3:
        return f"рейтинг выше на {gap}".replace(".", ",")
    return None


def _comparisons(packages: list[Package]) -> list[Package]:
    """«Чем жертвуем»: сравнение с соседями по цене и расстоянию до моря, без LLM."""
    compared = []
    for package in packages:
        why: list[str] = []
        tradeoffs: list[str] = []
        others = [other for other in packages if other.id != package.id]
        pricier = [other for other in others if other.total > package.total]
        cheaper = [other for other in others if other.total < package.total]
        if pricier:
            rival = min(pricier, key=lambda other: other.total)
            line = f"на {_money(rival.total - package.total)} дешевле {_tier(rival)}"
            if drawback := _drawback(package, rival):
                line += f", но {drawback}"
            tradeoffs.append(line)
        elif cheaper:
            rival = max(cheaper, key=lambda other: other.total)
            line = f"на {_money(package.total - rival.total)} дороже {_tier(rival)}"
            if advantage := _advantage(package, rival):
                line += f", зато {advantage}"
            tradeoffs.append(line)
        gaps = [
            (abs(package.hotel.beach_distance_m - other.hotel.beach_distance_m), other)
            for other in others
            if package.hotel.beach_distance_m is not None
            and other.hotel.beach_distance_m is not None
        ]
        if gaps:
            gap, rival = max(gaps, key=lambda pair: pair[0])
            if gap >= _MIN_GAP_M:
                own = package.hotel.beach_distance_m
                theirs = rival.hotel.beach_distance_m
                if own > theirs:
                    tradeoffs.append(f"на {_distance(gap)} дальше от моря, чем {_tier(rival)}")
                else:
                    why.append(f"на {_distance(gap)} ближе к морю, чем {_tier(rival)}")
        compared.append(
            package.model_copy(
                update={
                    "why": list(dict.fromkeys([*package.why, *why])),
                    "tradeoffs": list(dict.fromkeys([*package.tradeoffs, *tradeoffs])),
                },
                deep=True,
            )
        )
    return compared


def _numbers(text: str) -> set[str]:
    """Числа текста без разделителей тысяч, с точкой как десятичным знаком."""
    flat = _THOUSANDS.sub("", text)
    return {number.replace(",", ".") for number in _NUMBER.findall(flat)}


def _fact_numbers(package: Package) -> set[str]:
    """Все числа, которые есть в фактах пакета: их и только их модель вправе называть."""
    text = "\n".join([*package.why, *package.tradeoffs, *package.risks])
    extra = [
        _money(package.total),
        str(package.nights),
        str(package.hotel.stars),
        f"{package.hotel.rating}",
        f"{package.check_in:%d.%m}",
        f"{package.check_out:%d.%m}",
        *(_money(value) for value in package.price_breakdown.values()),
    ]
    if package.hotel.beach_distance_m is not None:
        extra.append(f"{package.hotel.beach_distance_m} м")
    return _numbers(" ".join([text, *extra]))


def _text_is_true(text: _PackageText, package: Package, knowledge_count: int) -> bool:
    """Текст годится, если все его числа есть в фактах, а ссылки — на существующие фрагменты."""
    lines = [*text.why, *text.tradeoffs, *text.risks]
    if not any(line.strip() for line in lines):
        return False
    # Номера ссылок — не числа в тексте: [S1] проверяем отдельно, ниже.
    plain = _CITATION.sub(" ", "\n".join(lines))
    if _numbers(plain) - _fact_numbers(package):
        return False
    exists = set(range(1, knowledge_count + 1))
    cited = {int(number) for line in lines for number in _CITATION.findall(line)}
    return cited <= exists and set(text.sources) <= exists


def _facts(package: Package) -> dict[str, object]:
    hotel = package.hotel
    return {
        "id": package.id,
        "tier": TIERS[package.tier],
        "total": _money(package.total),
        "nights": package.nights,
        "dates": f"{package.check_in:%d.%m}–{package.check_out:%d.%m}",
        "hotel": {
            "name": hotel.name,
            "stars": hotel.stars,
            "rating": hotel.rating,
            "meal": hotel.meal,
            "free_cancellation": hotel.free_cancellation,
            "kids_friendly": hotel.kids_friendly,
            "pets_allowed": hotel.pets_allowed,
            "beach_distance_m": hotel.beach_distance_m,
        },
        "transfer": package.transfer is not None,
        "outbound": {"stops": package.outbound.stops, "minutes": package.outbound.duration_min},
        "inbound": {"stops": package.inbound.stops, "minutes": package.inbound.duration_min},
        "already_said": {
            "why": package.why,
            "tradeoffs": package.tradeoffs,
            "risks": package.risks,
        },
    }


def _knowledge_block(knowledge: list[KnowledgeHit]) -> str:
    if not knowledge:
        return "нет фрагментов"
    return "\n".join(
        f"[S{number}] {hit.heading_path or hit.title}: {hit.text}"
        for number, hit in enumerate(knowledge, 1)
    )


def _apply_narration(
    packages: list[Package], narration: _Narration, knowledge: list[KnowledgeHit]
) -> list[Package]:
    by_id = {item.id: item for item in narration.packages}
    updated = []
    for package in packages:
        text = by_id.get(package.id)
        if text is None or not _text_is_true(text, package, len(knowledge)):
            updated.append(package)  # мусор или выдуманные числа — оставляем шаблоны
            continue
        sources = [
            knowledge[number - 1]
            for number in dict.fromkeys(text.sources)
            if 1 <= number <= len(knowledge)
        ]
        updated.append(
            package.model_copy(
                update={
                    "why": [*package.why, *text.why],
                    "tradeoffs": [*package.tradeoffs, *text.tradeoffs],
                    "risks": [*package.risks, *text.risks],
                    "sources": sources,
                },
                deep=True,
            )
        )
    return updated


async def narrate(
    packages: list[Package],
    request: TripRequest,
    *,
    knowledge: list[KnowledgeHit],
    llm: LLM,
) -> list[Package]:
    """Все пакеты разом: сравнение соседей шаблоном, затем живой текст модели.

    Без LLM остаются шаблоны и сравнения — жюри видит их без ключа. Текст модели добавляется,
    только если все его числа есть в фактах пакета и ссылки [S1] указывают на присланные фрагменты.
    """
    compared = _comparisons(packages)
    if not compared or not llm.enabled:
        return compared
    template = Template(_NARRATE_PROMPT.read_text(encoding="utf-8"))
    facts = json.dumps([_facts(package) for package in compared], ensure_ascii=False, indent=1)
    messages: ChatMessages = [
        {
            "role": "system",
            "content": template.substitute(facts=facts, knowledge=_knowledge_block(knowledge)),
        },
        {"role": "user", "content": "Напиши объяснения для каждого пакета по схеме."},
    ]
    try:
        narration = await llm.structured(messages, _Narration)
    except (LLMUnavailable, ValidationError):
        return compared
    return _apply_narration(compared, narration, knowledge)
