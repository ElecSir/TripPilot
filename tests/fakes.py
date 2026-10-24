"""Фейковые реализации портов на данных в памяти.

С ними каждая зона пишет и тестирует свой код до появления настоящих адаптеров:
`from tests.fakes import fake_sources`. Данные детерминированы: три направления, по три отеля,
по два рейса в день в каждую сторону (Москва ↔ Сочи, Москва ↔ Анталья), по трансферу на отель.
"""

import uuid
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from trip_pilot.domain.knowledge import KnowledgeHit
from trip_pilot.domain.offers import Destination, Hotel, Leg, Package, Transfer
from trip_pilot.domain.request import Party
from trip_pilot.domain.trip_state import Order, TripState
from trip_pilot.ports import ChatMessages, LLMUnavailable

DESTINATIONS = [
    Destination(
        slug="moscow", name="Москва", country="Россия", iata="MOW", lat=55.7558, lon=37.6173,
        timezone="Europe/Moscow", tags=["city"], warm_months=[6, 7, 8],
    ),
    Destination(
        slug="sochi", name="Сочи", country="Россия", iata="AER", lat=43.5855, lon=39.7231,
        timezone="Europe/Moscow", tags=["sea", "nature"], warm_months=[6, 7, 8, 9],
    ),
    Destination(
        slug="antalya", name="Анталья", country="Турция", iata="AYT", lat=36.8969, lon=30.7133,
        timezone="Europe/Istanbul", tags=["sea", "warm"], warm_months=[5, 6, 7, 8, 9, 10],
    ),
]
_TZ = {d.slug: ZoneInfo(d.timezone) for d in DESTINATIONS}

# Маршруты из Москвы: (куда) → (минут в пути прямым рейсом, базовая цена за пассажира).
_ROUTES = {"sochi": (150, Decimal("7500")), "antalya": (240, Decimal("14000"))}

_HOTELS = [
    # направление, название, звёзды, цена за ночь, питание, бесплатная отмена,
    # с животными, для детей, до пляжа (м), рейтинг
    ("sochi", "Морской бриз", 3, "4500", "BB", True, True, True, 600, 7.9),
    ("sochi", "Ривьера Парк", 4, "8200", "HB", True, False, True, 250, 8.6),
    ("sochi", "Гранд Кипарис", 5, "15500", "AI", False, False, True, 50, 9.3),
    ("antalya", "Лара Сан", 3, "5200", "AI", False, False, True, 700, 7.6),
    ("antalya", "Коньяалты Бэй", 4, "9100", "AI", True, True, True, 300, 8.5),
    ("antalya", "Белек Резорт", 5, "18900", "AI", True, False, False, 30, 9.4),
    ("moscow", "Арбат Сити", 3, "5600", "RO", True, True, False, None, 8.0),
    ("moscow", "Тверская Плаза", 4, "9800", "BB", True, False, True, None, 8.7),
    ("moscow", "Кремлёвская Набережная", 5, "21000", "BB", False, False, True, None, 9.5),
]
HOTELS = [
    Hotel(
        id=i, destination=dest, name=name, stars=stars, price_per_night=Decimal(price),
        meal=meal, free_cancellation=free_cancel, pets_allowed=pets, kids_friendly=kids,
        beach_distance_m=beach, check_in_time=time(14), check_out_time=time(12), rating=rating,
    )
    for i, (dest, name, stars, price, meal, free_cancel, pets, kids, beach, rating)
    in enumerate(_HOTELS, start=1)
]
TRANSFERS = [
    Transfer(
        id=h.id, destination=h.destination, hotel_id=h.id, kind="taxi",
        duration_min=25 + 10 * (h.id % 3), price=Decimal("1800"), capacity=4,
        pets_allowed=h.pets_allowed,
    )
    for h in HOTELS
]

_KNOWLEDGE = [
    # направление, тип, заголовок, раздел, текст
    ("sochi", "guide", "Сочи", "Сочи › Почему ехать", "Море, горы и Олимпийский парк."),
    ("sochi", "guide", "Сочи", "Сочи › С детьми", "Галечные пляжи, дендрарий, парк развлечений."),
    ("antalya", "guide", "Анталья", "Анталья › Почему ехать", "Тёплое море до конца октября."),
    ("antalya", "guide", "Анталья", "Анталья › С детьми", "Песчаные пляжи с пологим входом."),
    ("moscow", "guide", "Москва", "Москва › Почему ехать", "Музеи, театры и прогулки по центру."),
]


def _stable_id(*parts: object) -> int:
    """Детерминированный id: hash() строк в Python меняется от запуска к запуску."""
    return zlib.crc32("|".join(map(str, parts)).encode())


class FakeDestinationCatalog:
    async def all(self) -> list[Destination]:
        return list(DESTINATIONS)


class FakeHotelSource:
    async def search(
        self, destination: str, check_in: date, check_out: date, party: Party
    ) -> list[Hotel]:
        return [h for h in HOTELS if h.destination == destination]


def _legs(origin: str, destination: str, day: date) -> list[Leg]:
    """Два рейса в день: утренний прямой подороже и вечерний с пересадкой подешевле."""
    route = _ROUTES.get(destination if origin == "moscow" else origin)
    if route is None or "moscow" not in (origin, destination) or origin == destination:
        return []
    minutes, base_price = route
    options = [(time(8, 30), 0, minutes, base_price * Decimal("1.2")),
               (time(19, 10), 1, minutes + 150, base_price * Decimal("0.8"))]
    legs = []
    for n, (start, stops, duration, price) in enumerate(options):
        depart = datetime.combine(day, start, tzinfo=_TZ[origin])
        legs.append(Leg(
            id=_stable_id(origin, destination, day, n), mode="flight",
            origin=origin, destination=destination,
            depart_at=depart,
            arrive_at=(depart + timedelta(minutes=duration)).astimezone(_TZ[destination]),
            price=price.quantize(Decimal("1")), stops=stops, carrier="Демо Авиа",
            baggage_included=stops == 0, pets_allowed=True,
        ))
    return legs


