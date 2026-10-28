from datetime import timedelta

from app.models import ScrapeRun, utcnow
from app.services.health import classify, store_health
from tests.conftest import make_product, signup_and_login


def run(db, product, store="amazon", status="success", source="markup", error_type=None, ms=500, hours_ago=1):
    db.add(
        ScrapeRun(
            product_id=product.id, store=store, trigger="scheduled", attempt=1, status=status,
            source=source if status == "success" else None, error_type=error_type, duration_ms=ms,
            price=10.0 if status == "success" else None,
            started_at=utcnow() - timedelta(hours=hours_ago),
        )
    )


def by_store(db):
    return {h.store: h for h in store_health(db)}


def test_classify_thresholds():
    assert classify(0, 0) == "idle"
    assert classify(10, 10) == "healthy"
    assert classify(10, 9) == "healthy"
    assert classify(10, 8) == "degraded"
    assert classify(10, 4) == "down"
    assert classify(3, 0) == "down"
    assert classify(2, 0) == "down"  # rate 0 < 0.5


def test_healthy_store_stats(db):
    p = make_product(db)
    for i, ms in enumerate([100, 200, 300, 400, 5000]):
        run(db, p, ms=ms, source="json_ld" if i < 3 else "markup")
    db.commit()
    h = by_store(db)["amazon"]
    assert (h.status, h.attempts, h.successes, h.success_rate) == ("healthy", 5, 5, 1.0)
    assert h.p50_ms == 300 and h.p95_ms == 5000
    assert h.layers == {"json_ld": 3, "markup": 2}
    assert h.errors == {} and h.diagnosis is None
    assert h.last_failure_at is None and h.last_success_at is not None


def test_parse_errors_mean_the_layout_probably_changed(db):
    p = make_product(db)
    for _ in range(3):
        run(db, p, status="error", error_type="ParseError")
    run(db, p)
    db.commit()
    h = by_store(db)["amazon"]
    assert h.status == "down"
    assert h.diagnosis == "layout_changed"
    assert h.errors == {"ParseError": 3}


def test_blocked_and_network_diagnoses(db):
    p = make_product(db)
    for _ in range(4):
        run(db, p, store="amazon", status="error", error_type="BlockedError")
        run(db, p, store="mercado_livre", status="error", error_type="FetchError")
    db.commit()
    stores = by_store(db)
    assert stores["amazon"].diagnosis == "blocked"
    assert stores["mercado_livre"].diagnosis == "network"


def test_degraded_between_50_and_90_percent(db):
    p = make_product(db)
    for _ in range(8):
        run(db, p)
    for _ in range(2):
        run(db, p, status="error", error_type="BlockedError")
    db.commit()
    h = by_store(db)["amazon"]
    assert (h.status, h.success_rate, h.diagnosis) == ("degraded", 0.8, "blocked")


def test_most_common_error_wins_the_diagnosis(db):
    p = make_product(db)
    for _ in range(3):
        run(db, p, status="error", error_type="FetchError")
    run(db, p, status="error", error_type="ParseError")
    db.commit()
    assert by_store(db)["amazon"].diagnosis == "network"


def test_only_the_last_24_hours_count(db):
    p = make_product(db)
    for _ in range(5):
        run(db, p, status="error", error_type="ParseError", hours_ago=30)  # yesterday's outage
    run(db, p, hours_ago=1)
    db.commit()
    h = by_store(db)["amazon"]
    assert (h.status, h.attempts) == ("healthy", 1)


def test_stores_without_recent_runs_are_not_listed(db):
    p = make_product(db)
    run(db, p, hours_ago=100)
    db.commit()
    assert store_health(db) == []


def test_health_endpoint_requires_auth_and_hides_per_user_data(client, auth, session_factory):
    assert client.get("/stores/health").status_code == 401
    with session_factory() as db:
        p = make_product(db)
        run(db, p)
        db.commit()
    data = client.get("/stores/health", headers=auth).json()
    assert [s["store"] for s in data] == ["amazon"]
    assert set(data[0]) == {
        "store", "status", "attempts", "successes", "success_rate", "p50_ms", "p95_ms",
        "layers", "errors", "diagnosis", "last_success_at", "last_failure_at", "window_hours",
    }  # no product ids, urls or user data
