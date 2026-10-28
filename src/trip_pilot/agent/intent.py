"""Разбор русских запросов и изменений поездки правилами, без IO и LLM."""

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from rapidfuzz.fuzz import ratio
from returns.result import Failure, Result, Success

from trip_pilot.domain.errors import (
    AmbiguousCity,
    DatesInPast,
    DomainError,
    NoResults,
    UnknownCity,
)
from trip_pilot.domain.offers import Destination
from trip_pilot.domain.request import Assumption, TripRequest

MONTHS = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)
_MONTH_FORMS = (
    ("январь", "января", "январе"),
    ("февраль", "февраля", "феврале"),
    ("март", "марта", "марте"),
    ("апрель", "апреля", "апреле"),
    ("май", "мая", "мае"),
    ("июнь", "июня", "июне"),
    ("июль", "июля", "июле"),
    ("август", "августа", "августе"),
    ("сентябрь", "сентября", "сентябре"),
    ("октябрь", "октября", "октябре"),
    ("ноябрь", "ноября", "ноябре"),
    ("декабрь", "декабря", "декабре"),
)
_MONTH_NUMBERS = {word: number for number, forms in enumerate(_MONTH_FORMS, 1) for word in forms}
_MONTH_PATTERN = "(?:" + "|".join(_MONTH_NUMBERS) + ")"
_NUMBERS = {
    "один": 1,
    "одну": 1,
    "одна": 1,
    "два": 2,
    "две": 2,
    "двух": 2,
    "три": 3,
    "трех": 3,
    "четыре": 4,
    "пять": 5,
    "семь": 7,
    "десять": 10,
}
_ALIASES = {
    "moscow": ("москва", "москвы", "москву", "москве", "масква", "масквы"),
    "spb": (
        "спб",
        "питер",
        "питера",
        "питере",
        "петербург",
        "петербурга",
        "санкт-петербург",
        "санкт-петербурга",
        "санкт петербург",
        "санкт петербурга",
    ),
    "kazan": ("казань", "казани"),
    "antalya": ("анталья", "анталью", "антальи", "анталия", "анталию"),
    "anapa": ("анапа", "анапу", "анапы", "анапе"),
    "kaliningrad": ("калининград", "калининграда", "калининграде"),
    "murmansk": ("мурманск", "мурманска", "мурманске"),
    "dubai": ("дубай", "дубая", "дубае"),
    "sharm": (
        "шарм",
        "шарма",
        "шарме",
        "шарм-эль-шейх",
        "шарм-эль-шейха",
        "шарм эль шейх",
        "шарм эль шейха",
    ),
    "phuket": ("пхукет", "пхукета", "пхукете"),
    "nha-trang": ("нячанг", "нячанга", "нячанге", "нья-чанг", "нья чанг"),
}
# Страны: ключ — название из каталога в нижнем регистре, значения — падежные формы.
_COUNTRY_FORMS = {
    "россия": ("россию", "россии", "рф"),
    "турция": ("турцию", "турции"),
    "оаэ": ("эмираты", "эмиратах", "эмиратов", "арабские эмираты"),
    "египет": ("египта", "египте"),
    "таиланд": ("таиланда", "таиланде", "тайланд", "тайланда", "тай"),
    "вьетнам": ("вьетнама", "вьетнаме"),
}
_COUNTRY_FUZZY = 80  # опечатки в названии страны («турцмю»)
_CLOSE_MISS = 65  # слово после «в» настолько похоже на город, что это опечатка, а не «в начале»
_CITY_NOISE = {
    "море",
    "морю",
    "город",
    "горы",
    "майские",
    "теплое",
    "теплому",
    "теплые",
    "теплую",
    "отпуск",
    "отпуске",
    "ноябре",
    "декабре",
    "январе",
    "феврале",
    "марте",
    "апреле",
    "мае",
    "июне",
    "июле",
    "августе",
    "сентябре",
    "октябре",
    "выходные",
    "неделю",
    "двух",
    "троем",
    "двоем",
    "возрасте",
}
_CITY_STOP = {
    "в",
    "во",
    "из",
    "с",
    "со",
    "на",
    "до",
    "по",
    "и",
    "за",
    "от",
    "без",
    "вдвоем",
    "втроем",
    "недорого",
    "бюджет",
    "через",
    "одна",
    "один",
}


