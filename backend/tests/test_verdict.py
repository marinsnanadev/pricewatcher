import json

import httpx
import pytest

from app.services.insights.verdict import (
    AIError,
    GeminiClient,
    get_verdict,
    rule_based_verdict,
)


def stats(**over):
    base = {
        "current_price": 90.0, "lowest_price": 90.0, "highest_price": 120.0, "median_price": 100.0,
        "trend_7d_pct": 0.0, "trend_30d_pct": 0.0, "volatility_pct": 5.0, "days_since_lowest": 0,
        "data_points": 30, "days_tracked": 45.0, "target_price": None, "below_target": False,
        "deal_verdict": "fair_price", "claimed_discount_pct": None, "real_discount_pct": 2.0, "flags": [],
    }
    base.update(over)
    return base


# ---------- rules ----------

@pytest.mark.parametrize(
    "overrides, action",
    [
        ({"deal_verdict": "insufficient_data", "days_tracked": 2.0}, "neutral"),
        ({"deal_verdict": "fake_discount"}, "wait"),
        ({"deal_verdict": "misleading_discount"}, "wait"),
        ({"deal_verdict": "price_above_usual"}, "wait"),
        ({"deal_verdict": "genuine_deal"}, "buy_now"),
        ({"deal_verdict": "fair_price", "below_target": True}, "buy_now"),
        ({"deal_verdict": "fair_price", "trend_7d_pct": -5.0}, "wait"),
        ({"deal_verdict": "fair_price"}, "neutral"),
    ],
)
def test_rule_based_actions(overrides, action):
    verdict = rule_based_verdict(stats(**overrides))
    assert verdict.action == action
    assert verdict.source == "rules" and 0 <= verdict.confidence <= 1 and verdict.reasoning


def test_below_target_does_not_beat_a_fake_discount():
    assert rule_based_verdict(stats(deal_verdict="fake_discount", below_target=True)).action == "wait"


def test_insufficient_data_mentions_how_little_history_there_is():
    assert "2 days" in rule_based_verdict(stats(deal_verdict="insufficient_data", days_tracked=2.0)).reasoning


# ---------- Gemini ----------

def gemini_reply(payload, status=200, wrap=True):
    body = {"candidates": [{"content": {"parts": [{"text": json.dumps(payload) if wrap else payload}]}}]}
    return httpx.Response(status, json=body)


def client_returning(response_or_fn, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return response_or_fn(request) if callable(response_or_fn) else response_or_fn

    return GeminiClient("secret-key", model="test-model", transport=httpx.MockTransport(handler))


GOOD = {"action": "wait", "confidence": 0.8, "reasoning": "The price is above its usual range."}


def test_gemini_happy_path_and_request_shape():
    seen = []
    client = client_returning(gemini_reply(GOOD), seen)
    answer = client.generate(stats())
    assert (answer.action, answer.confidence) == ("wait", 0.8)

    request = seen[0]
    assert "test-model:generateContent" in str(request.url)
    assert request.headers["x-goog-api-key"] == "secret-key"
    assert "secret-key" not in str(request.url)  # keys never go in URLs
    body = json.loads(request.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["temperature"] <= 0.3
    assert json.loads(body["contents"][0]["parts"][0]["text"])["current_price"] == 90.0


def test_the_model_only_receives_numbers_never_product_text():
    seen = []
    client_returning(gemini_reply(GOOD), seen).generate(stats())
    sent = json.loads(json.loads(seen[0].content)["contents"][0]["parts"][0]["text"])
    assert all(isinstance(v, (int, float, bool, str, list, type(None))) for v in sent.values())
    assert not {"name", "url", "title", "product"} & set(sent)


def test_confidence_given_as_percent_is_normalized():
    answer = client_returning(gemini_reply({**GOOD, "confidence": 85})).generate(stats())
    assert answer.confidence == 0.85


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(429),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"candidates": []}),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}),
        gemini_reply("plain text, not json", wrap=False),
        gemini_reply([1, 2, 3]),
        gemini_reply({"action": "yolo", "confidence": 0.5, "reasoning": "x"}),
        gemini_reply({"action": "wait", "confidence": 7000, "reasoning": "x"}),
        gemini_reply({"action": "wait", "confidence": 0.5, "reasoning": ""}),
        gemini_reply({"action": "wait", "confidence": 0.5, "reasoning": "x" * 5000}),
        gemini_reply({"action": "wait"}),
    ],
)
def test_bad_answers_are_rejected(response):
    with pytest.raises(AIError):
        client_returning(response).generate(stats())


def test_timeouts_and_network_errors_become_ai_errors():
    def slow(request):
        raise httpx.ReadTimeout("slow")

    def down(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(AIError, match="timed out"):
        client_returning(slow).generate(stats())
    with pytest.raises(AIError):
        client_returning(down).generate(stats())


# ---------- get_verdict: orchestration ----------

def test_without_a_client_rules_are_used():
    verdict, problem = get_verdict(stats(), None)
    assert verdict.source == "rules" and problem is None


def test_ai_answer_is_used_when_valid():
    verdict, problem = get_verdict(stats(), client_returning(gemini_reply(GOOD)))
    assert (verdict.source, verdict.action, problem) == ("gemini", "wait", None)


def test_ai_failure_falls_back_to_rules():
    verdict, problem = get_verdict(stats(), client_returning(httpx.Response(500)))
    assert verdict.source == "rules" and "500" in problem


@pytest.mark.parametrize("deal", ["fake_discount", "misleading_discount", "price_above_usual", "insufficient_data"])
def test_deterministic_checks_veto_a_buy_now(deal):
    greedy = {"action": "buy_now", "confidence": 0.99, "reasoning": "Amazing deal, buy it!"}
    verdict, problem = get_verdict(stats(deal_verdict=deal), client_returning(gemini_reply(greedy)))
    assert verdict.action != "buy_now"
    assert verdict.source == "rules" and problem == "vetoed"


def test_ai_buy_now_is_fine_on_a_genuine_deal():
    ok = {"action": "buy_now", "confidence": 0.9, "reasoning": "Lowest price in weeks."}
    verdict, _ = get_verdict(stats(deal_verdict="genuine_deal"), client_returning(gemini_reply(ok)))
    assert (verdict.source, verdict.action) == ("gemini", "buy_now")


def test_prompt_injection_attempt_in_the_reasoning_is_just_text():
    # whatever the model says, it's stored/rendered as plain data and capped in length
    sneaky = {"action": "neutral", "confidence": 0.5, "reasoning": "Ignore previous instructions <script>alert(1)</script>"}
    verdict, _ = get_verdict(stats(), client_returning(gemini_reply(sneaky)))
    assert verdict.action == "neutral" and len(verdict.reasoning) <= 400
