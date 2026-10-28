from datetime import datetime, timedelta, timezone

from app.services.insights.deals import Point, analyze_deal
from app.services.insights.stats import compute_stats, fingerprint

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def history(*days_and_prices):
    """history((60, 100), (30, 100), (0, 80)) -> prices N days before NOW"""
    return [Point(price=p, at=NOW - timedelta(days=d)) for d, p in days_and_prices]


def steady(price=100.0, days=60, every=3):
    return [(d, price) for d in range(days, 0, -every)]


def analyze(points, current, list_price=None):
    return analyze_deal(points, current, list_price, NOW)


# ---------- not enough data ----------

def test_too_few_points_is_insufficient():
    result = analyze(history((2, 100), (1, 100), (0, 80)), 80, 160)
    assert result.verdict == "insufficient_data"
    assert result.claimed_discount_pct == 50.0  # we still report what's advertised
    assert result.reference_price is None


def test_short_history_is_insufficient_even_with_many_points():
    points = history(*[(d / 10, 100) for d in range(60, -1, -1)])  # 6 days
    assert analyze(points, 70).verdict == "insufficient_data"


def test_confidence_grows_with_history():
    assert analyze(history(*steady(days=10, every=2)), 100).confidence == "low"
    assert analyze(history(*steady(days=20, every=2)), 100).confidence == "medium"
    assert analyze(history(*steady(days=80, every=3)), 100).confidence == "high"


# ---------- genuine ----------

def test_genuine_deal_real_drop_to_new_low():
    points = history(*steady(100.0), (0, 78.0))
    result = analyze(points, 78.0, list_price=100.0)
    assert result.verdict == "genuine_deal"
    assert result.real_discount_pct == 22.0
    assert result.claimed_discount_pct == 22.0
    assert result.is_lowest and "new_low" in result.flags


def test_genuine_deal_without_any_advertised_list_price():
    result = analyze(history(*steady(100.0), (0, 85.0)), 85.0)
    assert result.verdict == "genuine_deal"
    assert result.claimed_discount_pct is None


def test_drop_that_is_not_the_lowest_is_only_fair():
    # it already sold for 70 a while ago, so 88 isn't a bargain
    points = history((50, 100), (45, 100), (40, 70), (35, 100), (30, 100), (25, 100), (20, 100), (15, 100), (0, 88))
    result = analyze(points, 88.0)
    assert result.verdict == "fair_price"


# ---------- fake / misleading ----------

def test_inflated_list_price_is_a_fake_discount():
    # "was R$ 200, now R$ 100", but it has always cost about 100
    result = analyze(history(*steady(100.0), (0, 100.0)), 100.0, list_price=200.0)
    assert result.verdict == "fake_discount"
    assert "inflated_list_price" in result.flags
    assert result.claimed_discount_pct == 50.0
    assert result.real_discount_pct == 0.0


def test_pre_sale_hike_is_a_fake_discount():
    # 100 for weeks, hiked to 150 ten days ago, then "discounted" back to 100
    points = history(*steady(100.0, days=60), (10, 150.0), (8, 150.0), (5, 140.0), (0, 100.0))
    result = analyze(points, 100.0, list_price=150.0)
    assert result.verdict == "fake_discount"
    assert "pre_sale_hike" in result.flags


def test_hike_without_an_advertised_discount_is_flagged_but_not_called_fake():
    points = history(*steady(100.0, days=60), (10, 150.0), (8, 150.0), (0, 100.0))
    result = analyze(points, 100.0, list_price=None)
    assert "pre_sale_hike" in result.flags
    assert result.verdict == "fair_price"


def test_misleading_when_list_price_was_real_but_discount_is_much_smaller():
    # it did cost ~150 sometimes (so the list price isn't fiction), but usually ~100
    points = history(*steady(100.0, days=60), (40, 150.0), (38, 150.0), (0, 95.0))
    result = analyze(points, 95.0, list_price=150.0)  # advertises 37%, real is ~5%
    assert "inflated_list_price" not in result.flags
    assert result.verdict == "misleading_discount"
    assert result.claimed_discount_pct - result.real_discount_pct >= 10


def test_small_advertised_discount_is_not_scrutinised():
    result = analyze(history(*steady(100.0), (0, 96.0)), 96.0, list_price=100.0)  # 4% claim
    assert result.verdict == "fair_price"


# ---------- other verdicts ----------

def test_price_above_usual():
    result = analyze(history(*steady(100.0), (0, 120.0)), 120.0)
    assert result.verdict == "price_above_usual"
    assert "above_usual" in result.flags
    assert result.real_discount_pct == -20.0


def test_fair_price():
    assert analyze(history(*steady(100.0), (0, 101.0)), 101.0).verdict == "fair_price"


def test_old_points_outside_the_90_day_window_are_ignored():
    points = history((200, 10), (190, 10), *steady(100.0, days=60), (0, 100.0))
    result = analyze(points, 100.0)
    assert result.reference_price == 100.0  # the 10s from 6 months ago don't drag it down


def test_handles_naive_datetimes_like_sqlite_returns():
    naive = [Point(price=100.0, at=(NOW - timedelta(days=d)).replace(tzinfo=None)) for d in range(60, 0, -3)]
    assert analyze_deal(naive, 100.0, None, NOW).verdict == "fair_price"


def test_to_dict_is_serializable():
    import json
    json.dumps(analyze(history(*steady(100.0)), 100.0).to_dict())


# ---------- stats ----------

def test_stats_numbers():
    points = history(*steady(100.0, days=60), (0, 80.0))
    deal = analyze(points, 80.0, 100.0)
    stats = compute_stats(points, 80.0, 90.0, deal, NOW)
    assert stats["lowest_price"] == 80.0 and stats["highest_price"] == 100.0
    assert stats["below_target"] is True
    assert stats["days_since_lowest"] == 0
    assert stats["trend_7d_pct"] == -20.0
    assert stats["deal_verdict"] == "genuine_deal"
    assert stats["data_points"] == len(points)
    assert stats["volatility_pct"] > 0


def test_stats_trend_is_none_without_old_enough_history():
    points = history((2, 100), (0, 90))
    stats = compute_stats(points, 90.0, None, analyze(points, 90.0), NOW)
    assert stats["trend_7d_pct"] is None and stats["trend_30d_pct"] is None
    assert stats["below_target"] is False


def test_fingerprint_ignores_tiny_wiggles_but_not_real_changes():
    points = history(*steady(100.0), (0, 90.0))
    deal = analyze(points, 90.0)
    base = compute_stats(points, 90.0, None, deal, NOW)

    wiggle = dict(base, trend_7d_pct=base["trend_7d_pct"] + 0.4, volatility_pct=base["volatility_pct"] + 1)
    assert fingerprint(wiggle) == fingerprint(base)
    assert fingerprint(dict(base, current_price=85.0)) != fingerprint(base)
    assert fingerprint(dict(base, target_price=80.0)) != fingerprint(base)
    assert fingerprint(dict(base, deal_verdict="fake_discount")) != fingerprint(base)
