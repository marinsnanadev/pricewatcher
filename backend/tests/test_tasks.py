"""Runs the real Celery tasks in eager mode (in-process, no Redis needed)."""
import pytest

from app import tasks
from app.celery_app import celery_app
from app.models import Product, ScrapeRun, utcnow
from app.services.scraping import FetchError, ParseError, ScrapeResult
from tests.conftest import make_product


@pytest.fixture(autouse=True)
def eager(session_factory, monkeypatch):
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    yield
    celery_app.conf.task_always_eager = False


def test_task_checks_product(db, monkeypatch):
    product = make_product(db, current_price=100.0)
    monkeypatch.setattr(
        tasks, "scrape", lambda url: ScrapeResult(name="x", store="amazon", price=70.0, source="markup")
    )
    result = tasks.check_product_task.apply(args=[product.id]).get()
    assert result == {"status": "success", "changed": True}
    db.refresh(product)
    assert product.current_price == 70.0


def test_parse_errors_are_recorded_but_not_retried(db, monkeypatch):
    product = make_product(db)
    calls = []

    def scrape(url):
        calls.append(url)
        raise ParseError("layout changed")

    monkeypatch.setattr(tasks, "scrape", scrape)
    result = tasks.check_product_task.apply(args=[product.id]).get()
    assert result["status"] == "error"
    assert len(calls) == 1
    assert db.query(ScrapeRun).one().error_type == "ParseError"


def test_fetch_errors_are_retried_then_give_up(db, monkeypatch):
    product = make_product(db)
    calls = []

    def scrape(url):
        calls.append(url)
        raise FetchError("timeout")

    monkeypatch.setattr(tasks, "scrape", scrape)
    tasks.check_product_task.apply(args=[product.id])

    assert len(calls) == 4  # 1 try + 3 retries
    runs = db.query(ScrapeRun).order_by(ScrapeRun.attempt).all()
    assert [r.attempt for r in runs] == [1, 2, 3, 4]
    assert all(r.status == "error" for r in runs)


def test_retry_that_succeeds_stops_retrying(db, monkeypatch):
    product = make_product(db, current_price=100.0)
    attempts = []

    def flaky(url):
        attempts.append(1)
        if len(attempts) < 3:
            raise FetchError("blip")
        return ScrapeResult(name="x", store="amazon", price=90.0, source="json_ld")

    monkeypatch.setattr(tasks, "scrape", flaky)
    tasks.check_product_task.apply(args=[product.id])
    assert len(attempts) == 3
    db.refresh(product)
    assert product.current_price == 90.0
    assert product.consecutive_failures == 0  # reset by the success


def test_dispatch_task_enqueues_due_products(db, monkeypatch):
    make_product(db, next_check_at=None)
    make_product(db, next_check_at=utcnow().replace(year=2099))
    queued = []
    monkeypatch.setattr(
        tasks.check_product_task, "apply_async", lambda args, countdown: queued.append((args, countdown))
    )
    assert tasks.dispatch_due.apply().get() == 1
    assert len(queued) == 1


def test_beat_schedule_points_at_a_registered_task():
    entry = celery_app.conf.beat_schedule["dispatch-due-products"]
    assert entry["task"] in celery_app.tasks
