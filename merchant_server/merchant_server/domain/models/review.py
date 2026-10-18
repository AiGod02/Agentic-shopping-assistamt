"""Review model."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from merchant_server.domain.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Review(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "reviews"

    user_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    listing_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("listings.id"), nullable=False)
    order_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"))
    booking_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), ForeignKey("bookings.id"))
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text)
    media: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")

    # Relationships
    listing = relationship("Listing", back_populates="reviews")
