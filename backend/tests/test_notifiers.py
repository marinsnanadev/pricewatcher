import json
import logging
import smtplib

import httpx
import pytest

from app.config import settings
from app.services.notifiers import email, webhook
from app.services.notifiers.errors import DeliveryError
from app.services.notifiers.messages import brl
from app.services.notifiers.signing import sign, signature_header, verify

PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(webhook, "resolve_ips", lambda host, port: [PUBLIC_IP])


def mock_transport(handler):
    return httpx.MockTransport(handler)


# ---------- signing ----------

def test_signature_round_trip():
    body = b'{"hello":"world"}'
    header = signature_header("whsec_abc", body, timestamp=1_000)
    assert verify("whsec_abc", header, body, now=1_000)


def test_signature_rejects_tampering_wrong_secret_and_replay():
    body = b'{"price":10}'
    header = signature_header("whsec_abc", body, timestamp=1_000)
    assert not verify("whsec_abc", header, b'{"price":1}', now=1_000)  # body changed
    assert not verify("whsec_other", header, body, now=1_000)  # wrong secret
    assert not verify("whsec_abc", header, body, now=1_000 + 301)  # too old (replay)
    assert not verify("whsec_abc", "garbage", body, now=1_000)
    assert sign("a", 1, b"x") != sign("a", 2, b"x")  # timestamp is part of the signature


# ---------- webhook sending ----------

def test_webhook_posts_signed_json():
    seen = {}

    def handler(request: httpx.Request):
        seen["request"] = request
        return httpx.Response(204)

    payload = {"id": "n1", "event": "price.alert", "data": {"price": 90.0}}
    webhook.send_webhook("https://hooks.example.com/pw", "whsec_abc", payload, "n1", mock_transport(handler))

    request = seen["request"]
    assert json.loads(request.content) == payload
    assert request.headers["x-pricewatcher-event"] == "price.alert"
    assert request.headers["x-pricewatcher-delivery"] == "n1"
    assert verify("whsec_abc", request.headers["x-pricewatcher-signature"], request.content)


@pytest.mark.parametrize("status", [400, 404, 500, 503])
def test_webhook_non_2xx_is_a_delivery_error(status):
    with pytest.raises(DeliveryError, match=str(status)):
        webhook.send_webhook(
            "https://hooks.example.com/pw", "s", {"event": "x"}, None,
            mock_transport(lambda r: httpx.Response(status)),
        )


def test_webhook_does_not_follow_redirects():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    with pytest.raises(DeliveryError, match="302"):
        webhook.send_webhook("https://hooks.example.com/pw", "s", {"event": "x"}, None, mock_transport(handler))
    assert calls == ["https://hooks.example.com/pw"]  # never went to the internal address


def test_webhook_timeout_and_network_errors():
    def slow(request):
        raise httpx.ReadTimeout("slow")

    def down(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(DeliveryError, match="timed out"):
        webhook.send_webhook("https://hooks.example.com/pw", "s", {"event": "x"}, None, mock_transport(slow))
    with pytest.raises(DeliveryError, match="ConnectError"):
        webhook.send_webhook("https://hooks.example.com/pw", "s", {"event": "x"}, None, mock_transport(down))


# ---------- SSRF protection ----------

@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "javascript:alert(1)",
        "not a url",
        "http://localhost:8000/hook",
        "http://app.localhost/hook",
        "http://127.0.0.1/hook",
        "http://10.0.0.5/hook",
        "http://192.168.1.10/hook",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/hook",
        "http://0.0.0.0/hook",
    ],
)
def test_validate_rejects_unsafe_urls(url):
    assert webhook.validate_webhook_url(url) is not None


def test_validate_accepts_public_urls():
    assert webhook.validate_webhook_url("https://hooks.example.com/pw?x=1") is None
    assert webhook.validate_webhook_url("http://93.184.216.34/pw") is None


def test_validate_allows_private_in_dev_mode(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_webhooks", True)
    assert webhook.validate_webhook_url("http://localhost:9000/hook") is None


def test_send_blocks_hostnames_that_resolve_to_internal_ips(monkeypatch):
    # the host looked fine when saved, but now points inside the network (DNS rebinding)
    monkeypatch.setattr(webhook, "resolve_ips", lambda host, port: ["10.1.2.3"])
    sent = []
    with pytest.raises(DeliveryError, match="private"):
        webhook.send_webhook(
            "https://innocent.example.com/pw", "s", {"event": "x"}, None,
            mock_transport(lambda r: sent.append(r) or httpx.Response(200)),
        )
    assert sent == []  # no request was made


def test_send_blocks_if_any_resolved_ip_is_internal(monkeypatch):
    monkeypatch.setattr(webhook, "resolve_ips", lambda host, port: [PUBLIC_IP, "127.0.0.1"])
    with pytest.raises(DeliveryError):
        webhook.assert_public_destination("https://mixed.example.com/pw")


# ---------- email ----------

def test_console_backend_only_logs(caplog, monkeypatch):
    monkeypatch.setattr(settings, "email_backend", "console")
    with caplog.at_level(logging.WARNING):
        email.send_email("a@b.com", "Hi", "Body text")
    assert "a@b.com" in caplog.text and "Body text" in caplog.text


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.sent, self.started_tls, self.logged_in = [], False, None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, message):
        self.sent.append(message)


def configure_smtp(monkeypatch):
    monkeypatch.setattr(settings, "email_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_user", "apikey")
    monkeypatch.setattr(settings, "smtp_password", "secret")
    FakeSMTP.instances = []


def test_smtp_backend_sends_message(monkeypatch):
    configure_smtp(monkeypatch)
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    email.send_email("nana@example.com", "Price drop", "Now R$ 90,00")

    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port, smtp.started_tls, smtp.logged_in) == (
        "smtp.example.com", 587, True, ("apikey", "secret"),
    )
    message = smtp.sent[0]
    assert message["To"] == "nana@example.com" and message["Subject"] == "Price drop"


def test_smtp_failures_become_delivery_errors(monkeypatch):
    configure_smtp(monkeypatch)

    class Broken(FakeSMTP):
        def send_message(self, message):
            raise smtplib.SMTPServerDisconnected("bye")

    monkeypatch.setattr(smtplib, "SMTP", Broken)
    with pytest.raises(DeliveryError, match="SMTP"):
        email.send_email("a@b.com", "s", "b")


def test_smtp_without_host_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(settings, "email_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_host", "")
    with pytest.raises(DeliveryError, match="SMTP_HOST"):
        email.send_email("a@b.com", "s", "b")


def test_brl_formatting():
    assert brl(1299.9) == "R$ 1.299,90"
    assert brl(5) == "R$ 5,00"
    assert brl(None) == "-"
