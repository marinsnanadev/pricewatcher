from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import PriceHistory, Product, User
from ..schemas import PriceOut, ProductCreate, ProductOut, ProductUpdate
from ..services import scraper_stub

router = APIRouter(prefix="/products", tags=["products"])


def get_owned_product(product_id: str, user: User, db: Session) -> Product:
    product = db.scalar(
        select(Product).where(Product.id == product_id, Product.user_id == user.id)
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


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
):
    url = payload.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(422, "Enter a valid product URL")

    result = scraper_stub.scrape(url)
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
