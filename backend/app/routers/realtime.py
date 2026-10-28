import asyncio
import json
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from ..config import settings
from ..database import get_session_factory
from ..models import User
from ..security import decode_access_token
from ..services.realtime import get_event_bus

log = logging.getLogger(__name__)
router = APIRouter(tags=["realtime"])

UNAUTHORIZED = 4401  # app-level close code: "don't retry, sign in again"


async def authenticate(ws: WebSocket, session_factory) -> str | None:
    """First message must be {"type":"auth","token":"<jwt>"}, sent within a few seconds.
    The token travels in the message, not the URL, so it never lands in access logs."""
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=settings.ws_auth_timeout_seconds)
        message = json.loads(raw)
    except (asyncio.TimeoutError, ValueError, WebSocketDisconnect, RuntimeError):
        return None
    if not isinstance(message, dict) or message.get("type") != "auth":
        return None
    token = message.get("token")
    user_id = decode_access_token(token) if isinstance(token, str) else None
    if user_id is None:
        return None
    with session_factory() as db:  # short-lived: we don't hold a DB connection for the whole socket
        return user_id if db.get(User, user_id) else None


async def forward_events(ws: WebSocket, subscription) -> None:
    while True:
        event = await subscription.next(settings.ws_heartbeat_seconds)
        # nothing for a while -> heartbeat; also how we notice a dead connection
        await ws.send_json(event if event is not None else {"type": "heartbeat"})


async def read_client(ws: WebSocket) -> None:
    while True:
        text = await ws.receive_text()  # raises WebSocketDisconnect when the client leaves
        if text == "ping":
            await ws.send_json({"type": "pong"})


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    bus=Depends(get_event_bus),
    session_factory=Depends(get_session_factory),
):
    await ws.accept()
    user_id = await authenticate(ws, session_factory)
    if user_id is None:
        await ws.close(code=UNAUTHORIZED)
        return

    try:
        async with bus.subscribe(user_id) as subscription:
            # "ready" goes out only after we're subscribed, so the client can trust that
            # everything that happens from now on will reach it
            await ws.send_json({"type": "ready"})
            tasks = [
                asyncio.create_task(forward_events(ws, subscription)),
                asyncio.create_task(read_client(ws)),
            ]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()  # re-raises WebSocketDisconnect & co. for the handler below
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except (WebSocketDisconnect, RuntimeError):
        pass  # client closed the tab; nothing to clean up beyond the subscription
    except Exception:
        log.exception("websocket crashed")
        try:
            await ws.close(code=1011)
        except RuntimeError:
            pass
