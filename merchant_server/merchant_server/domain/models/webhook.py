"""Merchant Webhook model."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from merchant_server.domain.models.base import Base, UUIDPrimaryKeyMixin
from sqlalchemy import func


class MerchantWebhook(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "merchant_webhooks"

    merchant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    events: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_triggered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    merchant = relationship("Merchant", back_populates="webhooks")