def normalize(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").strip().split())


def month_number(word: str) -> int | None:
    return _MONTH_NUMBERS.get(normalize(word))


def _scores(value: str, catalog: list[Destination]) -> dict[str, float]:
    scores = {}
    for city in catalog:
        aliases = [city.name, city.slug, *_ALIASES.get(city.slug, ())]
        if city.iata:
            aliases.append(city.iata)
        scores[city.slug] = max(ratio(value, normalize(alias)) for alias in aliases)
    return scores


def resolve_city(raw: str, catalog: list[Destination]) -> Result[str, DomainError]:
    """Алиасы действуют только для городов из переданного каталога."""
    value = normalize(raw).strip(" .,!?")
    scores = _scores(value, catalog)
    if not scores or max(scores.values()) < 80:
        return Failure(UnknownCity(raw))
    best = max(scores.values())
    candidates = tuple(slug for slug, score in scores.items() if score >= best - 3)
    if len(candidates) > 1:
        return Failure(AmbiguousCity(raw, candidates))
    return Success(candidates[0])


def _country_slugs(value: str, catalog: list[Destination]) -> tuple[str, ...]:
    """Направления страны из каталога, если значение — название страны в любом падеже."""
    for country in dict.fromkeys(normalize(city.country) for city in catalog):
        forms = (country, *_COUNTRY_FORMS.get(country, ()))
        if any(
            value == form or (len(value) >= 5 and ratio(value, form) >= _COUNTRY_FUZZY)
            for form in forms
        ):
            return tuple(city.slug for city in catalog if normalize(city.country) == country)
    return ()


def resolve_place(raw: str, catalog: list[Destination]) -> Result[str, DomainError]:
    """Куда: страна даёт её направления из каталога (одно — slug, несколько — AmbiguousCity)."""
    value = normalize(raw).strip(" .,!?")
    slugs = _country_slugs(value, catalog)
    if len(slugs) == 1:
        return Success(slugs[0])
    if slugs:
        return Failure(AmbiguousCity(raw, slugs))
    return resolve_city(raw, catalog)


def _capitalized(text: str) -> set[str]:
    """Слова, написанные с заглавной: «в Урюпинск» — название места, а не «в начале»."""
    return {normalize(word) for word in re.findall(r"[А-ЯЁA-Z][а-яёa-z-]*", text)}


def _resolve_phrase(
    words: list[str], catalog: list[Destination], *, origin: bool, capitalized: set[str]
) -> Result[str, DomainError] | None:
    """Success или Failure по названию. None: слова не похожи на город, их пропускаем."""
    resolve = resolve_city if origin else resolve_place
    result = None
    for length in range(len(words), 0, -1):
        result = resolve(" ".join(words[:length]), catalog)
        if isinstance(result, Success) or isinstance(result.failure(), AmbiguousCity):
            return result
    if origin:  # «из …» без города — ошибка, пропускать нельзя
        return result
    close = any(
        max(_scores(" ".join(words[:length]), catalog).values(), default=0) >= _CLOSE_MISS
        for length in range(1, len(words) + 1)
    )
    if close or words[0] in capitalized:
        return Failure(UnknownCity(words[0]))
    return None


def _cities(
    text: str, catalog: list[Destination], capitalized: set[str] | None = None
) -> Result[dict, DomainError]:
    patch = {}
    # Lookahead позволяет увидеть и «из Москвы», и следующее «в Сочи».
    pattern = r"(?=\b(из|в|во|на)\s+([а-яa-z][а-яa-z-]*(?:\s+[а-яa-z][а-яa-z-]*){0,2}))"
    for match in re.finditer(pattern, text):
        marker, phrase = match.groups()
        words = phrase.split()
        if words[0] in _CITY_NOISE or month_number(words[0]) is not None:
            continue
        for index, word in enumerate(words):
            if word in _CITY_STOP:
                words = words[:index]
                break
        if not words:
            continue
        result = _resolve_phrase(
            words, catalog, origin=marker == "из", capitalized=capitalized or set()
        )
        if result is None:
            continue
        if isinstance(result, Failure):
            return result
        patch["origin" if marker == "из" else "destination"] = result.unwrap()
    return Success(patch)


def _number(raw: str) -> int:
    return int(raw) if raw.isdigit() else _NUMBERS[raw]


def _future_date(day: int, month: int, year: int | None, today: date) -> date:
    """Дата без года, уже прошедшая в текущем году, переносится на следующий."""
    y = year if year is not None else today.year
    candidate = date(y, month, day)
    if year is None and candidate < today:
        candidate = date(y + 1, month, day)
    return candidate


def parse_when(text: str, today: date) -> dict[str, Any] | None:
    """Разбирает названные даты; проверку прошлого выполняет вызывающая функция."""
    text = normalize(text)
    if match := re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text):
        return {"date_from": date.fromisoformat(match[1]), "month": None}
    if match := re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b", text):
        year = int(match[3]) if match[3] else None
        return {
            "date_from": _future_date(int(match[1]), int(match[2]), year, today),
            "month": None,
        }
    # «с 5 по 12 декабря» и «с 5 до 12 декабря»; «до» не должно уходить в бюджет.
    range_pattern = (
        rf"\bс\s+(\d{{1,2}})\s*({_MONTH_PATTERN})?\s*(?:по|до)\s+(\d{{1,2}})\s*"
        rf"({_MONTH_PATTERN})(?:\s+(\d{{4}}))?\b"
    )
    if match := re.search(range_pattern, text):
        start_day, start_name, end_day, end_name, year_raw = match.groups()
        end_month = month_number(end_name)
        start_month = month_number(start_name) if start_name else end_month
        year = int(year_raw) if year_raw else None
        start = _future_date(int(start_day), start_month, year, today)
        end_year = start.year + (end_month < start_month)
        end = date(end_year, end_month, int(end_day))
        return {"date_from": start, "month": None, "nights": (end - start).days}
    if match := re.search(rf"\b(\d{{1,2}})\s+({_MONTH_PATTERN})(?:\s+(\d{{4}}))?\b", text):
        year = int(match[3]) if match[3] else None
        start = _future_date(int(match[1]), month_number(match[2]), year, today)
        return {"date_from": start, "month": None}
    if match := re.search(
        r"\bчерез\s+(\d+|один|одну|две|два|три|четыре|пять|семь|десять)\s+"
        r"(недел\w*|дн\w*|день)\b",
        text,
    ):
        days = _number(match[1]) * (7 if match[2].startswith("недел") else 1)
        return {"date_from": today + timedelta(days=days), "month": None}
    for word, days in (("послезавтра", 2), ("завтра", 1)):
        if re.search(rf"\b{word}\b", text):
            return {"date_from": today + timedelta(days=days), "month": None}
    if "майские" in text:
        return {"month": 5, "date_from": None}
    for word in re.findall(r"[а-я]+", text):
        if number := month_number(word):
            return {"month": number, "date_from": None}
    return None


