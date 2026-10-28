import time
from contextlib import contextmanager

import pytest
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.security import create_access_token
from tests.conftest import signup_and_login


def user_id_and_token(client, email="nana@example.com"):
    headers = signup_and_login(client, email=email)
    me = client.get("/auth/me", headers=headers).json()
    return me["id"], headers["Authorization"].split()[1]


@contextmanager
def socket(client, bus, user_id, token):
    """Connects, authenticates, waits for "ready" and, when leaving, waits until the server
    finished cleaning up. (The TestClient cancels the app the instant the block ends, which
    would otherwise race with the server's own shutdown; real servers don't do that.)"""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json() == {"type": "ready"}
        try:
            yield ws
        finally:
            ws.close()
            deadline = time.time() + 3
            while bus.subscriber_count(user_id) and time.time() < deadline:
                time.sleep(0.01)


def test_valid_auth_gets_ready_then_events(client, bus):
    user_id, token = user_id_and_token(client)
    with socket(client, bus, user_id, token) as ws:
        assert bus.subscriber_count(user_id) == 1  # "ready" is only sent once we're subscribed
        bus.publish(user_id, {"type": "product.checked", "data": {"current_price": 80.0}})
        assert ws.receive_json() == {"type": "product.checked", "data": {"current_price": 80.0}}
    assert bus.subscriber_count(user_id) == 0  # cleaned up after the client left


def test_users_only_receive_their_own_events(client, bus):
    mine, my_token = user_id_and_token(client)
    other, _ = user_id_and_token(client, email="other@example.com")
    with socket(client, bus, mine, my_token) as ws:
        bus.publish(other, {"type": "product.checked", "data": {"secret": True}})
        bus.publish(mine, {"type": "alert.triggered", "data": {}})
        # the other user's event never shows up; ours is the first thing delivered
        assert ws.receive_json()["type"] == "alert.triggered"


def test_two_tabs_both_receive(client, bus):
    user_id, token = user_id_and_token(client)
    with socket(client, bus, user_id, token) as a, socket(client, bus, user_id, token) as b:
        assert bus.subscriber_count(user_id) == 2
        bus.publish(user_id, {"type": "product.checked", "data": {}})
        assert a.receive_json()["type"] == "product.checked"
        assert b.receive_json()["type"] == "product.checked"


@pytest.mark.parametrize(
    "first_message",
    [
        {"type": "auth", "token": "garbage"},
        {"type": "auth"},
        {"type": "auth", "token": 123},
        {"type": "hello", "token": "x"},
        [1, 2],
    ],
)
def test_bad_auth_is_closed_with_4401(client, first_message):
    with client.websocket_connect("/ws") as ws:
        ws.send_json(first_message)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4401


def test_non_json_first_message_is_rejected(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text("hello")
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4401


def test_token_of_a_deleted_user_is_rejected(client):
    token = create_access_token("00000000-0000-0000-0000-000000000000")
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4401


def test_not_authenticating_in_time_closes_the_socket(client, monkeypatch):
    monkeypatch.setattr(settings, "ws_auth_timeout_seconds", 0.2)
    with client.websocket_connect("/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4401


def test_ping_gets_pong(client, bus):
    user_id, token = user_id_and_token(client)
    with socket(client, bus, user_id, token) as ws:
        ws.send_text("ping")
        assert ws.receive_json() == {"type": "pong"}


def test_idle_connections_get_heartbeats(client, bus, monkeypatch):
    monkeypatch.setattr(settings, "ws_heartbeat_seconds", 0.1)
    user_id, token = user_id_and_token(client)
    with socket(client, bus, user_id, token) as ws:
        assert ws.receive_json() == {"type": "heartbeat"}
        assert ws.receive_json() == {"type": "heartbeat"}


def test_events_published_before_connecting_are_not_replayed(client, bus):
    """Pub/sub is live-only. That's why the frontend re-syncs from REST on every (re)connect."""
    user_id, token = user_id_and_token(client)
    bus.publish(user_id, {"type": "product.checked", "data": {"old": True}})
    with socket(client, bus, user_id, token) as ws:
        bus.publish(user_id, {"type": "alert.triggered", "data": {}})
        assert ws.receive_json()["type"] == "alert.triggered"
