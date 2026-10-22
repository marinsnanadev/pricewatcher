from celery import Celery

from .config import settings

celery_app = Celery("pricewatcher", broker=settings.redis_url, include=["app.tasks"])

celery_app.conf.update(
    timezone="UTC",
    task_ignore_result=True,  # results live in the scrape_runs table, not in Redis
    task_acks_late=True,  # if a worker dies mid-job, the job goes back to the queue
    worker_prefetch_multiplier=1,  # long scrapes: don't let one worker hoard jobs
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "dispatch-due-products": {
            "task": "app.tasks.dispatch_due",
            "schedule": float(settings.dispatch_every_seconds),
        },
        "retry-pending-notifications": {
            "task": "app.tasks.retry_pending_notifications",
            "schedule": 300.0,
        },
    },
)
