"""Variant model — represents SKU-level variations of a listing."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from merchant_server.domain.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Variant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Variant — size, color, room type, plan tier, etc."""

    __tablename__ = "variants"

    listing_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    sku: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price_override: Mapped[float | None] = mapped_column(Numeric(12, 2))
    inventory_count: Mapped[int] = mapped_column(Integer, default=0)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    listing = relationship("Listing", back_populates="variants")
