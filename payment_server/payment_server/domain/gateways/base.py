"""
Abstract Payment Gateway — interface for all payment providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class PaymentIntentResult:
    """Result of creating a payment intent."""
    gateway_payment_id: str
    gateway_order_id: str | None
    client_secret: str | None  # For client-side confirmation (Stripe)
    status: str
    amount: float
    currency: str
    metadata: dict[str, Any] | None = None


@dataclass
class CaptureResult:
    """Result of capturing a payment."""
    gateway_payment_id: str
    status: str
    amount_captured: float
    payment_method_type: str | None = None


@dataclass
class RefundResult:
    """Result of a refund operation."""
    gateway_refund_id: str
    status: str
    amount: float


class PaymentGateway(ABC):
    """Abstract base class for payment gateway integrations."""

    @abstractmethod
    async def create_payment_intent(
        self,
        amount: float,
        currency: str,
        order_id: str,
        customer_email: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> PaymentIntentResult:
        """Create a payment intent / order on the gateway."""
        ...

    @abstractmethod
    async def capture_payment(
        self,
        gateway_payment_id: str,
        amount: float | None = None,
    ) -> CaptureResult:
        """Capture a previously authorized payment."""
        ...

    @abstractmethod
    async def refund_payment(
        self,
        gateway_payment_id: str,
        amount: float | None = None,
        reason: str | None = None,
    ) -> RefundResult:
        """Issue a full or partial refund."""
        ...

    @abstractmethod
    async def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
    ) -> dict[str, Any]:
        """Verify and parse a webhook payload."""
        ...

    @abstractmethod
    async def get_payment_status(self, gateway_payment_id: str) -> dict[str, Any]:
        """Get the current status of a payment from the gateway."""
        ...
