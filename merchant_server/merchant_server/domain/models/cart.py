"""Cart and CartItem models — polymorphic cart supporting all verticals."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from merchant_server.domain.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Cart(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "carts"

    user_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active")
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)

    # Relationships
    user = relationship("User", back_populates="carts")
    items = relationship("CartItem", back_populates="cart", lazy="selectin", cascade="all, delete-orphan")

    @property
    def subtotal(self) -> float:
        return sum(item.line_total for item in self.items)

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)


class CartItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Polymorphic cart item — supports products, hotels, rentals, services."""

    __tablename__ = "cart_items"

    cart_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), nullable=False
    )
    listing_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("listings.id"), nullable=False)
    variant_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), ForeignKey("variants.id"))
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    # Booking-specific fields
    check_in: Mapped[dt.date | None] = mapped_column(Date)
    check_out: Mapped[dt.date | None] = mapped_column(Date)
    time_slot_start: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    time_slot_end: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    guests: Mapped[int | None] = mapped_column(Integer)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)

    # Relationships
    cart = relationship("Cart", back_populates="items")

    @property
    def line_total(self) -> float:
        if self.check_in and self.check_out:
            nights = (self.check_out - self.check_in).days
            return float(self.unit_price) * max(nights, 1) * self.quantity
        return float(self.unit_price) * self.quantity
