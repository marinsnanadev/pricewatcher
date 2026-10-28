"""Store health, computed from the scrape_runs table (no extra bookkeeping).

Answers "is Amazon working right now, and if not, why?":
  ParseError   -> the page loaded but the price wasn't found: the layout probably changed
  BlockedError -> the store served a captcha / blocked us
  FetchError   -> network trouble, timeouts, 5xx
"""
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ScrapeRun, utcnow
from .insights.deals import aware

WINDOW = timedelta(hours=24)

DIAGNOSIS_BY_ERROR = {
    "ParseError": "layout_changed",
    "BlockedError": "blocked",
    "FetchError": "network",
    "UnsupportedStoreError": "unsupported",
}


@dataclass
class StoreHealth:
    store: str
    status: str  # healthy | degraded | down | idle
    attempts: int = 0
    successes: int = 0
    success_rate: float | None = None
    p50_ms: int | None = None
    p95_ms: int | None = None
    layers: dict = field(default_factory=dict)  # which extraction layer found the price
    errors: dict = field(default_factory=dict)  # error type -> count
    diagnosis: str | None = None  # why it's failing, when it is
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    window_hours: int = 24

    def to_dict(self) -> dict:
        return asdict(self)


def _percentile(sorted_values: list[int], pct: float) -> int | None:
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, max(0, round(pct / 100 * (len(sorted_values) - 1))))
    return sorted_values[index]


def classify(attempts: int, successes: int) -> str:
    if attempts == 0:
        return "idle"
    rate = successes / attempts
    if successes == 0 and attempts >= 3:
        return "down"
    if rate < 0.5:
        return "down"
    if rate < 0.9:
        return "degraded"
    return "healthy"


def store_health(db: Session, now: datetime | None = None) -> list[StoreHealth]:
    now = aware(now or utcnow())
    rows = db.execute(
        select(
            ScrapeRun.store, ScrapeRun.status, ScrapeRun.source,
            ScrapeRun.error_type, ScrapeRun.duration_ms, ScrapeRun.started_at,
        ).where(ScrapeRun.started_at >= now - WINDOW)
    ).all()

    by_store: dict[str, list] = defaultdict(list)
    for row in rows:
        by_store[row.store].append(row)

    result = []
    for store in sorted(by_store):
        runs = by_store[store]
        ok = [r for r in runs if r.status == "success"]
        failed = [r for r in runs if r.status == "error"]
        durations = sorted(r.duration_ms for r in ok)
        errors = Counter(r.error_type or "unknown" for r in failed)

        diagnosis = None
        status = classify(len(runs), len(ok))
        if failed and status != "healthy":
            top_error = errors.most_common(1)[0][0]
            diagnosis = DIAGNOSIS_BY_ERROR.get(top_error, "unknown")

        result.append(
            StoreHealth(
                store=store,
                status=status,
                attempts=len(runs),
                successes=len(ok),
                success_rate=round(len(ok) / len(runs), 3),
                p50_ms=_percentile(durations, 50),
                p95_ms=_percentile(durations, 95),
                layers=dict(Counter(r.source for r in ok if r.source)),
                errors=dict(errors),
                diagnosis=diagnosis,
                last_success_at=max((aware(r.started_at) for r in ok), default=None),
                last_failure_at=max((aware(r.started_at) for r in failed), default=None),
            )
        )
    return result
