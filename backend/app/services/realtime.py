"""Live updates: the worker PUBLISHES events, the API's WebSocket FORWARDS them.

They are different processes, so they talk through Redis pub/sub (one channel per
user). That also means it keeps working with several API instances. Events are
best-effort: if Redis hiccups, a check must never fail because of it, and the
frontend re-syncs from the REST API whenever it reconnects.
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache

import redis
import redis.asyncio as aioredis

from ..config import settings
from ..models import Product, utcnow

log = logging.getLogger(__name__)


def channel(user_id: str) -> str:
    return f"pw:events:{user_id}"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class RedisSubscription:
    def __init__(self, pubsub):
        self._pubsub = pubsub

    async def next(self, timeout: float) -> dict | None:
        """Next event for this user, or None if nothing arrived within `timeout`.

        redis-py returns None early when it swallows a housekeeping message (like the
        subscribe confirmation), so we keep waiting until the real deadline."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            message = await self._pubsub.get_message(
                ignore_subscribe_messages=True, timeout=remaining
            )
            if message is None or message.get("type") != "message":
                continue
            try:
                event = json.loads(message["data"])
            except (TypeError, ValueError):
                log.warning("dropping malformed realtime message")
                continue
            if isinstance(event, dict):
                return event


class RedisEventBus:
    def __init__(self, url: str | None = None, sync_client=None, async_client=None):
        self._url = url or settings.redis_url
        self._sync = sync_client
        self._async = async_client

    def publish(self, user_id: str, event: dict) -> None:
        if self._sync is None:
            self._sync = redis.Redis.from_url(self._url, socket_timeout=2, socket_connect_timeout=2)
        self._sync.publish(channel(user_id), json.dumps(event, separators=(",", ":")))

    @asynccontextmanager
    async def subscribe(self, user_id: str):
        """Subscribes BEFORE yielding, so no event is missed once the caller starts reading."""
        if self._async is None:
            self._async = aioredis.Redis.from_url(self._url)
        pubsub = self._async.pubsub()
        await pubsub.subscribe(channel(user_id))
        try:
            yield RedisSubscription(pubsub)
        finally:
            try:
                await pubsub.unsubscribe(channel(user_id))
                await pubsub.aclose()
            except Exception:  # connection already gone
                log.debug("pubsub cleanup failed", exc_info=True)


@lru_cache
def get_event_bus() -> RedisEventBus:
    return RedisEventBus()


def publish_event(user_id: str, type_: str, data: dict, bus=None) -> None:
    """Fire-and-forget. Never raises: realtime is a nice-to-have, not part of the check."""
    event = {"type": type_, "ts": utcnow().isoformat(), "data": data}
    try:
        (bus or get_event_bus()).publish(user_id, event)
    except Exception:
        log.warning("couldn't publish %s event", type_, exc_info=True)


def checked_event(product: Product, status: str, previous_price=None, changed=False, recorded=False) -> dict:
    return {
        "product_id": product.id,
        "status": status,  # success | error
        "current_price": product.current_price,
        "previous_price": previous_price,
        "changed": changed,
        "recorded": recorded,  # a new point was added to the history
        "checked_at": _iso(product.last_checked_at),
        "next_check_at": _iso(product.next_check_at),
        "last_error": product.last_error,
        "consecutive_failures": product.consecutive_failures,
    }


def alert_event(product: Product, reason: str, price: float | None) -> dict:
    return {
        "product_id": product.id,
        "product_name": product.name,
        "reason": reason,
        "price": price,
        "target_price": product.target_price,
    }
