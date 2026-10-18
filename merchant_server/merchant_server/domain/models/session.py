"""AgentSession model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from merchant_server.domain.models.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class AgentSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_sessions"

    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    state: Mapped[str] = mapped_column(String(50), server_default="active")
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    tool_history: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
