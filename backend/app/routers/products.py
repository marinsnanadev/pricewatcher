import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..config import settings
from ..models import PriceHistory, Product, ScrapeRun, User, utcnow
from ..schemas import PriceOut, ProductCreate, ProductOut, ProductUpdate, ScrapeRunOut
from ..services.alerts import initial_armed
from ..services.scheduling import next_check_time
from ..services.scraping import (
    FetchError,
    ParseError,
    ScrapeError,
    ScrapeResult,
    UnsupportedStoreError,
    scrape,
)

router = APIRouter(prefix="/products", tags=["products"])


def get_scrape_fn():
    """Dependency so tests can swap the real network scraper for a fake one."""
    return scrape


def get_enqueue():
    """Dependency returning the function that queues an immediate check.
    Imported lazily so the API can boot (and tests run) without Celery/Redis."""

    def enqueue(product_id: str) -> None:
        from ..tasks import check_product_task

        check_product_task.delay(product_id, trigger="manual")

    return enqueue


def get_owned_product(product_id: str, user: User, db: Session) -> Product:
    product = db.scalar(
        select(Product).where(Product.id == product_id, Product.user_id == user.id)
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


def run_scrape(scrape_fn, url: str) -> ScrapeResult:
    """Runs the scraper and translates scraping errors into HTTP errors."""
    try:
        return scrape_fn(url)
    except (UnsupportedStoreError, ParseError) as exc:
        raise HTTPException(422, str(exc))
    except FetchError as exc:  # includes BlockedError
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    except ScrapeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.get("", response_model=list[ProductOut])
def list_products(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(Product).where(Product.user_id == user.id).order_by(Product.created_at.desc())
    ).all()


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    scrape_fn=Depends(get_scrape_fn),
):
    url = payload.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(422, "Enter a valid product URL")

    now = utcnow()
    clock = time.perf_counter()
    result = run_scrape(scrape_fn, url)
    duration_ms = int((time.perf_counter() - clock) * 1000)

    product = Product(
        user_id=user.id,
        url=url,
        name=result.name,
        store=result.store,
        current_price=result.price,
        list_price=result.list_price,
        target_price=payload.target_price,
        check_interval_minutes=settings.default_check_interval_minutes,
        last_checked_at=now,
        alert_armed=initial_armed(payload.target_price, result.price),
    )
    product.next_check_at = next_check_time(product, now)
    product.history.append(PriceHistory(price=result.price, list_price=result.list_price, collected_at=now))
    product.runs.append(
        ScrapeRun(
            store=result.store,
            trigger="create",
            status="success",
            price=result.price,
            source=result.source,
            duration_ms=duration_ms,
            started_at=now,
        )
    )
    db.add(product)
    db.commit()
    return product


@router.get("/{product_id}", response_model=ProductOut)
def get_product(
    product_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return get_owned_product(product_id, user, db)


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: str,
    payload: ProductUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product = get_owned_product(product_id, user, db)
    # only touch the fields the client actually sent (so target_price can be cleared with null)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is None and field != "target_price":
            continue  # active / interval can't be cleared
        setattr(product, field, value)
    if "target_price" in changes:
        # new target = fresh start for alerts (stay quiet if we're already under it)
        product.alert_armed = initial_armed(product.target_price, product.current_price)
        product.last_alert_at = None
        product.last_alert_price = None
    if changes.get("check_interval_minutes"):
        product.next_check_at = next_check_time(product, utcnow())
    db.commit()
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    product = get_owned_product(product_id, user, db)
    db.delete(product)
    db.commit()


@router.get("/{product_id}/history", response_model=list[PriceOut])
def get_history(
    product_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    product = get_owned_product(product_id, user, db)
    return product.history


@router.post("/{product_id}/check", status_code=status.HTTP_202_ACCEPTED)
def check_now(
    product_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    enqueue=Depends(get_enqueue),
):
    """Queues an immediate price check (the worker does the actual scraping)."""
    product = get_owned_product(product_id, user, db)
    try:
        enqueue(product.id)
    except Exception:  # broker down (Redis not running, etc.)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Job queue unavailable, try again later")
    return {"status": "queued"}


@router.get("/{product_id}/runs", response_model=list[ScrapeRunOut])
def get_runs(
    product_id: str,
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product = get_owned_product(product_id, user, db)
    return product.runs[:limit]
