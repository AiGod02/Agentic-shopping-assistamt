"""
Refund Service — full and partial refund handling.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from payment_server.domain.gateways.stripe_gateway import StripeGateway
from payment_server.domain.gateways.razorpay_gateway import RazorpayGateway
from shared.events.kafka_producer import publish_event
from shared.observability.logging import get_logger

logger = get_logger(__name__)


class RefundServiceError(Exception):
    pass


class RefundService:
    """Handles full and partial refunds through payment gateways."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_refund(
        self,
        payment_id: str,
        amount: float | None = None,
        reason: str | None = None,
        initiated_by: str | None = None,
    ) -> dict[str, Any]:
        """Issue a refund (full or partial).

        If amount is None, issues a full refund.
        """
        # Get payment details
        result = await self.session.execute(
            text("SELECT gateway, gateway_payment_id, amount, currency, status FROM payments WHERE id = :id"),
            {"id": payment_id},
        )
        row = result.fetchone()
        if not row:
            raise RefundServiceError(f"Payment {payment_id} not found")

        gateway_name, gateway_payment_id, total_amount, currency, status = row

        if status not in ("captured", "partially_refunded"):
            raise RefundServiceError(
                f"Cannot refund payment in status: {status}"
            )

        refund_amount = amount if amount is not None else float(total_amount)

        # Check remaining refundable amount
        existing_refunds = await self.session.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM refunds WHERE payment_id = :pid AND status IN ('completed', 'processing')"),
            {"pid": payment_id},
        )
        already_refunded = float(existing_refunds.scalar() or 0)

        if already_refunded + refund_amount > float(total_amount):
            raise RefundServiceError(
                f"Refund amount {refund_amount} exceeds remaining refundable amount "
                f"{float(total_amount) - already_refunded}"
            )

        # Execute refund via gateway
        if gateway_name == "stripe":
            gw = StripeGateway()
        elif gateway_name == "razorpay":
            gw = RazorpayGateway()
        else:
            raise RefundServiceError(f"Unsupported gateway: {gateway_name}")

        refund_result = await gw.refund_payment(
            gateway_payment_id, refund_amount, reason
        )

        # Persist refund record
        refund_id = str(uuid.uuid4())
        await self.session.execute(
            text("""
                INSERT INTO refunds (id, payment_id, gateway_refund_id, amount, reason, status, initiated_by, completed_at)
                VALUES (:id, :payment_id, :gateway_refund_id, :amount, :reason, :status, :initiated_by, :completed_at)
            """),
            {
                "id": refund_id,
                "payment_id": payment_id,
                "gateway_refund_id": refund_result.gateway_refund_id,
                "amount": refund_amount,
                "reason": reason,
                "status": refund_result.status if refund_result.status != "succeeded" else "completed",
                "initiated_by": initiated_by,
                "completed_at": datetime.now(timezone.utc) if refund_result.status == "succeeded" else None,
            },
        )

        # Update payment status
        new_status = "refunded" if (already_refunded + refund_amount) >= float(total_amount) else "partially_refunded"
        await self.session.execute(
            text("UPDATE payments SET status = :status WHERE id = :id"),
            {"status": new_status, "id": payment_id},
        )
        await self.session.commit()

        # Ledger entry
        from payment_server.domain.services.ledger_service import LedgerService
        ledger = LedgerService(self.session)
        await ledger.record_entry(
            refund_id=refund_id,
            payment_id=payment_id,
            entry_type="refund_issued",
            debit_account="platform:cash",
            credit_account=f"customer:refund",
            amount=refund_amount,
            currency=currency,
            description=f"Refund for payment {payment_id}: {reason or 'no reason'}",
        )

        # Publish event
        await publish_event(
            topic="payments",
            event_type="refund.issued",
            payload={
                "refund_id": refund_id,
                "payment_id": payment_id,
                "amount": refund_amount,
                "reason": reason,
            },
            source="payment-server",
            key=payment_id,
        )

        logger.info(
            "refund_created",
            refund_id=refund_id,
            payment_id=payment_id,
            amount=refund_amount,
        )

        return {
            "refund_id": refund_id,
            "payment_id": payment_id,
            "amount": refund_amount,
            "status": new_status,
            "gateway_refund_id": refund_result.gateway_refund_id,
        }
