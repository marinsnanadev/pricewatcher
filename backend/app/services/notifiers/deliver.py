from sqlalchemy.orm import Session

from ...models import Notification, utcnow
from . import email, webhook
from .errors import DeliveryError
from .messages import email_content, webhook_payload

MAX_ATTEMPTS = 6  # first try + 5 retries (see tasks.deliver_notification_task)


def deliver_notification(
    db: Session,
    notification_id: str,
    *,
    final_attempt: bool = False,
    transport=None,
) -> str:
    """Sends one notification and records the outcome. Safe to call twice:
    an already-sent notification is never sent again.

    Raises DeliveryError on failure (so Celery retries), after saving the error.
    On the final attempt the notification is marked failed instead of staying pending.
    """
    n = db.get(Notification, notification_id)
    if n is None:
        return "missing"
    if n.status == "sent":
        return "already_sent"

    n.attempts += 1
    try:
        if n.channel == "email":
            subject, body = email_content(n)
            email.send_email(n.user.email, subject, body)
        elif n.channel == "webhook":
            user = n.user
            if not user.webhook_url:
                raise DeliveryError("Webhook was removed from your settings")
            webhook.send_webhook(
                user.webhook_url,
                user.webhook_secret or "",
                webhook_payload(n),
                delivery_id=n.id,
                transport=transport,
            )
        else:
            raise DeliveryError(f"Unknown channel {n.channel}")
    except DeliveryError as exc:
        n.error = str(exc)[:500]
        if final_attempt:
            n.status = "failed"
        db.commit()
        raise

    n.status = "sent"
    n.error = None
    n.sent_at = utcnow()
    db.commit()
    return "sent"
