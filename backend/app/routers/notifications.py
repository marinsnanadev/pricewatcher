import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Notification, User
from ..schemas import NotificationOut, NotificationSettingsOut, NotificationSettingsUpdate
from ..services.alerts import enabled_channels
from ..services.notifiers.webhook import validate_webhook_url

router = APIRouter(tags=["notifications"])


def get_enqueue_delivery():
    """Dependency returning the function that queues a delivery job."""

    def enqueue(notification_id: str) -> None:
        from ..tasks import deliver_notification_task

        deliver_notification_task.delay(notification_id)

    return enqueue


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(24)


def settings_out(user: User) -> NotificationSettingsOut:
    return NotificationSettingsOut(
        email_enabled=user.notify_email,
        email=user.email,
        webhook_url=user.webhook_url,
        webhook_secret=user.webhook_secret,
    )


@router.get("/settings/notifications", response_model=NotificationSettingsOut)
def get_settings(user: User = Depends(get_current_user)):
    return settings_out(user)


@router.put("/settings/notifications", response_model=NotificationSettingsOut)
def update_settings(
    payload: NotificationSettingsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    changes = payload.model_dump(exclude_unset=True)

    if "email_enabled" in changes and changes["email_enabled"] is not None:
        user.notify_email = changes["email_enabled"]

    if "webhook_url" in changes:
        url = (changes["webhook_url"] or "").strip()
        if not url:
            user.webhook_url = None
            user.webhook_secret = None
        else:
            error = validate_webhook_url(url)
            if error:
                raise HTTPException(422, error)
            user.webhook_url = url
            user.webhook_secret = user.webhook_secret or new_secret()

    db.commit()
    return settings_out(user)


@router.post("/settings/notifications/rotate-secret", response_model=NotificationSettingsOut)
def rotate_secret(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.webhook_url:
        raise HTTPException(status.HTTP_409_CONFLICT, "Set a webhook URL first")
    user.webhook_secret = new_secret()
    db.commit()
    return settings_out(user)


@router.post("/settings/notifications/test", status_code=status.HTTP_202_ACCEPTED)
def send_test(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    enqueue=Depends(get_enqueue_delivery),
):
    """Sends a test notification through every enabled channel."""
    channels = enabled_channels(user)
    if not channels:
        raise HTTPException(status.HTTP_409_CONFLICT, "No notification channel is enabled")

    rows = [Notification(user_id=user.id, channel=c, reason="test") for c in channels]
    db.add_all(rows)
    db.commit()
    try:
        for row in rows:
            enqueue(row.id)
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Job queue unavailable, try again later")
    return {"status": "queued", "channels": channels}


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    product_id: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = select(Notification).where(Notification.user_id == user.id)
    if product_id:
        query = query.where(Notification.product_id == product_id)
    return db.scalars(query.order_by(Notification.created_at.desc()).limit(limit)).all()
