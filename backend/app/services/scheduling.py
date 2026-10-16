import random
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Product, utcnow


def next_check_time(product: Product, now: datetime) -> datetime:
    """now + the product's interval, ±10% so jobs drift apart instead of
    all hitting the stores at the same minute."""
    seconds = product.check_interval_minutes * 60 * random.uniform(0.9, 1.1)
    return now + timedelta(seconds=seconds)


def dispatch_due_products(
    db: Session,
    enqueue: Callable[[str, int], None],
    now: datetime | None = None,
) -> int:
    """Finds active products whose time has come and enqueues one job each.

    `enqueue(product_id, countdown_seconds)` hands the job to the queue.
    next_check_at is pushed forward right away, so running this every minute
    never enqueues the same product twice.
    Returns how many jobs were enqueued.
    """
    now = now or utcnow()
    due = db.scalars(
        select(Product)
        .where(
            Product.active.is_(True),
            or_(Product.next_check_at.is_(None), Product.next_check_at <= now),
        )
        .order_by(Product.next_check_at.asc())
        .limit(settings.dispatch_batch_size)
    ).all()

    for product in due:
        enqueue(product.id, random.randint(0, settings.start_jitter_seconds))
        product.next_check_at = next_check_time(product, now)
        db.commit()  # per product: a crash midway doesn't lose the ones already queued
    return len(due)
