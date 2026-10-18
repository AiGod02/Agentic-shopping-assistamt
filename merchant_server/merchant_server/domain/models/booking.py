"""Booking model — hotel, rental, and service bookings."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from merchant_server.domain.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Booking(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "bookings"

    order_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    listing_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("listings.id"), nullable=False)
    variant_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), ForeignKey("variants.id"))
    availability_block_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("availability_blocks.id")
    )
    booking_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    check_in: Mapped[dt.date | None] = mapped_column(Date)
    check_out: Mapped[dt.date | None] = mapped_column(Date)
    time_slot_start: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    time_slot_end: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    guests: Mapped[int] = mapped_column(Integer, default=1)
    total_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    special_requests: Mapped[str | None] = mapped_column(Text)
    cancellation_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    order = relationship("Order", back_populates="bookings")
    listing = relationship("Listing", lazy="selectin")
