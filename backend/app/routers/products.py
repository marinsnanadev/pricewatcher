from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import PriceHistory, Product, User
from ..schemas import PriceOut, ProductCreate, ProductOut, ProductUpdate
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

    result = run_scrape(scrape_fn, url)
    product = Product(
        user_id=user.id,
        url=url,
        name=result.name,
        store=result.store,
        current_price=result.price,
        target_price=payload.target_price,
    )
    product.history.append(PriceHistory(price=result.price))
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
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
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