def sample_package(
    package_id: str = "p1",
    *,
    destination: str = "antalya",
    day: date = date(2030, 11, 10),
    nights: int = 7,
    party: Party | None = None,
) -> Package:
    """Готовый пакет из фейковых данных для тестов и примеров UI.

    Самый дешёвый рейс туда и обратно и самый дешёвый отель. Это не логика подбора:
    её делает data в planning/.
    """
    party = party or Party()
    back_day = day + timedelta(days=nights)
    out = min(_legs("moscow", destination, day), key=lambda leg: leg.price)
    back = min(_legs(destination, "moscow", back_day), key=lambda leg: leg.price)
    hotels = [h for h in HOTELS if h.destination == destination]
    hotel = min(hotels, key=lambda h: h.price_per_night)
    transfer = next(t for t in TRANSFERS if t.hotel_id == hotel.id)
    breakdown = {
        "flights": (out.price + back.price) * party.travellers,
        "hotel": hotel.price_per_night * nights,
        "transfer": transfer.price * 2,
    }
    return Package(
        id=package_id, tier="economy", destination=destination, outbound=out, inbound=back,
        hotel=hotel, transfer=transfer, check_in=day, check_out=back_day, nights=nights,
        total=sum(breakdown.values()), price_breakdown=breakdown,
    )


class FakeTransportSource:
    async def search(self, origin: str, destination: str, day: date, party: Party) -> list[Leg]:
        return _legs(origin, destination, day)


class FakeTransferSource:
    async def search(self, hotel_id: int, arrive_at: datetime, party: Party) -> list[Transfer]:
        return [t for t in TRANSFERS if t.hotel_id == hotel_id and t.capacity >= party.travellers]


class FakeKnowledgeBase:
    async def search(
        self,
        query: str,
        *,
        destination: str | None = None,
        doc_type: str | None = None,
        limit: int = 5,
    ) -> list[KnowledgeHit]:
        words = {w for w in query.lower().split() if len(w) > 2}
        hits = []
        for dest, kind, title, heading, text in _KNOWLEDGE:
            if (destination and dest != destination) or (doc_type and kind != doc_type):
                continue
            score = sum(w in f"{heading} {text}".lower() for w in words)
            if score:
                hits.append(KnowledgeHit(
                    text=text, title=title, heading_path=heading, source="synthetic",
                    score=float(score),
                ))
        return sorted(hits, key=lambda h: h.score, reverse=True)[:limit]


class FakeLLM:
    """Без ответов ведёт себя как LLM без ключа. С ответами отдаёт их по очереди."""

    def __init__(self, replies: list[str] | None = None) -> None:
        self.enabled = replies is not None
        self._replies = list(replies or [])

    def _next(self) -> str:
        if not self.enabled:
            raise LLMUnavailable("ключ LLM не задан")
        return self._replies.pop(0)

    async def complete(self, messages: ChatMessages) -> str:
        return self._next()

    async def structured[T: BaseModel](self, messages: ChatMessages, schema: type[T]) -> T:
        return schema.model_validate_json(self._next())

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.enabled:
            raise LLMUnavailable("ключ LLM не задан")
        return [[(_stable_id(t, i) % 1000) / 1000 for i in range(8)] for t in texts]


class FakeOrderRepository:
    """Как SqlOrderRepository: ключ идемпотентности уникален в пределах сессии."""

    def __init__(self) -> None:
        self.orders: dict[tuple[uuid.UUID, str], Order] = {}

    async def create(self, session_id: uuid.UUID, package: Package, idempotency_key: str) -> Order:
        key = (session_id, idempotency_key)
        if key not in self.orders:
            now = datetime.now(_TZ["moscow"])
            self.orders[key] = Order(
                id=f"TP-{now.year}-{len(self.orders) + 1:06d}", package_id=package.id,
                total=package.total, status="paid", created_at=now,
            )
        return self.orders[key]


class FakeTripStateRepository:
    def __init__(self) -> None:
        self.states: dict[uuid.UUID, TripState] = {}

    async def load(self, session_id: uuid.UUID) -> TripState | None:
        state = self.states.get(session_id)
        return state.model_copy(deep=True) if state else None

    async def save(self, state: TripState) -> None:
        self.states[state.session_id] = state.model_copy(deep=True)


@dataclass
class FakeSources:
    catalog: FakeDestinationCatalog = field(default_factory=FakeDestinationCatalog)
    hotels: FakeHotelSource = field(default_factory=FakeHotelSource)
    transport: FakeTransportSource = field(default_factory=FakeTransportSource)
    transfers: FakeTransferSource = field(default_factory=FakeTransferSource)
    knowledge: FakeKnowledgeBase = field(default_factory=FakeKnowledgeBase)
    llm: FakeLLM = field(default_factory=FakeLLM)
    orders: FakeOrderRepository = field(default_factory=FakeOrderRepository)
    trips: FakeTripStateRepository = field(default_factory=FakeTripStateRepository)


def fake_sources() -> FakeSources:
    """Полный набор фейков; каждый вызов — с чистыми хранилищами."""
    return FakeSources()
