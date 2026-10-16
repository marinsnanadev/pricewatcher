from datetime import timedelta

import pytest

from app.models import ScrapeRun, utcnow
from app.services.checker import check_product
from app.services.scraping import FetchError, ParseError, ScrapeResult
from tests.conftest import make_product


def scrape_returning(price):
    return lambda url: ScrapeResult(name="x", store="amazon", price=price, source="json_ld")


def scrape_raising(exc):
    def fn(url):
        raise exc

    return fn


def test_price_drop_updates_product_history_and_run(db):
    product = make_product(db, current_price=100.0)
    outcome = check_product(db, product.id, scrape_fn=scrape_returning(80.0))

    assert (outcome.price_before, outcome.price_after, outcome.changed) == (100.0, 80.0, True)
    db.refresh(product)
    assert product.current_price == 80.0
    assert [h.price for h in product.history] == [100.0, 80.0]
    assert product.last_checked_at is not None

    run = db.query(ScrapeRun).one()
    assert (run.status, run.price, run.source, run.trigger, run.attempt) == (
        "success", 80.0, "json_ld", "scheduled", 1,
    )


def test_unchanged_price_does_not_bloat_history(db):
    product = make_product(db, current_price=100.0)
    # the seed history point is "now", so no heartbeat is due
    product.history[0].collected_at = utcnow()
    db.commit()

    outcome = check_product(db, product.id, scrape_fn=scrape_returning(100.0))
    assert outcome.changed is False
    db.refresh(product)
    assert len(product.history) == 1
    assert db.query(ScrapeRun).count() == 1  # but the run is always recorded


def test_unchanged_price_adds_a_daily_heartbeat(db):
    product = make_product(db, current_price=100.0)
    product.history[0].collected_at = utcnow() - timedelta(hours=25)
    db.commit()

    check_product(db, product.id, scrape_fn=scrape_returning(100.0))
    db.refresh(product)
    assert len(product.history) == 2


def test_success_clears_previous_error(db):
    product = make_product(db, last_error="boom", consecutive_failures=3)
    check_product(db, product.id, scrape_fn=scrape_returning(100.0))
    db.refresh(product)
    assert product.last_error is None
    assert product.consecutive_failures == 0


def test_failure_is_recorded_and_reraised(db):
    product = make_product(db)
    with pytest.raises(ParseError):
        check_product(db, product.id, scrape_fn=scrape_raising(ParseError("no price here")), attempt=2)

    db.refresh(product)
    assert product.last_error == "no price here"
    assert product.consecutive_failures == 1
    assert product.current_price == 100.0  # untouched

    run = db.query(ScrapeRun).one()
    assert (run.status, run.error_type, run.error_message, run.attempt) == (
        "error", "ParseError", "no price here", 2,
    )


def test_failures_accumulate(db):
    product = make_product(db)
    for _ in range(3):
        with pytest.raises(FetchError):
            check_product(db, product.id, scrape_fn=scrape_raising(FetchError("timeout")))
    db.refresh(product)
    assert product.consecutive_failures == 3


def test_inactive_or_missing_products_are_skipped(db):
    product = make_product(db, active=False)
    boom = scrape_raising(AssertionError("must not scrape"))
    assert check_product(db, product.id, scrape_fn=boom).status == "skipped"
    assert check_product(db, "does-not-exist", scrape_fn=boom).status == "skipped"
    assert db.query(ScrapeRun).count() == 0
