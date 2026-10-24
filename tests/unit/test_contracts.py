"""Контракты ядра и фейки: фейки реализуют все порты, а модели держат свои инварианты."""

import asyncio
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from tests.fakes import fake_sources, sample_package
from trip_pilot import ports
from trip_pilot.domain.offers import Leg, Package
from trip_pilot.domain.request import Party, TripRequest
from trip_pilot.domain.trip_state import TripState

DAY = date(2030, 11, 10)


def run(coro):
    return asyncio.run(coro)


def make_package() -> Package:
    return sample_package(day=DAY, party=Party(adults=2, children_ages=[5]))


def test_fakes_implement_all_ports():
    src = fake_sources()
    assert isinstance(src.catalog, ports.DestinationCatalog)
    assert isinstance(src.hotels, ports.HotelSource)
    assert isinstance(src.transport, ports.TransportSource)
    assert isinstance(src.transfers, ports.TransferSource)
    assert isinstance(src.knowledge, ports.KnowledgeBase)
    assert isinstance(src.llm, ports.LLM)
    assert isinstance(src.orders, ports.OrderRepository)
    assert isinstance(src.trips, ports.TripStateRepository)


def test_fake_data_is_enough_for_three_different_packages():
    src = fake_sources()
    party = Party()
    hotels = run(src.hotels.search("antalya", DAY, DAY + timedelta(days=7), party))
    assert {h.stars for h in hotels} == {3, 4, 5}
    assert len(run(src.transport.search("moscow", "antalya", DAY, party))) == 2
    assert len(run(src.transport.search("antalya", "moscow", DAY, party))) == 2
    for hotel in hotels:
        assert run(src.transfers.search(hotel.id, datetime.now(ZoneInfo("UTC")), party))


def test_fake_legs_use_local_time_zones():
    leg = run(fake_sources().transport.search("moscow", "antalya", DAY, Party()))[0]
    assert leg.depart_at.tzinfo == ZoneInfo("Europe/Moscow")
    assert leg.arrive_at.tzinfo == ZoneInfo("Europe/Istanbul")
    assert leg.duration_min == 240


def test_package_total_must_match_breakdown():
    package = make_package()
    assert package.total == sum(package.price_breakdown.values())

    with pytest.raises(ValidationError, match="total"):
        Package.model_validate(package.model_dump() | {"total": package.total + 1})
    with pytest.raises(ValidationError, match="nights"):
        Package.model_validate(package.model_dump() | {"nights": 3})


def test_leg_requires_time_zone_and_order():
    leg = run(fake_sources().transport.search("moscow", "sochi", DAY, Party()))[0]
    naive = leg.model_dump() | {"depart_at": datetime(2030, 11, 10, 8, 30)}
    with pytest.raises(ValidationError):
        Leg.model_validate(naive)
    with pytest.raises(ValidationError, match="прибытие"):
        Leg.model_validate(leg.model_dump() | {"arrive_at": leg.depart_at})


def test_party_rules():
    assert Party(adults=2, children_ages=[5, None]).travellers == 4  # None: возраст не известен
    with pytest.raises(ValidationError):
        Party(adults=0)
    with pytest.raises(ValidationError):
        Party(children_ages=[18])


def test_trip_state_json_roundtrip_keeps_money_exact():
    state = TripState(
        session_id=uuid.uuid4(),
        request=TripRequest(destination="antalya", budget=Decimal("150000")),
        packages=[make_package()],
    )
    raw = state.model_dump_json()
    assert '"budget":"150000"' in raw  # деньги в JSON — строкой, без потери точности
    assert TripState.model_validate_json(raw) == state


def test_fake_orders_are_idempotent():
    src = fake_sources()
    package = make_package()
    session = uuid.uuid4()
    first = run(src.orders.create(session, package, "key-1"))
    again = run(src.orders.create(session, package, "key-1"))
    other = run(src.orders.create(session, package, "key-2"))
    assert first == again
    assert other.id != first.id
    assert first.id.startswith("TP-")


def test_fake_llm_without_replies_is_disabled():
    llm = fake_sources().llm
    assert llm.enabled is False
    with pytest.raises(ports.LLMUnavailable):
        run(llm.complete([{"role": "user", "content": "привет"}]))


def test_fake_knowledge_filters_by_destination():
    hits = run(fake_sources().knowledge.search("с детьми пляжи", destination="antalya"))
    assert hits
    assert all(h.title == "Анталья" for h in hits)
