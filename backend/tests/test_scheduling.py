from datetime import timedelta

from app.config import settings
from app.models import utcnow
from app.services.scheduling import dispatch_due_products
from tests.conftest import make_product


def run_dispatch(db, now=None):
    calls = []
    count = dispatch_due_products(db, lambda pid, countdown: calls.append((pid, countdown)), now=now)
    return count, calls


def test_only_due_active_products_are_enqueued(db):
    now = utcnow()
    due = make_product(db, next_check_at=now - timedelta(minutes=1))
    never_checked = make_product(db, next_check_at=None)
    later = make_product(db, next_check_at=now + timedelta(hours=1))
    paused = make_product(db, next_check_at=now - timedelta(hours=1), active=False)

    count, calls = run_dispatch(db, now)
    assert count == 2
    ids = {pid for pid, _ in calls}
    assert ids == {due.id, never_checked.id}
    assert later.id not in ids and paused.id not in ids


def test_running_twice_does_not_enqueue_twice(db):
    now = utcnow()
    make_product(db, next_check_at=None)
    assert run_dispatch(db, now)[0] == 1
    assert run_dispatch(db, now + timedelta(minutes=1))[0] == 0


def test_next_check_uses_interval_with_jitter(db):
    now = utcnow()
    product = make_product(db, next_check_at=None, check_interval_minutes=60)
    run_dispatch(db, now)
    db.refresh(product)
    wait = (product.next_check_at.replace(tzinfo=now.tzinfo) - now).total_seconds()
    assert 60 * 60 * 0.9 <= wait <= 60 * 60 * 1.1


def test_start_countdown_is_jittered_within_limit(db):
    now = utcnow()
    for _ in range(20):
        make_product(db, next_check_at=None)
    _, calls = run_dispatch(db, now)
    countdowns = [c for _, c in calls]
    assert all(0 <= c <= settings.start_jitter_seconds for c in countdowns)
    assert len(set(countdowns)) > 1  # not all the same second


def test_due_again_after_interval_passes(db):
    now = utcnow()
    make_product(db, next_check_at=None, check_interval_minutes=15)
    run_dispatch(db, now)
    assert run_dispatch(db, now + timedelta(minutes=20))[0] == 1
