import json
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import Product, ProductInsight, User, utcnow
from ..schemas import InsightsOut, StoreHealthOut
from ..services.health import store_health
from ..services.insights.deals import Point, aware, analyze_deal
from ..services.insights.stats import compute_stats, fingerprint
from ..services.insights.verdict import GeminiClient, get_verdict
from .products import get_owned_product

router = APIRouter(tags=["insights"])


def get_gemini_client() -> GeminiClient | None:
    """Dependency: None when no API key is configured (rules only)."""
    return GeminiClient(settings.gemini_api_key) if settings.gemini_api_key else None


def fresh_ai_calls_last_hour(db: Session, user: User, now) -> int:
    return db.scalar(
        select(func.count())
        .select_from(ProductInsight)
        .join(Product, Product.id == ProductInsight.product_id)
        .where(
            Product.user_id == user.id,
            ProductInsight.source == "gemini",
            ProductInsight.computed_at >= now - timedelta(hours=1),
        )
    ) or 0


@router.get("/products/{product_id}/insights", response_model=InsightsOut)
def get_insights(
    product_id: str,
    refresh: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    gemini: GeminiClient | None = Depends(get_gemini_client),
):
    product = get_owned_product(product_id, user, db)
    now = utcnow()

    points = [Point(price=h.price, at=h.collected_at, list_price=h.list_price) for h in product.history]
    current = product.current_price if product.current_price is not None else (points[-1].price if points else 0.0)

    # cheap and deterministic: always fresh
    deal = analyze_deal(points, current, product.list_price, now)
    stats = compute_stats(points, current, product.target_price, deal, now)
    fp = fingerprint(stats)

    cached = product.insight
    verdict = None
    if cached is not None:
        age = now - aware(cached.computed_at)
        same_situation = cached.fingerprint == fp
        fresh_enough = age < timedelta(hours=settings.insight_ttl_hours)
        cooling_down = age < timedelta(minutes=settings.insight_refresh_cooldown_minutes)
        # A changed situation always gets a new verdict (never show a stale one next to fresh
        # numbers). The cooldown only stops the "refresh" button from being spammed.
        reuse = same_situation and ((fresh_enough and not refresh) or (refresh and cooling_down))
        if reuse:
            verdict = json.loads(cached.verdict_json)  # no new AI call: saves money
            was_cached = True

    if verdict is None:
        was_cached = False
        # over the hourly budget? degrade to rules instead of failing
        client = gemini if gemini and fresh_ai_calls_last_hour(db, user, now) < settings.ai_hourly_limit else None
        answer, _problem = get_verdict(stats, client)
        verdict = answer.to_dict()
        if cached is None:
            cached = ProductInsight(product_id=product.id)
            db.add(cached)
        cached.fingerprint = fp
        cached.verdict_json = json.dumps(verdict)
        cached.source = answer.source
        cached.computed_at = now
        db.commit()

    return InsightsOut(
        deal=deal.to_dict(),
        stats=stats,
        verdict=verdict,
        cached=was_cached,
        ai_available=gemini is not None,
    )


@router.get("/stores/health", response_model=list[StoreHealthOut])
def get_store_health(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Aggregated over the last 24h and over every user's checks, so it says nothing
    about any individual's products."""
    return [h.to_dict() for h in store_health(db)]
