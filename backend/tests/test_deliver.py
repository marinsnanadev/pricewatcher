import json

import httpx
import pytest

from app import tasks
from app.celery_app import celery_app
from app.models import Notification, utcnow
from app.services.notifiers import webhook
from app.services.notifiers.deliver import MAX_ATTEMPTS, deliver_notification
from app.services.notifiers.errors import DeliveryError
from app.services.notifiers.signing import verify
from app.services.scraping import ScrapeResult
from tests.conftest import make_product


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(webhook, "resolve_ips", lambda host, port: ["93.184.216.34"])


def make_notification(db, channel="webhook", reason="target_reached", with_product=True, **kw):
    product = make_product(db, target_price=100.0)
    user = product.user
    user.webhook_url = "https://hooks.example.com/pw"
    user.webhook_secret = "whsec_test"
    n = Notification(
        user_id=user.id,
        product_id=product.id if with_product else None,
        channel=channel,
        reason=reason,
        price=90.0,
        previous_price=120.0,
        target_price=100.0,
        **kw,
    )
    db.add(n)
    db.commit()
    return n


def ok_transport(captured=None):
    def handler(request):
        if captured is not None:
            captured.append(request)
        return httpx.Response(200)

    return httpx.MockTransport(handler)


def test_webhook_delivery_marks_sent_with_signed_payload(db):
    n = make_notification(db)
    captured = []
    assert deliver_notification(db, n.id, transport=ok_transport(captured)) == "sent"

    db.refresh(n)
    assert (n.status, n.attempts, n.error) == ("sent", 1, None)
    assert n.sent_at is not None
    request = captured[0]
    assert verify("whsec_test", request.headers["x-pricewatcher-signature"], request.content)
    body = json.loads(request.content)
    assert body["id"] == n.id and body["event"] == "price.alert"
    assert body["data"]["price"] == 90.0 and body["data"]["product"]["name"] == "Test product"


def test_email_delivery_uses_console_backend(db, caplog):
    n = make_notification(db, channel="email")
    with caplog.at_level("WARNING"):
        assert deliver_notification(db, n.id) == "sent"
    assert "w@example.com" in caplog.text and "Test product" in caplog.text


def test_test_notification_has_no_product(db):
    n = make_notification(db, reason="test", with_product=False)
    captured = []
    deliver_notification(db, n.id, transport=ok_transport(captured))
    body = json.loads(captured[0].content)
    assert body["event"] == "webhook.test" and body["data"]["product"] is None


def test_already_sent_is_never_sent_twice(db):
    n = make_notification(db)
    deliver_notification(db, n.id, transport=ok_transport())
    sent = []
    assert deliver_notification(db, n.id, transport=ok_transport(sent)) == "already_sent"
    assert sent == []
    db.refresh(n)
    assert n.attempts == 1


def test_failure_keeps_pending_and_records_error(db):
    n = make_notification(db)
    with pytest.raises(DeliveryError):
        deliver_notification(db, n.id, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    db.refresh(n)
    assert (n.status, n.attempts) == ("pending", 1)
    assert "500" in n.error


def test_final_attempt_marks_failed(db):
    n = make_notification(db)
    with pytest.raises(DeliveryError):
        deliver_notification(
            db, n.id, final_attempt=True, transport=httpx.MockTransport(lambda r: httpx.Response(500))
        )
    db.refresh(n)
    assert n.status == "failed"


def test_webhook_removed_after_queueing(db):
    n = make_notification(db)
    n.user.webhook_url = None
    db.commit()
    with pytest.raises(DeliveryError, match="removed"):
        deliver_notification(db, n.id, transport=ok_transport())


def test_missing_notification_is_ignored(db):
    assert deliver_notification(db, "nope") == "missing"


# ---------- Celery tasks (eager) ----------

@pytest.fixture()
def eager(session_factory, monkeypatch):
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    yield
    celery_app.conf.task_always_eager = False


def test_delivery_task_retries_then_marks_failed(db, eager, monkeypatch):
    n = make_notification(db)
    calls = []

    def always_500(url, secret, payload, delivery_id=None, transport=None):
        calls.append(1)
        raise DeliveryError("Webhook answered HTTP 500")

    monkeypatch.setattr(webhook, "send_webhook", always_500)
    tasks.deliver_notification_task.apply(args=[n.id])

    assert len(calls) == MAX_ATTEMPTS
    db.refresh(n)
    assert (n.status, n.attempts) == ("failed", MAX_ATTEMPTS)


def test_delivery_task_recovers_after_transient_failure(db, eager, monkeypatch):
    n = make_notification(db)
    calls = []

    def flaky(url, secret, payload, delivery_id=None, transport=None):
        calls.append(1)
        if len(calls) < 3:
            raise DeliveryError("Webhook timed out")

    monkeypatch.setattr(webhook, "send_webhook", flaky)
    tasks.deliver_notification_task.apply(args=[n.id])
    db.refresh(n)
    assert (n.status, n.attempts) == ("sent", 3)


def test_check_task_queues_delivery_after_alert(db, eager, monkeypatch):
    product = make_product(db, current_price=120.0, target_price=100.0)
    monkeypatch.setattr(
        tasks, "scrape", lambda url: ScrapeResult(name="x", store="amazon", price=90.0, source="json_ld")
    )
    queued = []
    monkeypatch.setattr(tasks.deliver_notification_task, "delay", lambda nid: queued.append(nid))
    tasks.check_product_task.apply(args=[product.id])

    row = db.query(Notification).one()
    assert queued == [row.id]


def test_alert_survives_a_broker_outage(db, eager, monkeypatch):
    """The outbox row is committed with the price, so a dead broker loses nothing."""
    product = make_product(db, current_price=120.0, target_price=100.0)
    monkeypatch.setattr(
        tasks, "scrape", lambda url: ScrapeResult(name="x", store="amazon", price=90.0, source="json_ld")
    )

    def broker_down(nid):
        raise ConnectionError("redis down")

    monkeypatch.setattr(tasks.deliver_notification_task, "delay", broker_down)
    result = tasks.check_product_task.apply(args=[product.id]).get()
    assert result["status"] == "success"
    row = db.query(Notification).one()
    assert row.status == "pending"  # the sweeper will pick it up


def test_sweeper_only_requeues_old_pending(db, eager, monkeypatch):
    from datetime import timedelta

    old = make_notification(db, created_at=utcnow() - timedelta(minutes=10))
    fresh = make_notification(db, created_at=utcnow())
    done = make_notification(db, created_at=utcnow() - timedelta(minutes=10), status="sent")
    ancient = make_notification(db, created_at=utcnow() - timedelta(days=5))

    queued = []
    monkeypatch.setattr(tasks.deliver_notification_task, "delay", lambda nid: queued.append(nid))
    assert tasks.retry_pending_notifications.apply().get() == 1
    assert queued == [old.id]
    assert fresh.id not in queued and done.id not in queued and ancient.id not in queued


def test_beat_schedules_the_sweeper():
    entry = celery_app.conf.beat_schedule["retry-pending-notifications"]
    assert entry["task"] in celery_app.tasks
