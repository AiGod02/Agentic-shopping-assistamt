"""Merchant model."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from merchant_server.domain.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Merchant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "merchants"

    user_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    business_name: Mapped[str] = mapped_column(String(255), nullable=False)
    business_type: Mapped[str] = mapped_column(String(100), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(100))
    verification_status: Mapped[str] = mapped_column(String(50), default="pending")
    commission_rate: Mapped[float] = mapped_column(Numeric(5, 4), default=0.0)
    payout_account: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    user = relationship("User", back_populates="merchants", lazy="selectin")
    listings = relationship("Listing", back_populates="merchant", lazy="noload")
    webhooks = relationship("MerchantWebhook", back_populates="merchant", lazy="noload")
