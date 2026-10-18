"""
Payment Service — orchestrates entire payment lifecycle.

Handles payment creation, capture, gateway routing, idempotency, and ledger recording.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from payment_server.config import settings
from payment_server.domain.gateways.base import PaymentGateway
from payment_server.domain.gateways.stripe_gateway import StripeGateway
from payment_server.domain.gateways.razorpay_gateway import RazorpayGateway
from shared.events.kafka_producer import save_outbox_event
from shared.observability.logging import get_logger

logger = get_logger(__name__)

# SQLAlchemy table references — using raw SQL via session to avoid circular model imports
# These map directly to the payments table from the migration


class PaymentServiceError(Exception):
    pass


class PaymentService:
    """Orchestrates payment creation, capture, and status management."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._gateways: dict[str, PaymentGateway] = {}

    def _get_gateway(self, gateway_name: str) -> PaymentGateway:
        """Get or create a payment gateway instance."""
        if gateway_name not in self._gateways:
            if gateway_name == "stripe":
                if not settings.stripe_secret_key:
                    from payment_server.domain.gateways.mock_gateway import MockPaymentGateway
                    self._gateways[gateway_name] = MockPaymentGateway()
                else:
                    self._gateways[gateway_name] = StripeGateway()
            elif gateway_name == "razorpay":
                if not settings.razorpay_key_id:
                    from payment_server.domain.gateways.mock_gateway import MockPaymentGateway
                    self._gateways[gateway_name] = MockPaymentGateway()
                else:
                    self._gateways[gateway_name] = RazorpayGateway()
            elif gateway_name == "mock":
                from payment_server.domain.gateways.mock_gateway import MockPaymentGateway
                self._gateways[gateway_name] = MockPaymentGateway()
            else:
                raise PaymentServiceError(f"Unsupported gateway: {gateway_name}")
        return self._gateways[gateway_name]

    async def create_payment(
        self,
        order_id: str,
        user_id: str,
        amount: float,
        currency: str,
        gateway: str,
        idempotency_key: str,
        customer_email: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a payment intent via the specified gateway.

        Idempotency: if a payment with the same idempotency_key exists, return it.
        """
        # Idempotency check
        existing = await self.session.execute(
            select("*").select_from(
                self.session.get_bind().dialect.identifier_preparer.format_table(
                    type("T", (), {"__tablename__": "payments"})
                )
            )
        ) if False else None  # Placeholder — we use text queries below

        from sqlalchemy import text
        result = await self.session.execute(
            text("SELECT id, gateway_payment_id, status FROM payments WHERE idempotency_key = :key"),
            {"key": idempotency_key},
        )
        existing_row = result.fetchone()
        if existing_row:
            logger.info("payment_idempotent_hit", payment_id=str(existing_row[0]))
            return {
                "payment_id": str(existing_row[0]),
                "gateway_payment_id": existing_row[1],
                "status": existing_row[2],
            }

        # Create payment intent via gateway
        gw = self._get_gateway(gateway)
        intent = await gw.create_payment_intent(
            amount=amount,
            currency=currency,
            order_id=order_id,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )

        gateway_payment_id = intent.get("id") if isinstance(intent, dict) else intent.gateway_payment_id
        gateway_order_id = intent.get("id") if isinstance(intent, dict) else intent.gateway_order_id
        intent_status = intent.get("status") if isinstance(intent, dict) else intent.status

        # Persist payment record
        payment_id = str(uuid.uuid4())
        await self.session.execute(
            text("""
                INSERT INTO payments (id, order_id, user_id, gateway, gateway_payment_id,
                    gateway_order_id, amount, currency, status, idempotency_key, metadata)
                VALUES (:id, :order_id, :user_id, :gateway, :gateway_payment_id,
                    :gateway_order_id, :amount, :currency, :status, :idempotency_key, :metadata)
            """),
            {
                "id": payment_id,
                "order_id": order_id,
                "user_id": user_id,
                "gateway": gateway,
                "gateway_payment_id": gateway_payment_id,
                "gateway_order_id": gateway_order_id,
                "amount": amount,
                "currency": currency,
                "status": intent_status,
                "idempotency_key": idempotency_key,
                "metadata": "{}",
            },
        )
        await self.session.commit()

        # Record ledger entry
        from payment_server.domain.services.ledger_service import LedgerService
        ledger = LedgerService(self.session)
        await ledger.record_entry(
            payment_id=payment_id,
            entry_type="payment_created",
            debit_account=f"customer:{user_id}",
            credit_account="platform:receivables",
            amount=amount,
            currency=currency,
            description=f"Payment created for order {order_id}",
        )

        logger.info(
            "payment_created",
            payment_id=payment_id,
            gateway=gateway,
            amount=amount,
            order_id=order_id,
        )

        client_secret = intent.get("client_secret") if isinstance(intent, dict) else intent.client_secret

        return {
            "payment_id": payment_id,
            "gateway_payment_id": gateway_payment_id,
            "gateway_order_id": gateway_order_id,
            "client_secret": client_secret,
            "status": intent_status,
            "amount": amount,
            "currency": currency,
        }

    async def capture_payment(self, payment_id: str) -> dict[str, Any]:
        """Capture an authorized payment."""
        from sqlalchemy import text

        result = await self.session.execute(
            text("SELECT gateway, gateway_payment_id, amount, currency, order_id FROM payments WHERE id = :id FOR UPDATE"),
            {"id": payment_id},
        )
        row = result.fetchone()
        if not row:
            raise PaymentServiceError(f"Payment {payment_id} not found")

        gateway_name, gateway_payment_id, amount, currency, order_id = row

        gw = self._get_gateway(gateway_name)
        capture_result = await gw.capture_payment(gateway_payment_id)

        # Update payment status
        await self.session.execute(
            text("""
                UPDATE payments SET status = 'captured', payment_method_type = :pm_type,
                    captured_at = :captured_at WHERE id = :id
            """),
            {
                "id": payment_id,
                "pm_type": capture_result.payment_method_type,
                "captured_at": datetime.now(timezone.utc),
            },
        )

        # Activate subscription if this is a platform subscription payment
        if order_id and order_id.startswith("sub-"):
            sub_id = order_id[4:]
            import httpx
            from payment_server.config import settings
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    resp = await client.post(f"{settings.merchant_server_url}/api/v1/subscriptions/activate/{sub_id}")
                    resp.raise_for_status()
                    logger.info("subscription_activated_via_http", subscription_id=sub_id, payment_id=payment_id)
                except Exception as ex:
                    logger.error("failed_to_activate_subscription_on_merchant_server", subscription_id=sub_id, error=str(ex))
        # Ledger entry
        from payment_server.domain.services.ledger_service import LedgerService
        ledger = LedgerService(self.session)
        await ledger.record_entry(
            payment_id=payment_id,
            entry_type="payment_captured",
            debit_account="platform:cash",
            credit_account="platform:receivables",
            amount=float(amount),
            currency=currency,
            description=f"Payment {payment_id} captured",
        )

        # Save event to outbox
        await save_outbox_event(
            db_session=self.session,
            topic="payments",
            event_type="payment.captured",
            payload={"payment_id": payment_id, "amount": float(amount), "gateway": gateway_name},
            source="payment-server",
            key=payment_id,
        )

        # Commit everything atomically
        await self.session.commit()

        return {
            "payment_id": payment_id,
            "status": "captured",
            "amount_captured": capture_result.amount_captured,
        }

    async def get_payment(self, payment_id: str) -> dict[str, Any] | None:
        from sqlalchemy import text
        result = await self.session.execute(
            text("SELECT id, order_id, gateway, gateway_payment_id, amount, currency, status, captured_at, created_at FROM payments WHERE id = :id"),
            {"id": payment_id},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "payment_id": str(row[0]),
            "order_id": str(row[1]),
            "gateway": row[2],
            "gateway_payment_id": row[3],
            "amount": float(row[4]),
            "currency": row[5],
            "status": row[6],
            "captured_at": str(row[7]) if row[7] else None,
            "created_at": str(row[8]),
        }
