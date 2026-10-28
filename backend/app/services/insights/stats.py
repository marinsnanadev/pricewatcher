"""Numbers about a product's price history. They feed the UI and the AI verdict."""
import hashlib
import json
from datetime import datetime, timedelta
from statistics import mean, median, pstdev

from .deals import DealAnalysis, Point, aware


def _price_at_or_before(points: list[Point], moment: datetime) -> float | None:
    candidates = [p for p in points if aware(p.at) <= moment]
    return max(candidates, key=lambda p: aware(p.at)).price if candidates else None


def _trend_pct(points: list[Point], current: float, now: datetime, days: int) -> float | None:
    past = _price_at_or_before(points, now - timedelta(days=days))
    if past is None or past == 0:
        return None
    return round((current - past) / past * 100, 1)


def compute_stats(
    points: list[Point],
    current_price: float,
    target_price: float | None,
    deal: DealAnalysis,
    now: datetime,
) -> dict:
    now = aware(now)
    ordered = sorted(points, key=lambda p: aware(p.at))
    prices = [p.price for p in ordered] or [current_price]

    lowest = min(prices)
    days_since_lowest = None
    for p in reversed(ordered):
        if p.price == lowest:
            days_since_lowest = max(0, (now - aware(p.at)).days)
            break

    volatility = round(pstdev(prices) / mean(prices) * 100, 1) if len(prices) > 1 else 0.0
    return {
        "current_price": current_price,
        "lowest_price": lowest,
        "highest_price": max(prices),
        "median_price": round(median(prices), 2),
        "trend_7d_pct": _trend_pct(ordered, current_price, now, 7),
        "trend_30d_pct": _trend_pct(ordered, current_price, now, 30),
        "volatility_pct": volatility,
        "days_since_lowest": days_since_lowest,
        "data_points": len(ordered),
        "days_tracked": deal.days_tracked,
        "target_price": target_price,
        "below_target": target_price is not None and current_price <= target_price,
        "deal_verdict": deal.verdict,
        "claimed_discount_pct": deal.claimed_discount_pct,
        "real_discount_pct": deal.real_discount_pct,
        "flags": list(deal.flags),
    }


def fingerprint(stats: dict) -> str:
    """Same fingerprint = same situation = the cached verdict is still valid.
    Trends are bucketed so tiny wiggles don't trigger a new (paid) AI call."""
    def bucket(value):
        return None if value is None else round(value / 2) * 2

    key = {
        "current": round(stats["current_price"], 2),
        "lowest": round(stats["lowest_price"], 2),
        "highest": round(stats["highest_price"], 2),
        "t7": bucket(stats["trend_7d_pct"]),
        "t30": bucket(stats["trend_30d_pct"]),
        "target": stats["target_price"],
        "below": stats["below_target"],
        "deal": stats["deal_verdict"],
        "claimed": bucket(stats["claimed_discount_pct"]),
        "n_bucket": min(stats["data_points"] // 5, 10),
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
