"""Listing model — polymorphic item supporting any vertical."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey

from merchant_server.domain.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Listing(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Polymorphic listing — supports product, hotel, rental, service, real_estate, electronics, etc.

    Vertical-specific data is stored in the `metadata` JSONB column:
    - product: {brand, weight, dimensions, warranty_months}
    - hotel: {star_rating, amenities, room_count, check_in_time, check_out_time}
    - rental: {bedrooms, bathrooms, furnished, lease_terms, pet_policy}
    - service: {duration_minutes, provider_name, cancellation_hours}
    - real_estate: {sqft, lot_size, year_built, property_type}
    - electronics: {brand, model, specs, warranty_months}
    """

    __tablename__ = "listings"

    merchant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    base_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(50), default="draft")
    location: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    media: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    rating_avg: Mapped[float] = mapped_column(Numeric(3, 2), default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    search_vector = mapped_column(TSVECTOR)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    merchant = relationship("Merchant", back_populates="listings", lazy="selectin")
    variants = relationship("Variant", back_populates="listing", lazy="selectin", cascade="all, delete-orphan")
    availability_blocks = relationship("AvailabilityBlock", back_populates="listing", lazy="noload", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="listing", lazy="noload")
