"""
Event Schemas — structured event envelope for Kafka messaging.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from shared.schemas.base import BaseSchema


class EventEnvelope(BaseSchema):
    """Structured event envelope for all Kafka events."""

    event_id: str
    event_type: str
    source: str
    aggregate_id: str | None = None
    correlation_id: str
    timestamp: datetime
    version: str = "1.0"
    payload: dict[str, Any]


# ── Domain Events ──────────────────────────────────────────────

class OrderCreatedEvent(BaseSchema):
    """Payload for order.created events."""

    order_id: str
    user_id: str
    order_number: str
    total_amount: float
    currency: str
    items_count: int


class OrderStatusChangedEvent(BaseSchema):
    """Payload for order.status_changed events."""

    order_id: str
    previous_status: str
    new_status: str


class PaymentCapturedEvent(BaseSchema):
    """Payload for payment.captured events."""

    payment_id: str
    order_id: str
    amount: float
    currency: str
    gateway: str


class PaymentFailedEvent(BaseSchema):
    """Payload for payment.failed events."""

    payment_id: str
    order_id: str
    amount: float
    reason: str


class InventoryUpdatedEvent(BaseSchema):
    """Payload for inventory.updated events."""

    listing_id: str
    variant_id: str | None
    previous_count: int
    new_count: int
    reason: str  # sale | restock | adjustment


class BookingConfirmedEvent(BaseSchema):
    """Payload for booking.confirmed events."""

    booking_id: str
    listing_id: str
    user_id: str
    check_in: str | None
    check_out: str | None


class RefundIssuedEvent(BaseSchema):
    """Payload for refund.issued events."""

    refund_id: str
    payment_id: str
    amount: float
    reason: str | None
