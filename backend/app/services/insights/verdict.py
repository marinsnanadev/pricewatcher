"""'Should I buy now or wait?'

Two layers:
  * rule_based_verdict: deterministic, free, always available.
  * GeminiClient: an LLM writes a more natural verdict from the SAME numbers.

The LLM never sees the product name or page text (scraped text is untrusted, so it
can't inject instructions), its answer is validated like any other untrusted input,
and the deterministic checks keep a veto (a fake discount is never a "buy now").
If anything goes wrong with the AI, the rule-based verdict is used instead.
"""
import json
import logging
from dataclasses import asdict, dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from ...config import settings

log = logging.getLogger(__name__)

NOT_A_DEAL = {"fake_discount", "misleading_discount", "price_above_usual", "insufficient_data"}

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM_PROMPT = (
    "You are a careful price analyst for a shopper. You receive JSON with statistics about one "
    "product's price history (BRL). Decide whether the shopper should buy now, wait, or has no "
    "clear signal. Use ONLY the numbers provided; never invent prices, dates or events. "
    "If days_tracked is small or deal_verdict is 'insufficient_data', say the data is thin and "
    "prefer 'neutral' with low confidence. Never recommend 'buy_now' when deal_verdict is "
    "fake_discount, misleading_discount or price_above_usual. "
    "Answer in English with at most two short sentences of reasoning."
)

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "action": {"type": "STRING", "enum": ["buy_now", "wait", "neutral"]},
        "confidence": {"type": "NUMBER"},
        "reasoning": {"type": "STRING"},
    },
    "required": ["action", "confidence", "reasoning"],
}


class AIError(Exception):
    """The AI call failed or returned something unusable. Callers fall back to rules."""


class VerdictModel(BaseModel):
    action: Literal["buy_now", "wait", "neutral"]
    confidence: float = Field(ge=0, le=1)
    reasoning: str = Field(min_length=1, max_length=400)


@dataclass
class Verdict:
    action: str
    confidence: float
    reasoning: str
    source: str  # gemini | rules

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- rules

def rule_based_verdict(stats: dict) -> Verdict:
    deal = stats["deal_verdict"]
    trend7 = stats["trend_7d_pct"]

    if deal == "insufficient_data":
        days = stats["days_tracked"]
        return Verdict(
            "neutral", 0.2,
            f"Only {days:g} days of price history so far, too little to judge. Check back soon.",
            "rules",
        )
    if deal == "fake_discount":
        return Verdict(
            "wait", 0.85,
            "The advertised discount isn't supported by the price history. It isn't a real deal.",
            "rules",
        )
    if deal == "misleading_discount":
        return Verdict(
            "wait", 0.75,
            "The real discount is much smaller than the advertised one. Don't rush.",
            "rules",
        )
    if deal == "price_above_usual":
        return Verdict("wait", 0.7, "It costs more than it usually does. Waiting should pay off.", "rules")
    if deal == "genuine_deal":
        return Verdict(
            "buy_now", 0.8,
            "A real discount versus the usual price, at or near its lowest. Good moment to buy.",
            "rules",
        )
    if stats["below_target"]:
        return Verdict("buy_now", 0.7, "It's at or below your target price and nothing looks suspicious.", "rules")
    if trend7 is not None and trend7 <= -3:
        return Verdict("wait", 0.5, "The price is falling this week and may drop further.", "rules")
    return Verdict("neutral", 0.5, "The price is within its normal range. No strong reason to rush or wait.", "rules")


# ---------------------------------------------------------------- Gemini

class GeminiClient:
    def __init__(self, api_key: str, model: str | None = None, timeout: float | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.api_key = api_key
        self.model = model or settings.gemini_model
        self.timeout = timeout or settings.gemini_timeout_seconds
        self.transport = transport

    def generate(self, stats: dict) -> VerdictModel:
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps(stats, ensure_ascii=False)}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
                "temperature": 0.2,
                "maxOutputTokens": 300,
            },
        }
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.post(
                    GEMINI_URL.format(model=self.model),
                    json=body,
                    headers={"x-goog-api-key": self.api_key},  # header, not URL: keys leak from URLs
                )
        except httpx.TimeoutException as exc:
            raise AIError("Gemini timed out") from exc
        except httpx.HTTPError as exc:
            raise AIError(f"Gemini request failed: {exc.__class__.__name__}") from exc

        if response.status_code != 200:
            raise AIError(f"Gemini answered HTTP {response.status_code}")
        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> VerdictModel:
        try:
            data = response.json()
            if data.get("promptFeedback", {}).get("blockReason"):
                raise AIError("Gemini blocked the request")
            raw = json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
            if not isinstance(raw, dict):
                raise ValueError("not an object")
            confidence = raw.get("confidence")
            if isinstance(confidence, (int, float)) and 1 < confidence <= 100:
                raw["confidence"] = confidence / 100  # models sometimes answer "85" instead of 0.85
            return VerdictModel.model_validate(raw)
        except AIError:
            raise
        except (ValueError, KeyError, IndexError, TypeError, ValidationError) as exc:
            raise AIError("Gemini returned an unusable answer") from exc


def get_verdict(stats: dict, client: GeminiClient | None = None) -> tuple[Verdict, str | None]:
    """(verdict, ai_problem). ai_problem is None when the AI wasn't needed or worked."""
    rules = rule_based_verdict(stats)
    if client is None:
        return rules, None
    try:
        answer = client.generate(stats)
    except AIError as exc:
        log.warning("AI verdict failed, using rules: %s", exc)
        return rules, str(exc)

    # the deterministic checks have a veto
    if answer.action == "buy_now" and stats["deal_verdict"] in NOT_A_DEAL:
        log.warning("AI said buy_now but the price history says %s; using rules", stats["deal_verdict"])
        return rules, "vetoed"
    return Verdict(answer.action, round(answer.confidence, 2), answer.reasoning.strip(), "gemini"), None
