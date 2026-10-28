import json
from datetime import timedelta

import httpx
import pytest

from app.main import app
from app.models import PriceHistory, Product, ProductInsight, utcnow
from app.routers.insights import get_gemini_client
from app.services.insights.verdict import GeminiClient
from tests.conftest import signup_and_login

URL = "https://www.mercadolivre.com.br/fone-bluetooth-pro"
AI_ANSWER = {"action": "wait", "confidence": 0.7, "reasoning": "Looks pricey right now."}


class CountingGemini(GeminiClient):
    """A real GeminiClient wired to a fake network that counts calls."""

    def __init__(self, answer=AI_ANSWER, status=200):
        self.calls = 0

        def handler(request):
            self.calls += 1
            if status != 200:
                return httpx.Response(status)
            text = json.dumps(answer)
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

        super().__init__("key", model="m", transport=httpx.MockTransport(handler))


@pytest.fixture()
def gemini():
    fake = CountingGemini()
    app.dependency_overrides[get_gemini_client] = lambda: fake
    return fake


@pytest.fixture()
def no_gemini():
    app.dependency_overrides[get_gemini_client] = lambda: None


def create_product(client, auth, **extra):
    return client.post("/products", json={"url": URL, **extra}, headers=auth).json()["id"]


def seed_history(session_factory, product_id, prices_by_days_ago, list_price=None):
    with session_factory() as db:
        product = db.get(Product, product_id)
        product.history.clear()
        now = utcnow()
        for days_ago, price in prices_by_days_ago:
            product.history.append(PriceHistory(price=price, collected_at=now - timedelta(days=days_ago)))
        product.current_price = prices_by_days_ago[-1][1]
        product.list_price = list_price
        db.commit()


def steady_then(price_now, days=60):
    return [(d, 100.0) for d in range(days, 0, -3)] + [(0, price_now)]


def test_requires_auth_and_ownership(client, auth, session_factory, no_gemini):
    pid = create_product(client, auth)
    assert client.get(f"/products/{pid}/insights").status_code == 401
    other = signup_and_login(client, email="other@example.com")
    assert client.get(f"/products/{pid}/insights", headers=other).status_code == 404


def test_fresh_product_has_insufficient_data_but_a_helpful_verdict(client, auth, no_gemini):
    pid = create_product(client, auth)
    data = client.get(f"/products/{pid}/insights", headers=auth).json()
    assert data["deal"]["verdict"] == "insufficient_data"
    assert data["verdict"]["source"] == "rules" and data["verdict"]["action"] == "neutral"
    assert data["ai_available"] is False and data["cached"] is False


def test_detects_a_fake_discount_end_to_end(client, auth, session_factory, no_gemini):
    pid = create_product(client, auth)
    seed_history(session_factory, pid, steady_then(100.0), list_price=200.0)  # "was 200, now 100"
    data = client.get(f"/products/{pid}/insights", headers=auth).json()
    assert data["deal"]["verdict"] == "fake_discount"
    assert data["deal"]["claimed_discount_pct"] == 50.0
    assert "inflated_list_price" in data["deal"]["flags"]
    assert data["verdict"]["action"] == "wait"
    assert data["stats"]["data_points"] > 5


def test_genuine_deal_gets_buy_now(client, auth, session_factory, no_gemini):
    pid = create_product(client, auth)
    seed_history(session_factory, pid, steady_then(75.0), list_price=100.0)
    data = client.get(f"/products/{pid}/insights", headers=auth).json()
    assert data["deal"]["verdict"] == "genuine_deal"
    assert data["verdict"]["action"] == "buy_now"


def test_uses_gemini_when_configured(client, auth, session_factory, gemini):
    pid = create_product(client, auth)
    seed_history(session_factory, pid, steady_then(101.0))
    data = client.get(f"/products/{pid}/insights", headers=auth).json()
    assert data["verdict"]["source"] == "gemini" and data["verdict"]["reasoning"] == AI_ANSWER["reasoning"]
    assert data["ai_available"] is True and gemini.calls == 1


