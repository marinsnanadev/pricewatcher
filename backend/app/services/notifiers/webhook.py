import ipaddress
import json
import socket
import uuid
from urllib.parse import urlparse

import httpx

from ...config import settings
from .errors import DeliveryError
from .signing import signature_header


def _blocked(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # includes 169.254.169.254 (cloud metadata)
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_webhook_url(url: str) -> str | None:
    """Cheap check done when the user saves the URL (no DNS). Returns an error text or None."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "Webhook URL must start with http:// or https://"
    if settings.allow_private_webhooks:
        return None
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        return "Webhook URL can't point to localhost"
    try:
        if _blocked(ipaddress.ip_address(host)):
            return "Webhook URL can't point to a private or internal address"
    except ValueError:
        pass  # a hostname, resolved (and checked again) at send time
    return None


def resolve_ips(host: str, port: int) -> list[str]:
    try:
        return [info[4][0] for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]
    except socket.gaierror as exc:
        raise DeliveryError(f"Couldn't resolve webhook host {host}") from exc


def assert_public_destination(url: str) -> None:
    """Re-checked right before sending: a hostname can start resolving to an
    internal IP after it was saved (SSRF), so we look at where it points *now*."""
    if settings.allow_private_webhooks:
        return
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    for ip in resolve_ips(parsed.hostname, port):
        if _blocked(ipaddress.ip_address(ip)):
            raise DeliveryError("Webhook host resolves to a private or internal address")


def send_webhook(
    url: str,
    secret: str,
    payload: dict,
    delivery_id: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> None:
    assert_public_destination(url)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "PriceWatcher-Webhook/1.0",
        "X-PriceWatcher-Event": payload.get("event", "price.alert"),
        "X-PriceWatcher-Delivery": delivery_id or str(uuid.uuid4()),
        "X-PriceWatcher-Signature": signature_header(secret, body),
    }
    try:
        # no redirects: a 302 to an internal address would sidestep the check above
        with httpx.Client(
            timeout=settings.webhook_timeout_seconds,
            follow_redirects=False,
            transport=transport,
        ) as client:
            response = client.post(url, content=body, headers=headers)
    except httpx.TimeoutException as exc:
        raise DeliveryError("Webhook timed out") from exc
    except httpx.HTTPError as exc:
        raise DeliveryError(f"Webhook request failed: {exc.__class__.__name__}") from exc

    if not 200 <= response.status_code < 300:
        raise DeliveryError(f"Webhook answered HTTP {response.status_code}")
