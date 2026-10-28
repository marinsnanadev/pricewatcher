import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager


class _Subscription:
    def __init__(self, queue: asyncio.Queue):
        self._queue = queue

    async def next(self, timeout: float):
        try:
            return await asyncio.wait_for(self._queue.get(), timeout)
        except asyncio.TimeoutError:
            return None


class InMemoryEventBus:
    """Same interface as RedisEventBus, no Redis. publish() is thread-safe because the
    WebSocket handler runs in the TestClient's event-loop thread."""

    def __init__(self):
        self.published: list[tuple[str, dict]] = []
        self._subscribers = defaultdict(list)

    def publish(self, user_id: str, event: dict) -> None:
        self.published.append((user_id, event))
        for loop, queue in list(self._subscribers[user_id]):
            loop.call_soon_threadsafe(queue.put_nowait, event)

    @asynccontextmanager
    async def subscribe(self, user_id: str):
        queue: asyncio.Queue = asyncio.Queue()
        entry = (asyncio.get_running_loop(), queue)
        self._subscribers[user_id].append(entry)
        try:
            yield _Subscription(queue)
        finally:
            self._subscribers[user_id].remove(entry)

    def subscriber_count(self, user_id: str) -> int:
        return len(self._subscribers[user_id])

    def events(self, type_: str | None = None) -> list[dict]:
        return [e for _, e in self.published if type_ is None or e["type"] == type_]
