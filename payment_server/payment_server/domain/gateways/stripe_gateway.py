"""
Stripe Gateway — production integration using the Stripe SDK.

Uses PaymentIntents API for SCA-compliant payment processing.
Real webhook signature verification. No mocks.
"""

from __future__ import annotations

import asyncio
from typing import Any

import stripe

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


class StripeGateway(PaymentGateway):
    """Stripe SDK integration — PaymentIntents, captures, refunds, webhooks.

    All operations use the Stripe Python SDK with proper error handling.
    Amounts are in the smallest currency unit (cents for USD).
    """

    def __init__(self) -> None:
        if not settings.stripe_secret_key:
            raise ValueError("STRIPE_SECRET_KEY is required")
        stripe.api_key = settings.stripe_secret_key

    def _to_stripe_amount(self, amount: float, currency: str) -> int:
        """Convert decimal amount to Stripe's smallest currency unit."""
        zero_decimal_currencies = {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga",
                                    "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf"}
        if currency.lower() in zero_decimal_currencies:
            return int(amount)
        return int(round(amount * 100))

    def _from_stripe_amount(self, amount: int, currency: str) -> float:
        """Convert Stripe's smallest unit back to decimal."""
        zero_decimal_currencies = {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga",
                                    "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf"}
        if currency.lower() in zero_decimal_currencies:
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
        """Create a Stripe PaymentIntent.

        Uses capture_method='manual' to allow separate authorization and capture,
        enabling the saga pattern to verify order state before capturing.
        """
        stripe_amount = self._to_stripe_amount(amount, currency)

        params: dict[str, Any] = {
            "amount": stripe_amount,
            "currency": currency.lower(),
            "capture_method": "manual",  # Authorize now, capture later
            "metadata": {
                "order_id": order_id,
                **(metadata or {}),
            },
            "description": f"Order {order_id}",
        }

        # Check for Stripe Connect split payouts setup (e.g. metadata has merchant stripe connected account)
        if metadata and "merchant_stripe_account_id" in metadata:
            connected_account = metadata["merchant_stripe_account_id"]
            # Platform fee: 5% of order subtotal
            platform_fee = int(round(stripe_amount * 0.05))
            params["application_fee_amount"] = platform_fee
            params["transfer_data"] = {
                "destination": connected_account,
            }
            logger.info("stripe_connect_configured", connected_account=connected_account, application_fee=platform_fee)

        if customer_email:
            params["receipt_email"] = customer_email

        if idempotency_key:
            params["idempotency_key"] = idempotency_key

        try:
            loop = asyncio.get_event_loop()
            intent = await loop.run_in_executor(
                None,
                lambda: stripe.PaymentIntent.create(**params),
            )

            logger.info(
                "stripe_payment_intent_created",
                payment_intent_id=intent.id,
                amount=amount,
                currency=currency,
                order_id=order_id,
            )

            payments_processed_total.labels(
                gateway="stripe", status="created", service="payment-server"
            ).inc()

            return PaymentIntentResult(
                gateway_payment_id=intent.id,
                gateway_order_id=None,
                client_secret=intent.client_secret,
                status=intent.status,
                amount=amount,
                currency=currency,
                metadata={"stripe_status": intent.status},
            )

        except stripe.StripeError as e:
            logger.error("stripe_payment_intent_failed", error=str(e), order_id=order_id)
            payments_processed_total.labels(
                gateway="stripe", status="failed", service="payment-server"
            ).inc()
            raise

    async def capture_payment(
        self,
        gateway_payment_id: str,
        amount: float | None = None,
    ) -> CaptureResult:
        """Capture an authorized PaymentIntent."""
        try:
            params: dict[str, Any] = {}
            if amount is not None:
                # For partial captures: need to know the currency
                # Stripe accepts amount_to_capture in smallest unit
                intent = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: stripe.PaymentIntent.retrieve(gateway_payment_id),
                )
                params["amount_to_capture"] = self._to_stripe_amount(amount, intent.currency)

            captured = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: stripe.PaymentIntent.capture(gateway_payment_id, **params),
            )

            amount_captured = self._from_stripe_amount(
                captured.amount_received, captured.currency
            )

            logger.info(
                "stripe_payment_captured",
                payment_intent_id=gateway_payment_id,
                amount_captured=amount_captured,
            )

            payments_processed_total.labels(
                gateway="stripe", status="captured", service="payment-server"
            ).inc()

            # Extract payment method type
            pm_type = None
            if captured.payment_method:
                try:
                    pm = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: stripe.PaymentMethod.retrieve(captured.payment_method),
                    )
                    pm_type = pm.type
                except Exception:
                    pass

            return CaptureResult(
                gateway_payment_id=gateway_payment_id,
                status="captured",
                amount_captured=amount_captured,
                payment_method_type=pm_type,
            )

        except stripe.StripeError as e:
            logger.error("stripe_capture_failed", error=str(e), payment_id=gateway_payment_id)
            raise

    async def refund_payment(
        self,
        gateway_payment_id: str,
        amount: float | None = None,
        reason: str | None = None,
    ) -> RefundResult:
        """Issue a full or partial refund on a captured PaymentIntent."""
        try:
            params: dict[str, Any] = {"payment_intent": gateway_payment_id}

            if amount is not None:
                intent = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: stripe.PaymentIntent.retrieve(gateway_payment_id),
                )
                params["amount"] = self._to_stripe_amount(amount, intent.currency)

            if reason:
                # Stripe supports: duplicate, fraudulent, requested_by_customer
                valid_reasons = {"duplicate", "fraudulent", "requested_by_customer"}
                if reason in valid_reasons:
                    params["reason"] = reason

            refund = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: stripe.Refund.create(**params),
            )

            refund_amount = self._from_stripe_amount(refund.amount, refund.currency)

            logger.info(
                "stripe_refund_created",
                refund_id=refund.id,
                payment_intent_id=gateway_payment_id,
                amount=refund_amount,
            )

            return RefundResult(
                gateway_refund_id=refund.id,
                status=refund.status,
                amount=refund_amount,
            )

        except stripe.StripeError as e:
            logger.error("stripe_refund_failed", error=str(e), payment_id=gateway_payment_id)
            raise

    async def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
    ) -> dict[str, Any]:
        """Verify a Stripe webhook signature and return the parsed event.

        Uses Stripe's official signature verification — rejects tampered payloads.
        """
        if not settings.stripe_webhook_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET is required for webhook verification")

        try:
            event = stripe.Webhook.construct_event(
                payload, signature, settings.stripe_webhook_secret
            )
            logger.info("stripe_webhook_verified", event_type=event.type, event_id=event.id)
            return {
                "event_id": event.id,
                "event_type": event.type,
                "data": event.data.object,
                "created": event.created,
            }
        except stripe.SignatureVerificationError as e:
            logger.warning("stripe_webhook_signature_invalid", error=str(e))
            raise ValueError(f"Invalid webhook signature: {e}")

    async def get_payment_status(self, gateway_payment_id: str) -> dict[str, Any]:
        """Retrieve the current status of a PaymentIntent."""
        try:
            intent = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: stripe.PaymentIntent.retrieve(gateway_payment_id),
            )
            return {
                "gateway_payment_id": intent.id,
                "status": intent.status,
                "amount": self._from_stripe_amount(intent.amount, intent.currency),
                "amount_received": self._from_stripe_amount(intent.amount_received, intent.currency),
                "currency": intent.currency,
            }
        except stripe.StripeError as e:
            logger.error("stripe_status_check_failed", error=str(e))
            raise
