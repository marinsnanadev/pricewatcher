"""Turns a Notification row into the text of an email / the JSON of a webhook."""
from ...models import Notification


def brl(value: float | None) -> str:
    if value is None:
        return "-"
    text = f"{value:,.2f}"  # 1,299.90 -> swap separators to Brazilian style
    return "R$ " + text.replace(",", "X").replace(".", ",").replace("X", ".")


REASON_TEXT = {
    "target_reached": "reached your target price",
    "further_drop": "dropped even further",
    "test": "(test notification)",
}


def email_content(n: Notification) -> tuple[str, str]:
    if n.reason == "test":
        return (
            "Price Watcher: test notification",
            "This is a test notification. Your email alerts are working.",
        )
    product = n.product
    subject = f"Price drop: {product.name} is now {brl(n.price)}"
    lines = [
        f"{product.name} {REASON_TEXT.get(n.reason, '')}.",
        "",
        f"Now:      {brl(n.price)}",
        f"Before:   {brl(n.previous_price)}",
        f"Target:   {brl(n.target_price)}",
        "",
        f"Open the product: {product.url}",
    ]
    return subject, "\n".join(lines)


def webhook_payload(n: Notification) -> dict:
    is_test = n.reason == "test"
    data = {
        "reason": n.reason,
        "price": n.price,
        "previous_price": n.previous_price,
        "target_price": n.target_price,
        "currency": "BRL",
        "product": None
        if n.product is None
        else {
            "id": n.product.id,
            "name": n.product.name,
            "store": n.product.store,
            "url": n.product.url,
        },
    }
    return {
        "id": n.id,
        "event": "webhook.test" if is_test else "price.alert",
        "created_at": n.created_at.isoformat(),
        "data": data,
    }
