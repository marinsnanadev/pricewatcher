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
    check_interval_minutes: int | None = Field(default=None, ge=15, le=10080)


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
    check_interval_minutes: int
    last_checked_at: datetime | None
    next_check_at: datetime | None
    consecutive_failures: int
    created_at: datetime


class PriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    price: float
    collected_at: datetime


class ScrapeRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    store: str
    trigger: str
    attempt: int
    status: str
    price: float | None
    source: str | None
    error_type: str | None
    error_message: str | None
    duration_ms: int
    started_at: datetime


class NotificationSettingsOut(BaseModel):
    email_enabled: bool
    email: EmailStr
    webhook_url: str | None
    webhook_secret: str | None


class NotificationSettingsUpdate(BaseModel):
    email_enabled: bool | None = None
    webhook_url: str | None = None  # explicit null removes the webhook


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str | None
    channel: str
    reason: str
    price: float | None
    previous_price: float | None
    target_price: float | None
    status: str
    attempts: int
    error: str | None
    created_at: datetime
    sent_at: datetime | None
