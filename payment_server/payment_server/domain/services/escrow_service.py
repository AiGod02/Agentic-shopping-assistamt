"""
Escrow Service — hold, conditional release, and refund of escrowed funds.

Used for rental deposits, service advance payments, etc.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.kafka_producer import publish_event
from shared.observability.logging import get_logger

logger = get_logger(__name__)


class EscrowServiceError(Exception):
    pass


class EscrowService:
    """Manages escrow holds for booking-type transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_hold(
        self,
        payment_id: str,
        order_id: str,
        amount: float,
        currency: str = "USD",
        release_conditions: dict[str, Any] | None = None,
        release_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Create an escrow hold on captured payment funds."""
        escrow_id = str(uuid.uuid4())

        await self.session.execute(
            text("""
                INSERT INTO escrow_holds (id, payment_id, order_id, amount, currency, status,
                    release_conditions, release_at)
                VALUES (:id, :payment_id, :order_id, :amount, :currency, 'held',
                    :conditions, :release_at)
            """),
            {
                "id": escrow_id,
                "payment_id": payment_id,
                "order_id": order_id,
                "amount": amount,
                "currency": currency,
                "conditions": str(release_conditions or {}),
                "release_at": release_at,
            },
        )
        await self.session.commit()

        # Ledger entry
        from payment_server.domain.services.ledger_service import LedgerService
        ledger = LedgerService(self.session)
        await ledger.record_entry(
            payment_id=payment_id,
            escrow_id=escrow_id,
            entry_type="escrow_hold",
            debit_account="platform:cash",
            credit_account="platform:escrow",
            amount=amount,
            currency=currency,
            description=f"Escrow hold for order {order_id}",
        )

        logger.info("escrow_created", escrow_id=escrow_id, amount=amount, order_id=order_id)

        return {
            "escrow_id": escrow_id,
            "amount": amount,
            "currency": currency,
            "status": "held",
        }

    async def release_hold(self, escrow_id: str) -> dict[str, Any]:
        """Release escrowed funds to the merchant."""
        result = await self.session.execute(
            text("SELECT payment_id, order_id, amount, currency, status FROM escrow_holds WHERE id = :id"),
            {"id": escrow_id},
        )
        row = result.fetchone()
        if not row:
            raise EscrowServiceError(f"Escrow {escrow_id} not found")

        payment_id, order_id, amount, currency, status = row
        if status != "held":
            raise EscrowServiceError(f"Escrow is not in 'held' status: {status}")

        await self.session.execute(
            text("UPDATE escrow_holds SET status = 'released', released_at = :now WHERE id = :id"),
            {"id": escrow_id, "now": datetime.now(timezone.utc)},
        )
        await self.session.commit()

        # Ledger entry
        from payment_server.domain.services.ledger_service import LedgerService
        ledger = LedgerService(self.session)
        await ledger.record_entry(
            payment_id=payment_id,
            escrow_id=escrow_id,
            entry_type="escrow_release",
            debit_account="platform:escrow",
            credit_account=f"merchant:payout",
            amount=float(amount),
            currency=currency,
            description=f"Escrow released for order {order_id}",
        )

        await publish_event(
            topic="payments",
            event_type="escrow.released",
            payload={"escrow_id": escrow_id, "amount": float(amount), "order_id": str(order_id)},
            source="payment-server",
        )

        logger.info("escrow_released", escrow_id=escrow_id, amount=float(amount))
        return {"escrow_id": escrow_id, "status": "released", "amount": float(amount)}

    async def refund_hold(self, escrow_id: str) -> dict[str, Any]:
        """Refund escrowed funds back to the customer."""
        result = await self.session.execute(
            text("SELECT payment_id, order_id, amount, currency, status FROM escrow_holds WHERE id = :id"),
            {"id": escrow_id},
        )
        row = result.fetchone()
        if not row:
            raise EscrowServiceError(f"Escrow {escrow_id} not found")

        payment_id, order_id, amount, currency, status = row
        if status != "held":
            raise EscrowServiceError(f"Cannot refund escrow in status: {status}")

        await self.session.execute(
            text("UPDATE escrow_holds SET status = 'refunded', released_at = :now WHERE id = :id"),
            {"id": escrow_id, "now": datetime.now(timezone.utc)},
        )
        await self.session.commit()

        logger.info("escrow_refunded", escrow_id=escrow_id, amount=float(amount))
        return {"escrow_id": escrow_id, "status": "refunded", "amount": float(amount)}