def _duration(text: str) -> int | None:
    if re.search(r"\b(?:позже|раньше)\b", text):
        return None
    word_num = r"\d+|один|одну|одна|два|две|двух|три|трех|четыре|пять|семь|десять"
    if match := re.search(
        rf"\bна\s+({word_num})\s+(недел\w*|дн\w*|день|ноч\w*)", text
    ):
        unit = match[2]
        n = _number(match[1])
        return n * 7 if unit.startswith("недел") else n
    if re.search(r"\bна\s+неделю\b", text):
        return 7
    if re.search(r"\bна\s+выходные\b", text):
        return 2
    return None


def _budget(text: str) -> Decimal | None:
    if match := re.search(r"\bтысяч\s+(\d+(?:[.,]\d+)?)", text):
        return Decimal(match[1].replace(",", ".")) * 1000
    number = r"(\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?)"
    pattern = rf"(?:(бюджет\s*(?:до\s*)?|до\s+))?{number}\s*(к\b|k\b|тыс\w*|руб\w*|₽)?"
    for match in re.finditer(pattern, text):
        marker, raw, unit = match.groups()
        if not marker and not unit:
            continue
        tail = text[match.end() :].lstrip()
        # «до 12 декабря» / «до 2 лет» — не бюджет
        if tail.startswith(("лет", "год", "ноч", "дн", "день")) or month_number(
            tail.split()[0] if tail else ""
        ):
            continue
        amount = Decimal(raw.replace(" ", "").replace("\u00a0", "").replace(",", "."))
        if unit and unit.startswith(("к", "k", "тыс")):
            amount *= 1000
        if marker or unit:
            return amount
    return None


