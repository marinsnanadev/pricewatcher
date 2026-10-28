"""The worker side: which events a check publishes (using the recording in-memory bus)."""
import pytest

from app import tasks
from app.celery_app import celery_app
from app.services.scraping import FetchError, ParseError, ScrapeResult
from tests.conftest import make_product


@pytest.fixture(autouse=True)
def eager(session_factory, monkeypatch):
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks.deliver_notification_task, "delay", lambda nid: None)
    yield
    celery_app.conf.task_always_eager = False


def scrape_price(monkeypatch, price):
    monkeypatch.setattr(
        tasks, "scrape", lambda url: ScrapeResult(name="x", store="amazon", price=price, source="json_ld")
    )


def test_price_drop_publishes_checked_event_to_the_owner(db, bus, monkeypatch):
    product = make_product(db, current_price=100.0)
    scrape_price(monkeypatch, 80.0)
    tasks.check_product_task.apply(args=[product.id])

    (user_id, event), = bus.published
    assert user_id == product.user_id
    assert event["type"] == "product.checked"
    data = event["data"]
    assert (data["product_id"], data["status"], data["current_price"]) == (product.id, "success", 80.0)
    assert (data["previous_price"], data["changed"], data["recorded"]) == (100.0, True, True)
    assert data["checked_at"] is not None and data["last_error"] is None


def test_unchanged_price_still_publishes_but_not_recorded(db, bus, monkeypatch):
    from app.models import utcnow

    product = make_product(db, current_price=100.0)
    product.history[0].collected_at = utcnow()
    db.commit()
    scrape_price(monkeypatch, 100.0)
    tasks.check_product_task.apply(args=[product.id])

    data = bus.events("product.checked")[0]["data"]
    assert (data["changed"], data["recorded"]) == (False, False)  # "checked just now", no new point


def test_alert_publishes_alert_triggered_too(db, bus, monkeypatch):
    product = make_product(db, current_price=120.0, target_price=100.0)
    scrape_price(monkeypatch, 90.0)
    tasks.check_product_task.apply(args=[product.id])

    assert [e["type"] for e in bus.events()] == ["product.checked", "alert.triggered"]
    alert = bus.events("alert.triggered")[0]["data"]
    assert alert["reason"] == "target_reached" and alert["price"] == 90.0
    assert alert["product_name"] == "Test product"


def test_parse_error_publishes_error_event(db, bus, monkeypatch):
    product = make_product(db)

    def boom(url):
        raise ParseError("layout changed")

    monkeypatch.setattr(tasks, "scrape", boom)
    tasks.check_product_task.apply(args=[product.id])

    data = bus.events("product.checked")[0]["data"]
    assert data["status"] == "error" and data["last_error"] == "layout changed"
    assert data["consecutive_failures"] == 1


def test_fetch_errors_publish_only_after_the_last_retry(db, bus, monkeypatch):
    product = make_product(db)

    def down(url):
        raise FetchError("timeout")

    monkeypatch.setattr(tasks, "scrape", down)
    tasks.check_product_task.apply(args=[product.id])

    events = bus.events("product.checked")
    assert len(events) == 1  # 4 attempts, one event: no flicker while retrying
    assert events[0]["data"]["status"] == "error"
    assert events[0]["data"]["consecutive_failures"] == 4


def test_recovery_after_retries_publishes_success_only(db, bus, monkeypatch):
    product = make_product(db, current_price=100.0)
    attempts = []

    def flaky(url):
        attempts.append(1)
        if len(attempts) < 3:
            raise FetchError("blip")
        return ScrapeResult(name="x", store="amazon", price=90.0, source="json_ld")

    monkeypatch.setattr(tasks, "scrape", flaky)
    tasks.check_product_task.apply(args=[product.id])
    events = bus.events("product.checked")
    assert len(events) == 1 and events[0]["data"]["status"] == "success"


def test_skipped_products_publish_nothing(db, bus, monkeypatch):
    product = make_product(db, active=False)
    scrape_price(monkeypatch, 50.0)
    tasks.check_product_task.apply(args=[product.id])
    assert bus.published == []


def test_a_dead_redis_never_breaks_the_check(db, monkeypatch):
    from app.services import realtime

    class Broken:
        def publish(self, user_id, event):
            raise ConnectionError("redis down")

    monkeypatch.setattr(realtime, "get_event_bus", lambda: Broken())
    product = make_product(db, current_price=100.0)
    scrape_price(monkeypatch, 70.0)
    result = tasks.check_product_task.apply(args=[product.id]).get()
    assert result["status"] == "success"
    db.refresh(product)
    assert product.current_price == 70.0  # the price was saved regardless
