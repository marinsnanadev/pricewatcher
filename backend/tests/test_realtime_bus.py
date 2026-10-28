import asyncio
import json

import fakeredis
import pytest
from fakeredis import aioredis as fake_aioredis

from app.models import utcnow
from app.services import realtime
from app.services.realtime import RedisEventBus, alert_event, channel, checked_event, publish_event
from tests.conftest import make_product


def make_bus():
    server = fakeredis.FakeServer()
    return RedisEventBus(
        sync_client=fakeredis.FakeRedis(server=server),
        async_client=fake_aioredis.FakeRedis(server=server),
    )


def run(coro):
    return asyncio.run(coro)


def test_channel_is_per_user():
    assert channel("u1") != channel("u2")
    assert "u1" in channel("u1")


def test_publish_reaches_the_subscribed_user():
    bus = make_bus()
    event = {"type": "product.checked", "data": {"current_price": 90.0}}

    async def scenario():
        async with bus.subscribe("u1") as sub:
            bus.publish("u1", event)
            return await sub.next(2)

    assert run(scenario()) == event


def test_other_users_events_are_not_delivered():
    bus = make_bus()

    async def scenario():
        async with bus.subscribe("u1") as sub:
            bus.publish("u2", {"type": "secret"})
            return await sub.next(0.2)

    assert run(scenario()) is None


def test_next_returns_none_on_timeout():
    bus = make_bus()

    async def scenario():
        async with bus.subscribe("u1") as sub:
            return await sub.next(0.1)

    assert run(scenario()) is None


def test_malformed_messages_are_skipped():
    bus = make_bus()
    raw = bus._sync  # publish junk straight to the channel, bypassing our JSON encoding

    async def scenario():
        async with bus.subscribe("u1") as sub:
            raw.publish(channel("u1"), "{not json")
            first = await sub.next(0.3)
            raw.publish(channel("u1"), json.dumps([1, 2, 3]))  # valid JSON, wrong shape
            second = await sub.next(0.3)
            bus.publish("u1", {"type": "ok"})
            third = await sub.next(1)
            return first, second, third

    assert run(scenario()) == (None, None, {"type": "ok"})


# ---------- publish_event is best-effort ----------

class BrokenBus:
    def publish(self, user_id, event):
        raise ConnectionError("redis is down")


def test_publish_event_never_raises():
    publish_event("u1", "product.checked", {"x": 1}, bus=BrokenBus())  # must not blow up


def test_publish_event_wraps_data_with_type_and_timestamp(bus):
    publish_event("u1", "alert.triggered", {"a": 1})
    (user_id, event), = bus.published
    assert user_id == "u1"
    assert event["type"] == "alert.triggered" and event["data"] == {"a": 1}
    assert event["ts"]


# ---------- event payloads ----------

def test_checked_event_payload(db):
    now = utcnow()
    product = make_product(db, current_price=90.0, last_checked_at=now, next_check_at=now, last_error=None)
    data = checked_event(product, "success", previous_price=100.0, changed=True, recorded=True)
    assert data == {
        "product_id": product.id,
        "status": "success",
        "current_price": 90.0,
        "previous_price": 100.0,
        "changed": True,
        "recorded": True,
        "checked_at": now.isoformat(),
        "next_check_at": now.isoformat(),
        "last_error": None,
        "consecutive_failures": 0,
    }


def test_checked_event_handles_missing_dates(db):
    product = make_product(db)
    data = checked_event(product, "error")
    assert data["checked_at"] is None and data["next_check_at"] is None


def test_alert_event_payload(db):
    product = make_product(db, target_price=100.0)
    assert alert_event(product, "target_reached", 95.0) == {
        "product_id": product.id,
        "product_name": "Test product",
        "reason": "target_reached",
        "price": 95.0,
        "target_price": 100.0,
    }
