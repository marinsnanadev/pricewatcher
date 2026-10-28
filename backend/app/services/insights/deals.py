"""Is this discount real? Compares what the store ADVERTISES with what the price
history shows. Pure functions: easy to test with synthetic histories.

Verdicts:
  genuine_deal         clearly below the usual price, at/near its lowest
  fair_price           nothing special, nothing suspicious
  price_above_usual    costs more than it normally does
  misleading_discount  advertised discount is much bigger than the real one
  fake_discount        the "was" price is fiction, or the price was hiked before the "sale"
  insufficient_data    not enough history to judge (we say so instead of guessing)
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median

WINDOW = timedelta(days=90)
RECENT = timedelta(days=3)  # the last days are excluded from the "usual price"
MIN_POINTS = 5
MIN_SPAN_DAYS = 7

ADVERTISED_MIN_PCT = 10  # below this we don't call a "discount" a claim worth checking
GAP_MISLEADING_PP = 10  # advertised minus real, in percentage points
GENUINE_MIN_PCT = 10
ABOVE_USUAL_PCT = -5


@dataclass
class Point:
    price: float
    at: datetime
    list_price: float | None = None


@dataclass
class DealAnalysis:
    verdict: str
    confidence: str  # low | medium | high
    current_price: float
    list_price: float | None = None
    claimed_discount_pct: float | None = None
    reference_price: float | None = None  # what it usually costs (median of the history)
    real_discount_pct: float | None = None
    lowest_price: float | None = None
    highest_price: float | None = None
    is_lowest: bool = False
    flags: list[str] = field(default_factory=list)
    data_points: int = 0
    days_tracked: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; everything we store is UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _pct(value: float, base: float) -> float:
    return round((value / base) * 100, 1)


def _confidence(n: int, span_days: float) -> str:
    if n >= 20 and span_days >= 30:
        return "high"
    if n >= 8 and span_days >= 14:
        return "medium"
    return "low"


def analyze_deal(
    points: list[Point],
    current_price: float,
    list_price: float | None,
    now: datetime,
) -> DealAnalysis:
    now = aware(now)
    window = sorted(
        (p for p in points if now - aware(p.at) <= WINDOW), key=lambda p: aware(p.at)
    )
    n = len(window)
    span_days = (aware(window[-1].at) - aware(window[0].at)).total_seconds() / 86400 if n > 1 else 0.0

    claimed = None
    if list_price and list_price > current_price:
        claimed = _pct(list_price - current_price, list_price)

    result = DealAnalysis(
        verdict="insufficient_data",
        confidence=_confidence(n, span_days),
        current_price=current_price,
        list_price=list_price,
        claimed_discount_pct=claimed,
        data_points=n,
        days_tracked=round(span_days, 1),
    )
    if n < MIN_POINTS or span_days < MIN_SPAN_DAYS:
        return result

    prices = [p.price for p in window]
    older = [p.price for p in window if now - aware(p.at) > RECENT] or prices[:-1]
    reference = median(older)
    before = prices[:-1]
    lowest_before = min(before) if before else None

    result.reference_price = round(reference, 2)
    result.real_discount_pct = _pct(reference - current_price, reference)
    result.lowest_price = min(prices + [current_price])
    result.highest_price = max(prices + [current_price])
    result.is_lowest = lowest_before is not None and current_price <= lowest_before

    advertised = claimed is not None and claimed >= ADVERTISED_MIN_PCT

    # 1) the "was R$ X" price: did anyone ever really pay anything close to it?
    if advertised and not any(price >= list_price * 0.95 for price in prices):
        result.flags.append("inflated_list_price")

    # 2) price went up recently, then "dropped" back to about its usual level
    recent_prices = [p.price for p in window if now - aware(p.at) <= timedelta(days=30)]
    if recent_prices:
        peak = max(recent_prices)
        if peak >= reference * 1.15 and current_price <= peak * 0.92 and current_price >= reference * 0.97:
            result.flags.append("pre_sale_hike")

    if result.is_lowest and lowest_before is not None and current_price < lowest_before * 0.99:
        result.flags.append("new_low")
    if result.real_discount_pct <= ABOVE_USUAL_PCT:
        result.flags.append("above_usual")

    real = result.real_discount_pct
    if advertised and ("inflated_list_price" in result.flags or "pre_sale_hike" in result.flags):
        result.verdict = "fake_discount"
    elif advertised and claimed - max(real, 0) >= GAP_MISLEADING_PP:
        result.verdict = "misleading_discount"
    elif real >= GENUINE_MIN_PCT and (
        result.is_lowest or (lowest_before is not None and current_price <= lowest_before * 1.02)
    ):
        result.verdict = "genuine_deal"
    elif real <= ABOVE_USUAL_PCT:
        result.verdict = "price_above_usual"
    else:
        result.verdict = "fair_price"
    return result