def _party(text: str, current: TripRequest) -> tuple[dict, list[str], set[str]]:
    party = current.party.model_dump()
    fields = set()
    must = list(current.must)
    adults = None
    if match := re.search(r"\b(\d+)\s+взросл", text):
        adults = int(match[1])
    else:
        for pattern, count in (
            (r"\bвдвоем\b|\bс мужем\b|\bс женой\b", 2),
            (r"\bвтроем\b", 3),
            # «один/одна» — состав, но не перед «день/ночь/неделю» («на один день позже»)
            (r"\b(?:одна|один)\b(?!\s+(?:дн\w*|день|ноч\w*|недел\w*))", 1),
        ):
            if re.search(pattern, text):
                adults = count
                break
    if adults is not None:
        party["adults"] = adults
        fields.add("adults")
    # «отель для детей» и «детский отель» — требование к отелю, а не состав поездки:
    # ребёнка в такой фразе нет, поэтому состав не трогаем.
    child = re.search(r"(?<!для )\b(?:ребен\w*|детьми|дети|детей)\b", text)
    if child:
        ages = re.search(r"(\d+(?:\s*(?:,|и)\s*\d+)*)\s*(?:лет|года?|год)\b", text[child.end() :])
        is_range = re.search(r"\bдо\s+\d+\s*(?:лет|год)", text[child.end() :])
        party["children_ages"] = (
            [int(age) for age in re.findall(r"\d+", ages[1])] if ages and not is_range else [None]
        )
        count = re.search(r"\b(\d+|двумя|тремя|двое|трое)\s+(?:детьми|детей|ребенка)\b", text)
        if count and not ages:
            value = {"двумя": 2, "тремя": 3, "двое": 2, "трое": 3}.get(count[1])
            party["children_ages"] = [None] * (value if value is not None else int(count[1]))
        fields.add("children_ages")
    if re.search(r"\bбез\s+детей\b", text):
        party["children_ages"] = []
        fields.add("children_ages")
    excluded = set()
    if re.search(r"\bбез\s+животных\b", text):
        excluded = set(party["pets"])
        party["pets"] = []
        fields.add("pets")
    else:
        if re.search(r"\bбез\s+собаки\b", text):
            excluded.add("dog")
        if re.search(r"\bбез\s+(?:кота|кошки)\b", text):
            excluded.add("cat")
        pets = [
            pet
            for pattern, pet in (
                (r"\bсобак(?:а|ой|у|и|е)?\b", "dog"),
                (r"\b(?:кот(?:ом|а|у|ы|е|ов)?|кошк(?:а|ой|у|и|е))\b", "cat"),
            )
            if re.search(pattern, text) and pet not in excluded
        ]
        if pets or excluded:
            party["pets"] = [
                pet for pet in dict.fromkeys([*party["pets"], *pets]) if pet not in excluded
            ]
            fields.add("pets")
    if "pets" in fields:
        must = [flag for flag in must if flag != "pets_allowed"]
        if party["pets"]:
            must.append("pets_allowed")
    return ({"party": party} if fields else {}), must, fields


def _assumptions(
    current: TripRequest,
    patch: dict,
    extra: list[Assumption],
    party_fields: set[str],
) -> list[Assumption]:
    fields = set(patch) - {"party"}
    fields.update(f"party.{field}" for field in party_fields)
    if "adults" in party_fields:
        fields.add("party")
    if "children_ages" in party_fields:
        fields.add("party.children_count")
    kept = [
        item
        for item in current.assumptions
        if item.field not in fields
        and not any(field != "party" and item.field.startswith(field + ".") for field in fields)
    ]
    return list({(item.field, item.value, item.reason): item for item in [*kept, *extra]}.values())


