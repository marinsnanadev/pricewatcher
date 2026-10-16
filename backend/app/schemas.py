from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProductCreate(BaseModel):
    url: str = Field(min_length=1)
    target_price: float | None = Field(default=None, gt=0)


class ProductUpdate(BaseModel):
    target_price: float | None = Field(default=None, gt=0)
    active: bool | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    url: str
    name: str
    store: str
    current_price: float | None
    target_price: float | None
    active: bool
    last_error: str | None
    created_at: datetime


class PriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    price: float
    collected_at: datetime
