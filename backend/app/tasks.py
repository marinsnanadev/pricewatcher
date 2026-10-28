import logging
from datetime import timedelta

from sqlalchemy import select

from .celery_app import celery_app
from .database import SessionLocal
from .models import Notification, Product, utcnow
from .services.checker import check_product
from .services.notifiers.deliver import MAX_ATTEMPTS, deliver_notification
from .services.notifiers.errors import DeliveryError
from .services.scheduling import dispatch_due_products
from .services import realtime
from .services.scraping import FetchError, ScrapeError, scrape

log = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.check_product",
    autoretry_for=(FetchError,),  # network trouble / blocks: worth another try
    retry_backoff=30,  # 30s, 60s, 120s... (doubles each time)
    retry_backoff_max=900,  # never wait more than 15 min
    retry_jitter=True,  # randomize the wait so retries don't pile up
    max_retries=3,
)
def check_product_task(self, product_id: str, trigger: str = "scheduled"):
    final_attempt = self.request.retries >= self.max_retries
    with SessionLocal() as db:
        try:
            outcome = check_product(
                db,
                product_id,
                trigger=trigger,
                attempt=self.request.retries + 1,
                scrape_fn=scrape,
            )
        except FetchError:
            if final_attempt:  # still retrying? stay quiet, the next attempt may fix it
                publish_checked(db, product_id, status="error")
            raise  # autoretry_for takes it from here
        except ScrapeError as exc:
            # parse/unsupported errors won't fix themselves on retry; already recorded
            log.warning("product %s: %s", product_id, exc)
            publish_checked(db, product_id, status="error")
            return {"status": "error", "error": str(exc)}

        if outcome.status == "success":
            publish_checked(db, product_id, status="success", outcome=outcome)

    # Queue deliveries only after the alert rows are committed. If the broker hiccups
    # here nothing is lost: pending rows are picked up by retry_pending_notifications.
    for notification_id in outcome.notification_ids:
        try:
            deliver_notification_task.delay(notification_id)
        except Exception:
            log.exception("couldn't queue notification %s (sweeper will retry)", notification_id)
    return {"status": outcome.status, "changed": outcome.changed}


def publish_checked(db, product_id: str, status: str, outcome=None) -> None:
    """Tells the user's open browser tabs what just happened (best-effort)."""
    product = db.get(Product, product_id)
    if product is None:
        return
    realtime.publish_event(
        product.user_id,
        "product.checked",
        realtime.checked_event(
            product,
            status,
            previous_price=outcome.price_before if outcome else None,
            changed=outcome.changed if outcome else False,
            recorded=outcome.recorded if outcome else False,
        ),
    )
    if outcome and outcome.alert_reason:
        realtime.publish_event(
            product.user_id,
            "alert.triggered",
            realtime.alert_event(product, outcome.alert_reason, outcome.price_after),
        )


@celery_app.task(
    bind=True,
    name="app.tasks.deliver_notification",
    autoretry_for=(DeliveryError,),
    retry_backoff=60,  # 1m, 2m, 4m, 8m, 16m
    retry_backoff_max=1800,
    retry_jitter=True,
    max_retries=MAX_ATTEMPTS - 1,
)
def deliver_notification_task(self, notification_id: str):
    with SessionLocal() as db:
        return deliver_notification(
            db, notification_id, final_attempt=self.request.retries >= self.max_retries
        )


@celery_app.task(name="app.tasks.retry_pending_notifications")
def retry_pending_notifications():
    """Safety net (runs via beat): pending notifications nobody is working on, e.g.
    the broker was down when they were created. Old enough to not race with the
    normal flow, and recent enough to not resurrect ancient alerts."""
    now = utcnow()
    with SessionLocal() as db:
        ids = db.scalars(
            select(Notification.id).where(
                Notification.status == "pending",
                Notification.created_at <= now - timedelta(minutes=5),
                Notification.created_at >= now - timedelta(days=2),
            ).limit(100)
        ).all()
    for notification_id in ids:
        deliver_notification_task.delay(notification_id)
    return len(ids)


@celery_app.task(name="app.tasks.dispatch_due")
def dispatch_due():
    """Runs every minute via celery beat."""

    def enqueue(product_id: str, countdown: int) -> None:
        check_product_task.apply_async(args=[product_id], countdown=countdown)

    with SessionLocal() as db:
        count = dispatch_due_products(db, enqueue)
    if count:
        log.info("enqueued %d product checks", count)
    return count
