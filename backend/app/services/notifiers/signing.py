"""Webhook signatures (same scheme as Stripe): the receiver recomputes
HMAC-SHA256(secret, f"{timestamp}.{body}") and compares. The timestamp is part
of what's signed, so a captured request can't be replayed later."""
import hashlib
import hmac
import time


def sign(secret: str, timestamp: int, body: bytes) -> str:
    message = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def signature_header(secret: str, body: bytes, timestamp: int | None = None) -> str:
    timestamp = int(time.time()) if timestamp is None else timestamp
    return f"t={timestamp},v1={sign(secret, timestamp, body)}"


def verify(secret: str, header: str, body: bytes, tolerance_seconds: int = 300, now: int | None = None) -> bool:
    """What a receiving server should do. Included so we can test the round trip."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
        received = parts["v1"]
    except (KeyError, ValueError):
        return False
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), received)
