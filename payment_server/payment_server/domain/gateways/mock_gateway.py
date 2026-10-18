"""
Mock Payment Gateway — simulates payment flows for testing without Stripe/Razorpay.

Returns realistic-looking responses so the entire checkout saga works end-to-end.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from shared.observability.logging import get_logger

logger = get_logger(__name__)


class MockPaymentGateway:
    """Mock gateway that simulates payment operations.

    Use this for local testing when you don't have Stripe/Razorpay credentials.
    All operations succeed immediately and return realistic response shapes.
    """

    def __init__(self) -> None:
        self.name = "mock"
        self._payments: dict[str, dict] = {}

    async def create_payment_intent(
        self,
        amount: float,
        currency: str,
        order_id: str | None = None,
        customer_email: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Simulate creating a payment intent (authorize)."""
        intent_id = f"mock_pi_{uuid.uuid4().hex[:16]}"
        client_secret = f"{intent_id}_secret_{uuid.uuid4().hex[:8]}"

        payment = {
            "id": intent_id,
            "client_secret": client_secret,
            "amount": amount,
            "currency": currency.lower(),
            "status": "requires_capture",
            "capture_method": "manual",
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._payments[intent_id] = payment

        logger.info("mock_payment_created", intent_id=intent_id, amount=amount, currency=currency)
        return payment

    async def capture_payment(
        self,
        payment_intent_id: str,
        amount: float | None = None,
    ) -> dict[str, Any]:
        """Simulate capturing a payment."""
        payment = self._payments.get(payment_intent_id, {
            "id": payment_intent_id,
            "amount": amount or 0,
            "currency": "usd",
        })
        payment["status"] = "captured"
        payment["captured_at"] = datetime.now(timezone.utc).isoformat()
        if amount:
            payment["amount_captured"] = amount
        self._payments[payment_intent_id] = payment

        logger.info("mock_payment_captured", intent_id=payment_intent_id)
        return payment

    async def refund_payment(
        self,
        payment_intent_id: str,
        amount: float | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Simulate a refund."""
        refund_id = f"mock_re_{uuid.uuid4().hex[:16]}"
        payment = self._payments.get(payment_intent_id, {})

        refund = {
            "id": refund_id,
            "payment_intent_id": payment_intent_id,
            "amount": amount or payment.get("amount", 0),
            "currency": payment.get("currency", "usd"),
            "status": "succeeded",
            "reason": reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info("mock_refund_created", refund_id=refund_id, amount=amount)
        return refund

    async def get_payment_status(self, payment_intent_id: str) -> dict[str, Any]:
        """Get mock payment status."""
        payment = self._payments.get(payment_intent_id)
        if payment:
            return payment
        return {
            "id": payment_intent_id,
            "status": "not_found",
        }

    async def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        webhook_secret: str,
    ) -> dict[str, Any]:
        """Mock webhook verification — always succeeds."""
        return {"verified": True, "type": "mock.event"}
