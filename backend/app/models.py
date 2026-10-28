import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    notify_email: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=sa.true()
    )
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    products: Mapped[list["Product"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(500))
    store: Mapped[str] = mapped_column(String(50))
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    list_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # struck-through price, if any
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    check_interval_minutes: Mapped[int] = mapped_column(
        Integer, default=360, server_default="360"
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    # alert state: "armed" = the next time price <= target we should alert
    alert_armed: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=sa.true()
    )
    last_alert_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_alert_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="products")
    history: Mapped[list["PriceHistory"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="PriceHistory.collected_at",
    )
    insight: Mapped["ProductInsight | None"] = relationship(
        cascade="all, delete-orphan", uselist=False
    )
    runs: Mapped[list["ScrapeRun"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ScrapeRun.started_at.desc()",
    )


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    price: Mapped[float] = mapped_column(Float)
    list_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    product: Mapped[Product] = relationship(back_populates="history")


class ScrapeRun(Base):
    """One row per scraping attempt (retries included). Feeds the store-health
    panel and makes failures debuggable."""

    __tablename__ = "scrape_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    store: Mapped[str] = mapped_column(String(50), index=True)
    trigger: Mapped[str] = mapped_column(String(20))  # create | scheduled | manual
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(10), index=True)  # success | error
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # json_ld|markup|meta
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    product: Mapped[Product] = relationship(back_populates="runs")


class Notification(Base):
    """Outbox of alerts. A row is created in the same transaction as the price
    update (so an alert is never lost); a worker then delivers it and marks it sent."""

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[str | None] = mapped_column(
        ForeignKey("products.id"), nullable=True, index=True
    )  # null for test notifications
    channel: Mapped[str] = mapped_column(String(10))  # email | webhook
    reason: Mapped[str] = mapped_column(String(20))  # target_reached | further_drop | test
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)  # pending|sent|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()
    product: Mapped[Product | None] = relationship()


class ProductInsight(Base):
    """Cached AI/rule verdict for a product, so the (paid, slow) AI call only happens
    when the numbers actually changed."""

    __tablename__ = "product_insights"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    verdict_json: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10))  # gemini | rules
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