def parse_request(
    text: str,
    *,
    catalog: list[Destination],
    today: date,
    base: TripRequest | None = None,
) -> Result[TripRequest, DomainError]:
    """Новое сообщение дополняет базу; месяцу не назначаются даты поиска."""
    current = base or TripRequest()
    low = normalize(text)
    cities = _cities(low, catalog, _capitalized(text))
    if isinstance(cities, Failure):
        return cities
    patch = cities.unwrap()
    extra = []
    try:
        patch.update(parse_when(low, today) or {})
        duration = _duration(low)
        if duration is not None:
            patch["nights"] = duration
        budget = _budget(low)
        if budget is not None:
            patch["budget"] = budget
        party, must, party_fields = _party(low, current)
        patch.update(party)
        if "без пересадок" in low or "прямой рейс" in low:
            must = list(dict.fromkeys([*must, "direct_only"]))
        if "для детей" in low or "детский отель" in low:
            must = list(dict.fromkeys([*must, "kids_friendly"]))
        if must != current.must:
            patch["must"] = must
        tags = list(current.tags)
        for pattern, tag in (
            (r"\bмор[еюя]\b", "sea"),
            (r"\bтепл\w*", "warm"),
            (r"\bгород\b", "city"),
            (r"\bгор[ыау]\b", "nature"),
        ):
            if re.search(pattern, low) and tag not in tags:
                tags.append(tag)
        if tags != current.tags:
            patch["tags"] = tags
        if base is None and "adults" not in party_fields:
            extra.append(
                Assumption(field="party", value="2 взрослых", reason="Число взрослых не указано")
            )
        if (
            "children_ages" in party_fields
            and party["party"]["children_ages"] == [None]
            and re.search(r"\b(?:детьми|дети|детей)\b", low)
            and not re.search(r"\b(?:\d+|двумя|тремя|двое|трое)\s+(?:детьми|детей)\b", low)
        ):
            extra.append(
                Assumption(
                    field="party.children_count",
                    value="1 ребёнок",
                    reason="Число детей не указано; пока отмечен один ребёнок для уточнения",
                )
            )
        if "недорого" in low and budget is None:
            extra.append(
                Assumption(
                    field="budget",
                    value="недорого",
                    reason="Точная сумма не указана; числовой бюджет не придумываем",
                )
            )
        start = patch.get("date_from")
        if start is not None and start < today:
            return Failure(DatesInPast(start))
        patch["assumptions"] = _assumptions(current, patch, extra, party_fields)
        return Success(TripRequest.model_validate(current.model_dump() | patch))
    except (ValueError, OverflowError, ValidationError):
        return Failure(NoResults("Проверьте даты, длительность, бюджет и состав поездки"))


def has_city_clause(text: str) -> bool:
    """Смешанное сообщение с городом нужно разбирать там, где доступен каталог."""
    return any(
        match[1] == "из" or (match[2] not in _CITY_NOISE and month_number(match[2]) is None)
        for match in re.finditer(r"\b(из|в|во)\s+([а-яa-z-]+)", text)
    )


def parse_change(text: str, current: TripRequest, *, today: date) -> dict[str, Any] | None:
    """Патч считается от последнего поиска; неприменимое изменение отдаём общему разбору."""
    low, patch, extra = normalize(text), {}, []
    if has_city_clause(low):
        return None
    try:
        shift = re.search(
            r"\bна\s+(\d+|один|два|две|три|четыре|пять|семь)\s+"
            r"(?:дн\w*|день)\s+(позже|раньше)",
            low,
        )
        if shift and current.date_from is not None:
            days = _number(shift[1]) * (1 if shift[2] == "позже" else -1)
            start = current.date_from + timedelta(days=days)
            if start < today:
                return None
            patch["date_from"] = start
        patch.update(parse_when(low, today) or {})
        if budget := _budget(low):
            patch["budget"] = budget
        elif (
            re.search(r"\b(?:бюджет\s+меньше|подешевле|дешевле)\b", low)
            and current.budget is not None
        ):
            patch["budget"] = (current.budget * Decimal("0.8")).quantize(Decimal("0.01"))
            extra.append(
                Assumption(
                    field="budget",
                    value=str(patch["budget"]),
                    reason="«Бюджет меньше» → уменьшение на 20%",
                )
            )
        if duration := _duration(low):
            patch["nights"] = duration
        party, must, party_fields = _party(low, current)
        patch.update(party)
        if "без пересадок" in low or "прямой рейс" in low:
            must = list(dict.fromkeys([*must, "direct_only"]))
        if must != current.must:
            patch["must"] = must
        if not patch:
            return None
        patch["assumptions"] = _assumptions(current, patch, extra, party_fields)
        validated = TripRequest.model_validate(current.model_dump() | patch)
        if validated.date_from is not None and validated.date_from < today:
            return None
        return patch
    except (ValueError, OverflowError, ValidationError):
        return None
