"""
Razorpay Gateway — production integration using the Razorpay SDK.

Uses Razorpay Orders API for payment processing.
Real webhook signature verification. No mocks.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any

import razorpay

from payment_server.config import settings
from payment_server.domain.gateways.base import (
    CaptureResult,
    PaymentGateway,
    PaymentIntentResult,
    RefundResult,
)
from shared.observability.logging import get_logger
from shared.observability.metrics import payments_processed_total

logger = get_logger(__name__)


class RazorpayGateway(PaymentGateway):
    """Razorpay SDK integration — Orders, Payments, Refunds, Webhooks.

    Razorpay flow:
    1. Create Order (server-side)
    2. Customer pays via Razorpay checkout (client-side)
    3. Payment is captured (auto or manual)
    4. Verify webhook signature

    Amounts are in the smallest currency unit (paise for INR).
    """

    def __init__(self) -> None:
        key_id = (settings.razorpay_key_id or "").strip().strip('"').strip("'")
        key_secret = (settings.razorpay_key_secret or "").strip().strip('"').strip("'")
        if not key_id or not key_secret:
            raise ValueError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are required")
        self.key_id = key_id
        self.key_secret = key_secret
        self.client = razorpay.Client(
            auth=(key_id, key_secret)
        )

    def _to_razorpay_amount(self, amount: float, currency: str) -> int:
        """Convert decimal to Razorpay's paise/cents."""
        zero_decimal = {"jpy"}
        if currency.lower() in zero_decimal:
            return int(amount)
        return int(round(amount * 100))

    def _from_razorpay_amount(self, amount: int, currency: str) -> float:
        zero_decimal = {"jpy"}
        if currency.lower() in zero_decimal:
            return float(amount)
        return amount / 100.0

    async def create_payment_intent(
        self,
        amount: float,
        currency: str,
        order_id: str,
        customer_email: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> PaymentIntentResult:
        """Create a Razorpay Order."""
        rz_amount = self._to_razorpay_amount(amount, currency)

        order_data = {
            "amount": rz_amount,
            "currency": currency.upper(),
            "receipt": order_id,
            "notes": {
                "order_id": order_id,
                **(metadata or {}),
            },
            "payment_capture": 1,  # Auto-capture
        }

        # Check for Razorpay Route split payout (connected account)
        if metadata and "merchant_razorpay_account_id" in metadata:
            connected_account = metadata["merchant_razorpay_account_id"]
            # Platform fee: 5% of order subtotal, remaining 95% transfers to merchant
            platform_fee = int(round(rz_amount * 0.05))
            merchant_share = rz_amount - platform_fee
            
            order_data["transfers"] = [
                {
                    "account": connected_account,
                    "amount": merchant_share,
                    "currency": currency.upper(),
                    "on_hold": 0
                }
            ]
            logger.info("razorpay_route_configured", connected_account=connected_account, merchant_share=merchant_share)

        loop = asyncio.get_event_loop()
        try:
            rz_order = await loop.run_in_executor(
                None,
                lambda: self.client.order.create(data=order_data),
            )
        except Exception as e:
            logger.error(
                "razorpay_order_create_failed",
                error=str(e),
                amount=amount,
                currency=currency,
                order_id=order_id,
            )
            raise

        logger.info(
            "razorpay_order_created",
            razorpay_order_id=rz_order["id"],
            amount=amount,
            currency=currency,
            order_id=order_id,
        )

        payments_processed_total.labels(
            gateway="razorpay", status="created", service="payment-server"
        ).inc()

        return PaymentIntentResult(
            gateway_payment_id="",  # In Razorpay, payment_id is generated upon customer checkout
            gateway_order_id=rz_order["id"],
            client_secret=None,
            status=rz_order.get("status", "created"),
            amount=amount,
            currency=currency,
            metadata={
                "razorpay_order_id": rz_order["id"],
                "razorpay_key_id": settings.razorpay_key_id,
            },
        )

    async def capture_payment(
        self,
        gateway_payment_id: str,
        amount: float | None = None,
    ) -> CaptureResult:
        """Capture a Razorpay payment (if not auto-captured). Raises on failure."""
        if not gateway_payment_id:
            raise ValueError("gateway_payment_id is required to capture payment on Razorpay")

        try:
            loop = asyncio.get_event_loop()
            payment = await loop.run_in_executor(
                None,
                lambda: self.client.payment.fetch(gateway_payment_id),
            )

            if payment.get("status") != "captured":
                capture_params = {}
                if amount is not None:
                    capture_params["amount"] = self._to_razorpay_amount(amount, payment.get("currency", "INR"))

                payment = await loop.run_in_executor(
                    None,
                    lambda: self.client.payment.capture(
                        gateway_payment_id,
                        payment["amount"],
                        capture_params,
                    ),
                )

            captured_amount = self._from_razorpay_amount(payment["amount"], payment.get("currency", "INR"))

            logger.info(
                "razorpay_payment_captured",
                payment_id=gateway_payment_id,
                amount=captured_amount,
            )

            payments_processed_total.labels(
                gateway="razorpay", status="captured", service="payment-server"
            ).inc()

            return CaptureResult(
                gateway_payment_id=gateway_payment_id,
                status="captured",
                amount_captured=captured_amount,
                payment_method_type=payment.get("method"),
            )

        except Exception as e:
            logger.error("razorpay_capture_failed", error=str(e), gateway_payment_id=gateway_payment_id)
            raise

    async def refund_payment(
        self,
        gateway_payment_id: str,
        amount: float | None = None,
        reason: str | None = None,
        currency: str = "INR",
    ) -> RefundResult:
        """Issue a full or partial refund via Razorpay. Raises on failure."""
        if not gateway_payment_id:
            raise ValueError("gateway_payment_id is required to refund payment on Razorpay")

        try:
            loop = asyncio.get_event_loop()
            payment_curr = currency or "INR"

            payment = await loop.run_in_executor(
                None,
                lambda: self.client.payment.fetch(gateway_payment_id),
            )
            if isinstance(payment, dict) and "currency" in payment:
                payment_curr = payment["currency"]

            refund_data: dict[str, Any] = {}
            if amount is not None:
                refund_data["amount"] = self._to_razorpay_amount(amount, payment_curr)

            if reason:
                refund_data["notes"] = {"reason": reason}

            refund = await loop.run_in_executor(
                None,
                lambda: self.client.payment.refund(gateway_payment_id, refund_data),
            )

            refund_amount = self._from_razorpay_amount(refund.get("amount", 0), refund.get("currency", payment_curr))
            refund_status = "completed" if refund.get("status") in ("processed", "succeeded") else refund.get("status", "pending")

            logger.info(
                "razorpay_refund_processed",
                refund_id=refund.get("id"),
                payment_id=gateway_payment_id,
                amount=refund_amount,
                status=refund_status,
            )

            return RefundResult(
                gateway_refund_id=refund.get("id"),
                status=refund_status,
                amount=refund_amount,
            )
        except Exception as e:
            logger.error("razorpay_refund_failed", error=str(e), gateway_payment_id=gateway_payment_id)
            raise

    async def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
    ) -> dict[str, Any]:
        """Verify Razorpay webhook signature using HMAC-SHA256."""
        if not settings.razorpay_webhook_secret:
            raise ValueError("RAZORPAY_WEBHOOK_SECRET is required")

        expected_signature = hmac.new(
            settings.razorpay_webhook_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_signature, signature):
            logger.warning("razorpay_webhook_signature_invalid")
            raise ValueError("Invalid Razorpay webhook signature")

        event = json.loads(payload)
        logger.info(
            "razorpay_webhook_verified",
            event_type=event.get("event"),
            account_id=event.get("account_id"),
        )

        return {
            "event_id": event.get("event"),
            "event_type": event.get("event"),
            "data": event.get("payload", {}),
            "created": event.get("created_at"),
        }

    async def get_payment_status(self, gateway_payment_id: str) -> dict[str, Any]:
        """Get payment status from Razorpay."""
        try:
            loop = asyncio.get_event_loop()
            payment = await loop.run_in_executor(
                None,
                lambda: self.client.payment.fetch(gateway_payment_id),
            )
            return {
                "gateway_payment_id": payment["id"],
                "status": payment["status"],
                "amount": self._from_razorpay_amount(payment["amount"], payment["currency"]),
                "currency": payment["currency"],
                "method": payment.get("method"),
            }
        except Exception as e:
            logger.error("razorpay_status_failed", error=str(e))
            raise