def test_second_request_is_served_from_cache(client, auth, session_factory, gemini):
    pid = create_product(client, auth)
    seed_history(session_factory, pid, steady_then(101.0))
    first = client.get(f"/products/{pid}/insights", headers=auth).json()
    second = client.get(f"/products/{pid}/insights", headers=auth).json()
    assert (first["cached"], second["cached"]) == (False, True)
    assert second["verdict"] == first["verdict"]
    assert gemini.calls == 1  # no second paid call


def test_a_changed_situation_recomputes(client, auth, session_factory, gemini):
    pid = create_product(client, auth)
    seed_history(session_factory, pid, steady_then(101.0))
    client.get(f"/products/{pid}/insights", headers=auth)
    # the price crashes: new fingerprint, so a new verdict is needed
    seed_history(session_factory, pid, steady_then(60.0))
    data = client.get(f"/products/{pid}/insights", headers=auth).json()
    assert data["cached"] is False and gemini.calls == 2


def test_refresh_is_throttled_by_the_cooldown(client, auth, session_factory, gemini):
    pid = create_product(client, auth)
    seed_history(session_factory, pid, steady_then(101.0))
    client.get(f"/products/{pid}/insights", headers=auth)
    for _ in range(5):  # hammering "refresh"
        data = client.get(f"/products/{pid}/insights?refresh=true", headers=auth).json()
        assert data["cached"] is True
    assert gemini.calls == 1


def test_refresh_works_after_the_cooldown(client, auth, session_factory, gemini):
    pid = create_product(client, auth)
    seed_history(session_factory, pid, steady_then(101.0))
    client.get(f"/products/{pid}/insights", headers=auth)
    with session_factory() as db:
        db.get(ProductInsight, pid).computed_at = utcnow() - timedelta(minutes=10)
        db.commit()
    data = client.get(f"/products/{pid}/insights?refresh=true", headers=auth).json()
    assert data["cached"] is False and gemini.calls == 2


def test_expired_cache_is_recomputed_even_if_nothing_changed(client, auth, session_factory, gemini):
    pid = create_product(client, auth)
    seed_history(session_factory, pid, steady_then(101.0))
    client.get(f"/products/{pid}/insights", headers=auth)
    with session_factory() as db:
        db.get(ProductInsight, pid).computed_at = utcnow() - timedelta(hours=13)
        db.commit()
    assert client.get(f"/products/{pid}/insights", headers=auth).json()["cached"] is False


def test_ai_failure_degrades_to_rules_instead_of_erroring(client, auth, session_factory):
    app.dependency_overrides[get_gemini_client] = lambda: CountingGemini(status=500)
    pid = create_product(client, auth)
    seed_history(session_factory, pid, steady_then(101.0))
    res = client.get(f"/products/{pid}/insights", headers=auth)
    assert res.status_code == 200
    assert res.json()["verdict"]["source"] == "rules"


def test_hourly_ai_budget_degrades_to_rules(client, auth, session_factory, gemini, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ai_hourly_limit", 2)
    ids = [create_product(client, auth, ) for _ in range(1)]
    ids += [client.post("/products", json={"url": URL + f"-{i}"}, headers=auth).json()["id"] for i in range(3)]
    sources = []
    for pid in ids:
        seed_history(session_factory, pid, steady_then(101.0))
        sources.append(client.get(f"/products/{pid}/insights", headers=auth).json()["verdict"]["source"])
    assert sources == ["gemini", "gemini", "rules", "rules"]
    assert gemini.calls == 2


def test_budget_is_per_user(client, auth, session_factory, gemini, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ai_hourly_limit", 1)
    other = signup_and_login(client, email="other@example.com")
    mine = create_product(client, auth)
    theirs = client.post("/products", json={"url": URL + "-x"}, headers=other).json()["id"]
    for pid in (mine, theirs):
        seed_history(session_factory, pid, steady_then(101.0))
    assert client.get(f"/products/{mine}/insights", headers=auth).json()["verdict"]["source"] == "gemini"
    assert client.get(f"/products/{theirs}/insights", headers=other).json()["verdict"]["source"] == "gemini"


def test_deleting_a_product_removes_its_cached_insight(client, auth, session_factory, no_gemini):
    pid = create_product(client, auth)
    client.get(f"/products/{pid}/insights", headers=auth)
    assert client.delete(f"/products/{pid}", headers=auth).status_code == 204
    with session_factory() as db:
        assert db.query(ProductInsight).count() == 0
