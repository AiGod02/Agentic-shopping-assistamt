"""PageView model — lightweight analytics for tracking merchant page visits."""

from __future__ import annotations

from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from merchant_server.domain.models.base import Base, UUIDPrimaryKeyMixin


class PageView(Base, UUIDPrimaryKeyMixin):
    """Tracks page visits for merchant storefronts and listings.

    Used for analytics dashboard — traffic, visits, referrer tracking.
    """

    __tablename__ = "page_views"

    merchant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False, index=True
    )
    listing_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id"), nullable=True, index=True
    )
    visitor_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="Hashed session/visitor identifier for unique visit counting",
    )
    page_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="storefront",
        comment="storefront | listing | checkout | search",
    )
    referrer: Mapped[str | None] = mapped_column(String(500))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
