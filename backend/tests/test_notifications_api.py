from app.models import Notification
from tests.conftest import signup_and_login

URL = "https://www.mercadolivre.com.br/fone-bluetooth-pro"


def put(client, auth, **body):
    return client.put("/settings/notifications", json=body, headers=auth)


def test_default_settings(client, auth):
    data = client.get("/settings/notifications", headers=auth).json()
    assert data == {
        "email_enabled": True,
        "email": "nana@example.com",
        "webhook_url": None,
        "webhook_secret": None,
    }


def test_settings_require_auth(client):
    assert client.get("/settings/notifications").status_code == 401
    assert client.put("/settings/notifications", json={}).status_code == 401
    assert client.get("/notifications").status_code == 401


def test_setting_a_webhook_generates_a_secret(client, auth):
    data = put(client, auth, webhook_url="https://hooks.example.com/pw").json()
    assert data["webhook_url"] == "https://hooks.example.com/pw"
    assert data["webhook_secret"].startswith("whsec_") and len(data["webhook_secret"]) > 20

    # saving again keeps the same secret
    again = put(client, auth, webhook_url="https://hooks.example.com/other").json()
    assert again["webhook_secret"] == data["webhook_secret"]


def test_removing_the_webhook_clears_the_secret(client, auth):
    put(client, auth, webhook_url="https://hooks.example.com/pw")
    data = put(client, auth, webhook_url=None).json()
    assert data["webhook_url"] is None and data["webhook_secret"] is None


def test_partial_update_does_not_touch_other_fields(client, auth):
    put(client, auth, webhook_url="https://hooks.example.com/pw")
    data = put(client, auth, email_enabled=False).json()
    assert data["email_enabled"] is False
    assert data["webhook_url"] == "https://hooks.example.com/pw"


def test_unsafe_webhook_urls_are_rejected(client, auth):
    for url in ["http://localhost:3000/x", "http://169.254.169.254/", "ftp://x.com", "http://10.0.0.1/"]:
        res = put(client, auth, webhook_url=url)
        assert res.status_code == 422, url
    assert client.get("/settings/notifications", headers=auth).json()["webhook_url"] is None


def test_rotate_secret(client, auth):
    assert client.post("/settings/notifications/rotate-secret", headers=auth).status_code == 409
    first = put(client, auth, webhook_url="https://hooks.example.com/pw").json()["webhook_secret"]
    second = client.post("/settings/notifications/rotate-secret", headers=auth).json()["webhook_secret"]
    assert second != first and second.startswith("whsec_")


def test_test_notification_queues_every_enabled_channel(client, auth, deliveries):
    put(client, auth, webhook_url="https://hooks.example.com/pw")
    res = client.post("/settings/notifications/test", headers=auth)
    assert res.status_code == 202
    assert sorted(res.json()["channels"]) == ["email", "webhook"]
    assert len(deliveries) == 2

    rows = client.get("/notifications", headers=auth).json()
    assert {r["reason"] for r in rows} == {"test"}
    assert {r["product_id"] for r in rows} == {None}


def test_test_notification_needs_a_channel(client, auth, deliveries):
    put(client, auth, email_enabled=False)
    assert client.post("/settings/notifications/test", headers=auth).status_code == 409
    assert deliveries == []


def test_test_notification_reports_queue_down(client, auth):
    from app.main import app
    from app.routers.notifications import get_enqueue_delivery

    def broken(nid):
        raise ConnectionError("redis down")

    app.dependency_overrides[get_enqueue_delivery] = lambda: broken
    assert client.post("/settings/notifications/test", headers=auth).status_code == 503


def test_notification_history_is_private_and_filterable(client, auth, session_factory):
    p1 = client.post("/products", json={"url": URL}, headers=auth).json()["id"]
    p2 = client.post("/products", json={"url": URL + "-2"}, headers=auth).json()["id"]
    me = client.get("/auth/me", headers=auth).json()["id"]

    other = signup_and_login(client, email="other@example.com")
    other_id = client.get("/auth/me", headers=other).json()["id"]

    with session_factory() as db:
        db.add_all([
            Notification(user_id=me, product_id=p1, channel="email", reason="target_reached", price=90.0),
            Notification(user_id=me, product_id=p2, channel="email", reason="target_reached", price=80.0),
            Notification(user_id=other_id, product_id=None, channel="email", reason="test"),
        ])
        db.commit()

    mine = client.get("/notifications", headers=auth).json()
    assert len(mine) == 2
    only_p1 = client.get(f"/notifications?product_id={p1}", headers=auth).json()
    assert [n["price"] for n in only_p1] == [90.0]
    assert len(client.get("/notifications", headers=other).json()) == 1


def test_target_price_controls_alert_state(client, auth, session_factory):
    from app.models import Product

    # fake scraper returns 149.9
    above = client.post("/products", json={"url": URL, "target_price": 100}, headers=auth).json()
    below = client.post("/products", json={"url": URL + "-b", "target_price": 200}, headers=auth).json()
    none = client.post("/products", json={"url": URL + "-c"}, headers=auth).json()

    with session_factory() as db:
        armed = {p.id: p.alert_armed for p in db.query(Product).all()}
    assert armed[above["id"]] is True  # 149.9 > 100: waiting for a drop
    assert armed[below["id"]] is False  # already under 200: no instant alert
    assert armed[none["id"]] is True

    # raising the target above the price disarms; lowering it re-arms
    client.patch(f"/products/{above['id']}", json={"target_price": 500}, headers=auth)
    client.patch(f"/products/{below['id']}", json={"target_price": 50}, headers=auth)
    with session_factory() as db:
        armed = {p.id: p.alert_armed for p in db.query(Product).all()}
    assert armed[above["id"]] is False
    assert armed[below["id"]] is True
