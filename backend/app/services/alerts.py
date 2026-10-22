"""Decides WHEN to alert. Pure rules + a function that queues the notifications.

Rules (per product, only when the user set a target price):
  * target_reached : price <= target while the alert is "armed". Alerting disarms it.
  * re-arm         : the price goes back above target -> armed again.
  * further_drop   : already alerted, but price fell a meaningful % below the last
                     alerted price AND the cooldown has passed.
Anything else stays quiet, so the same alert never goes out ten times.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Notification, Product, User

TARGET_REACHED = "target_reached"
FURTHER_DROP = "further_drop"


def initial_armed(target: float | None, price: float | None) -> bool:
    """Armed state for a fresh product / after the target changed.
    If the price is already under the target, stay quiet until it climbs back over."""
    return target is None or price is None or price > target


def decide(product: Product, price: float, now: datetime) -> str | None:
    target = product.target_price
    if target is None or price > target:
        return None
    if product.alert_armed:
        return TARGET_REACHED
    if product.last_alert_price is None or product.last_alert_at is None:
        return None
    last_at = product.last_alert_at
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=now.tzinfo)
    cooldown_over = now - last_at >= timedelta(hours=settings.alert_cooldown_hours)
    threshold = product.last_alert_price * (1 - settings.alert_further_drop_percent / 100)
    if cooldown_over and price <= threshold:
        return FURTHER_DROP
    return None


def enabled_channels(user: User) -> list[str]:
    channels = []
    if user.notify_email:
        channels.append("email")
    if user.webhook_url:
        channels.append("webhook")
    return channels


def queue_alerts(
    db: Session,
    product: Product,
    previous_price: float | None,
    price: float,
    now: datetime,
) -> list[Notification]:
    """Updates the product's alert state and adds Notification rows to the session
    (the caller commits, so price + alert are saved atomically)."""
    target = product.target_price
    if target is not None and price > target:
        product.alert_armed = True  # climbed back above: re-arm

    reason = decide(product, price, now)
    if reason is None:
        return []

    channels = enabled_channels(product.user)
    if not channels:
        return []  # nowhere to send: stay armed so a later config change still alerts

    product.alert_armed = False
    product.last_alert_at = now
    product.last_alert_price = price

    notifications = [
        Notification(
            user_id=product.user_id,
            product_id=product.id,
            channel=channel,
            reason=reason,
            price=price,
            previous_price=previous_price,
            target_price=target,
            created_at=now,
        )
        for channel in channels
    ]
    db.add_all(notifications)
    return notifications
