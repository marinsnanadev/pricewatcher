"""The heart of the scheduled jobs: check ONE product, record what happened.

Plain functions that take a DB session, so they are testable without Celery
or Redis. The Celery task in app/tasks.py is just a thin wrapper around this.
"""
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import PriceHistory, Product, ScrapeRun, utcnow
from .scraping import ScrapeError, scrape

# Even if the price didn't move, keep one point per day so the chart shows
# the product was being watched (no giant flat gaps).
HEARTBEAT = timedelta(hours=24)


@dataclass
class CheckOutcome:
    product_id: str
    status: str  # success | skipped
    price_before: float | None = None
    price_after: float | None = None

    @property
    def changed(self) -> bool:
        return (
            self.price_before is not None
            and self.price_after is not None
            and round(self.price_before, 2) != round(self.price_after, 2)
        )


def _as_aware(dt: datetime) -> datetime:
    # SQLite hands datetimes back without tzinfo; everything we store is UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


def record_price(product: Product, price: float, now: datetime) -> None:
    """Updates current_price and appends to the history when it's worth it."""
    last = product.history[-1] if product.history else None
    moved = last is None or round(last.price, 2) != round(price, 2)
    stale = last is not None and now - _as_aware(last.collected_at) >= HEARTBEAT
    if moved or stale:
        product.history.append(PriceHistory(price=price, collected_at=now))
    product.current_price = price
    product.last_error = None
    product.consecutive_failures = 0
    product.last_checked_at = now


def check_product(
    db: Session,
    product_id: str,
    *,
    trigger: str = "scheduled",
    attempt: int = 1,
    scrape_fn=scrape,
) -> CheckOutcome:
    """Scrapes the product once and stores the result (run + price + errors).

    Re-raises ScrapeError after recording it, so the caller (Celery) can decide
    whether to retry.
    """
    product = db.get(Product, product_id)
    if product is None or not product.active:
        return CheckOutcome(product_id, "skipped")

    before = product.current_price
    started = utcnow()
    clock = time.perf_counter()
    run = ScrapeRun(
        product_id=product.id,
        store=product.store,
        trigger=trigger,
        attempt=attempt,
        started_at=started,
    )

    try:
        result = scrape_fn(product.url)
    except ScrapeError as exc:
        run.status = "error"
        run.error_type = exc.__class__.__name__
        run.error_message = str(exc)[:1000]
        run.duration_ms = int((time.perf_counter() - clock) * 1000)
        product.last_error = str(exc)[:1000]
        product.consecutive_failures += 1
        product.last_checked_at = started
        db.add(run)
        db.commit()
        raise

    run.status = "success"
    run.price = result.price
    run.source = result.source
    run.duration_ms = int((time.perf_counter() - clock) * 1000)
    record_price(product, result.price, started)
    db.add(run)
    db.commit()
    return CheckOutcome(product.id, "success", price_before=before, price_after=result.price)
