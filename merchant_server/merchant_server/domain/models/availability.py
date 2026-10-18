"""Availability model — date/time blocks for hotels, rentals, services."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, Numeric, String, Time
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from merchant_server.domain.models.base import Base, UUIDPrimaryKeyMixin
from sqlalchemy import DateTime, func


class AvailabilityBlock(Base, UUIDPrimaryKeyMixin):
    """Availability block for date-range and time-slot-based listings."""

    __tablename__ = "availability_blocks"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="chk_dates"),
        CheckConstraint("booked_count <= capacity", name="chk_capacity"),
    )

    listing_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("variants.id", ondelete="CASCADE")
    )
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    start_time: Mapped[dt.time | None] = mapped_column(Time)
    end_time: Mapped[dt.time | None] = mapped_column(Time)
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    booked_count: Mapped[int] = mapped_column(Integer, default=0)
    price_override: Mapped[float | None] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(50), default="available")
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    listing = relationship("Listing", back_populates="availability_blocks")

    @property
    def remaining_capacity(self) -> int:
        return self.capacity - self.booked_count

    @property
    def is_available(self) -> bool:
        return self.status == "available" and self.remaining_capacity > 0
