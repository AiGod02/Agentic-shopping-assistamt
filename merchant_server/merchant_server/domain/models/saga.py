"""SagaInstance model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from merchant_server.domain.models.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class SagaInstance(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "saga_instances"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="started", nullable=False)
    context_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
