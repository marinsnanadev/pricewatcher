from datetime import timedelta

from app.config import settings
from app.models import Notification, utcnow
from app.services.alerts import FURTHER_DROP, TARGET_REACHED, decide, initial_armed
from app.services.checker import check_product
from app.services.scraping import ScrapeResult
from tests.conftest import make_product


def run_check(db, product, price):
    fn = lambda url: ScrapeResult(name="x", store="amazon", price=price, source="json_ld")  # noqa: E731
    return check_product(db, product.id, scrape_fn=fn)


def alerts(db):
    return db.query(Notification).order_by(Notification.created_at).all()


def test_initial_armed():
    assert initial_armed(None, 50) is True  # no target
    assert initial_armed(100, 150) is True  # still above target
    assert initial_armed(100, 90) is False  # already under: wait for a climb first
    assert initial_armed(100, 100) is False


def test_alert_when_price_reaches_target(db):
    product = make_product(db, current_price=120.0, target_price=100.0, alert_armed=True)
    outcome = run_check(db, product, 95.0)

    rows = alerts(db)
    assert len(rows) == 1  # email only (no webhook configured)
    n = rows[0]
    assert (n.channel, n.reason, n.price, n.previous_price, n.target_price, n.status) == (
        "email", TARGET_REACHED, 95.0, 120.0, 100.0, "pending",
    )
    assert outcome.notification_ids == [n.id]
    db.refresh(product)
    assert product.alert_armed is False
    assert product.last_alert_price == 95.0


def test_no_alert_without_target_or_above_target(db):
    no_target = make_product(db, current_price=120.0, target_price=None)
    run_check(db, no_target, 10.0)
    above = make_product(db, current_price=200.0, target_price=100.0)
    run_check(db, above, 150.0)
    assert alerts(db) == []


def test_same_low_price_does_not_alert_twice(db):
    product = make_product(db, current_price=120.0, target_price=100.0)
    run_check(db, product, 95.0)
    run_check(db, product, 95.0)
    run_check(db, product, 94.0)  # lower, but not meaningfully, and within the cooldown
    assert len(alerts(db)) == 1


def test_further_drop_needs_both_big_drop_and_cooldown(db):
    product = make_product(db, current_price=120.0, target_price=100.0)
    run_check(db, product, 90.0)  # alert 1
    big_drop = 90.0 * (1 - settings.alert_further_drop_percent / 100) - 1

    run_check(db, product, big_drop)  # big drop but still inside the cooldown
    assert len(alerts(db)) == 1

    db.refresh(product)
    product.last_alert_at = utcnow() - timedelta(hours=settings.alert_cooldown_hours + 1)
    db.commit()
    run_check(db, product, big_drop)
    rows = alerts(db)
    assert len(rows) == 2 and rows[1].reason == FURTHER_DROP


def test_cooldown_over_but_tiny_drop_stays_quiet(db):
    product = make_product(db, current_price=120.0, target_price=100.0)
    run_check(db, product, 90.0)
    db.refresh(product)
    product.last_alert_at = utcnow() - timedelta(days=3)
    db.commit()
    run_check(db, product, 89.5)
    assert len(alerts(db)) == 1


def test_rearms_after_price_climbs_back_over_target(db):
    product = make_product(db, current_price=120.0, target_price=100.0)
    run_check(db, product, 90.0)  # alert
    run_check(db, product, 130.0)  # back above target -> re-armed
    run_check(db, product, 99.0)  # crosses again -> alert again
    assert [n.reason for n in alerts(db)] == [TARGET_REACHED, TARGET_REACHED]


def test_one_notification_per_enabled_channel(db):
    product = make_product(db, current_price=120.0, target_price=100.0)
    product.user.webhook_url = "https://hooks.example.com/pw"
    product.user.webhook_secret = "whsec_x"
    db.commit()
    run_check(db, product, 90.0)
    assert sorted(n.channel for n in alerts(db)) == ["email", "webhook"]


def test_email_can_be_turned_off(db):
    product = make_product(db, current_price=120.0, target_price=100.0)
    product.user.notify_email = False
    product.user.webhook_url = "https://hooks.example.com/pw"
    db.commit()
    run_check(db, product, 90.0)
    assert [n.channel for n in alerts(db)] == ["webhook"]


def test_no_channels_means_no_alert_and_stays_armed(db):
    product = make_product(db, current_price=120.0, target_price=100.0)
    product.user.notify_email = False
    db.commit()
    run_check(db, product, 90.0)
    assert alerts(db) == []
    db.refresh(product)
    assert product.alert_armed is True  # user enables a channel later -> still gets it


def test_decide_is_pure_and_handles_naive_datetimes(db):
    product = make_product(db, target_price=100.0, alert_armed=False)
    product.last_alert_price = 90.0
    product.last_alert_at = utcnow().replace(tzinfo=None) - timedelta(days=1)  # as SQLite returns it
    assert decide(product, 85.0, utcnow()) == FURTHER_DROP
    assert decide(product, 89.0, utcnow()) is None
