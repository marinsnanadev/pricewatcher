import logging

from .celery_app import celery_app
from .database import SessionLocal
from .services.checker import check_product
from .services.scheduling import dispatch_due_products
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
            raise  # autoretry_for takes it from here
        except ScrapeError as exc:
            # parse/unsupported errors won't fix themselves on retry; already recorded
            log.warning("product %s: %s", product_id, exc)
            return {"status": "error", "error": str(exc)}
    return {"status": outcome.status, "changed": outcome.changed}


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
