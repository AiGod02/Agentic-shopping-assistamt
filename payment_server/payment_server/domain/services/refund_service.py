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
        # Normalize payment_id to UUID
        try:
            pid_uuid = uuid.UUID(str(payment_id))
        except Exception:
            pid_uuid = payment_id

        # Get payment details
        result = await self.session.execute(
            text("SELECT gateway, gateway_payment_id, gateway_order_id, amount, currency, status FROM payments WHERE id = :id"),
            {"id": pid_uuid},
        )
        row = result.fetchone()
        if not row:
            raise RefundServiceError(f"Payment {payment_id} not found")

        gateway_name, gateway_payment_id, gateway_order_id, total_amount, currency, status = row

        if status not in ("captured", "partially_refunded"):
            raise RefundServiceError(
                f"Cannot refund payment in status: {status}"
            )

        # For Razorpay, if payment_id was not set, resolve from order
        if gateway_name == "razorpay" and not gateway_payment_id and gateway_order_id:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                rz_gw = RazorpayGateway()
                order_payments = await loop.run_in_executor(
                    None,
                    lambda: rz_gw.client.order.payments(gateway_order_id),
                )
                if order_payments and order_payments.get("items"):
                    gateway_payment_id = order_payments["items"][0]["id"]
                    await self.session.execute(
                        text("UPDATE payments SET gateway_payment_id = :gw_pid WHERE id = :id"),
                        {"gw_pid": gateway_payment_id, "id": pid_uuid},
                    )
                    await self.session.flush()
            except Exception as e:
                logger.error("razorpay_order_payments_fetch_failed", error=str(e), order_id=gateway_order_id)

        if not gateway_payment_id:
            raise RefundServiceError(
                f"Cannot refund payment {payment_id}: No gateway payment ID found. "
                f"Ensure the payment was completed and captured on {gateway_name}."
            )

        refund_amount = amount if amount is not None else float(total_amount)

        # Check remaining refundable amount
        existing_refunds = await self.session.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM refunds WHERE payment_id = :pid AND status IN ('completed', 'processing', 'succeeded')"),
            {"pid": pid_uuid},
        )
        already_refunded = float(existing_refunds.scalar() or 0)

        if already_refunded + refund_amount > float(total_amount):
            raise RefundServiceError(
                f"Refund amount {refund_amount} exceeds remaining refundable amount "
                f"{float(total_amount) - already_refunded}"
            )

        # Execute refund via gateway
        try:
            if gateway_name == "stripe":
                gw = StripeGateway()
                refund_result = await gw.refund_payment(
                    gateway_payment_id, refund_amount, reason
                )
            elif gateway_name == "razorpay":
                gw = RazorpayGateway()
                refund_result = await gw.refund_payment(
                    gateway_payment_id, refund_amount, reason, currency=currency or "INR"
                )
            else:
                raise RefundServiceError(f"Unsupported gateway: {gateway_name}")
        except Exception as e:
            logger.error("gateway_refund_failed", gateway=gateway_name, error=str(e), payment_id=payment_id)
            raise RefundServiceError(f"Gateway refund failed on {gateway_name}: {e}")

        # Validate initiated_by against users table to prevent FK violations
        init_by_uuid: uuid.UUID | None = None
        if initiated_by:
            try:
                candidate_uuid = uuid.UUID(str(initiated_by))
                user_check = await self.session.execute(
                    text("SELECT 1 FROM users WHERE id = :uid"),
                    {"uid": candidate_uuid},
                )
                if user_check.scalar():
                    init_by_uuid = candidate_uuid
            except Exception:
                init_by_uuid = None

        # Persist refund record
        refund_uuid = uuid.uuid4()
        refund_status = "completed" if refund_result.status in ("succeeded", "completed", "processed") else refund_result.status
        await self.session.execute(
            text("""
                INSERT INTO refunds (id, payment_id, gateway_refund_id, amount, reason, status, initiated_by, completed_at)
                VALUES (:id, :payment_id, :gateway_refund_id, :amount, :reason, :status, :initiated_by, :completed_at)
            """),
            {
                "id": refund_uuid,
                "payment_id": pid_uuid,
                "gateway_refund_id": refund_result.gateway_refund_id,
                "amount": refund_amount,
                "reason": reason,
                "status": refund_status,
                "initiated_by": init_by_uuid,
                "completed_at": datetime.now(timezone.utc) if refund_status == "completed" else None,
            },
        )

        # Update payment status
        new_status = "refunded" if (already_refunded + refund_amount) >= float(total_amount) else "partially_refunded"
        await self.session.execute(
            text("UPDATE payments SET status = :status WHERE id = :id"),
            {"status": new_status, "id": pid_uuid},
        )
        await self.session.commit()

        # Ledger entry
        from payment_server.domain.services.ledger_service import LedgerService
        ledger = LedgerService(self.session)
        await ledger.record_entry(
            refund_id=str(refund_uuid),
            payment_id=str(payment_id),
            entry_type="refund_issued",
            debit_account="platform:cash",
            credit_account="customer:refund",
            amount=refund_amount,
            currency=currency or "USD",
            description=f"Refund for payment {payment_id}: {reason or 'no reason'}",
        )

        # Publish event
        await publish_event(
            topic="payments",
            event_type="refund.issued",
            payload={
                "refund_id": str(refund_uuid),
                "payment_id": str(payment_id),
                "amount": refund_amount,
                "reason": reason,
            },
            source="payment-server",
            key=str(payment_id),
        )

        logger.info(
            "refund_created",
            refund_id=str(refund_uuid),
            payment_id=str(payment_id),
            amount=refund_amount,
        )

        return {
            "refund_id": str(refund_uuid),
            "payment_id": str(payment_id),
            "amount": refund_amount,
            "status": new_status,
            "gateway_refund_id": refund_result.gateway_refund_id,
        }

