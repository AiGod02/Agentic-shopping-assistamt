"""
Ledger Service — double-entry accounting for all financial transactions.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.observability.logging import get_logger

logger = get_logger(__name__)

_ledger_table_verified: bool = False


class LedgerService:
    """Double-entry ledger — every financial event creates a debit+credit entry."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_entry(
        self,
        entry_type: str,
        debit_account: str,
        credit_account: str,
        amount: float,
        currency: str = "USD",
        description: str | None = None,
        payment_id: str | None = None,
        refund_id: str | None = None,
        escrow_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Record a ledger entry.

        Entry types:
        - payment_created: Customer charged, platform receives
        - payment_captured: Authorized funds captured
        - refund_issued: Funds returned to customer
        - escrow_hold: Funds moved to escrow
        - escrow_release: Escrow released to merchant
        - commission: Platform commission deducted
        - payout: Merchant payout executed
        """
        import json
        entry_uuid = uuid.uuid4()
        pid_uuid = None
        if payment_id:
            try:
                pid_uuid = uuid.UUID(str(payment_id))
            except Exception:
                pid_uuid = None

        rid_uuid = None
        if refund_id:
            try:
                rid_uuid = uuid.UUID(str(refund_id))
            except Exception:
                rid_uuid = None

        eid_uuid = None
        if escrow_id:
            try:
                eid_uuid = uuid.UUID(str(escrow_id))
            except Exception:
                eid_uuid = None

        global _ledger_table_verified
        if not _ledger_table_verified:
            try:
                await self.session.execute(text("""
                    CREATE TABLE IF NOT EXISTS ledger_entries (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        payment_id UUID REFERENCES payments(id),
                        refund_id UUID,
                        escrow_id UUID,
                        entry_type VARCHAR(50) NOT NULL,
                        debit_account VARCHAR(100) NOT NULL,
                        credit_account VARCHAR(100) NOT NULL,
                        amount NUMERIC(12, 2) NOT NULL,
                        currency VARCHAR(3) DEFAULT 'USD',
                        description TEXT,
                        metadata JSONB DEFAULT '{}',
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """))
                _ledger_table_verified = True
            except Exception as ddl_ex:
                logger.warning("ledger_entries_table_verify_failed", error=str(ddl_ex))

        await self.session.execute(
            text("""
                INSERT INTO ledger_entries (id, payment_id, refund_id, escrow_id, entry_type,
                    debit_account, credit_account, amount, currency, description, metadata)
                VALUES (:id, :payment_id, :refund_id, :escrow_id, :entry_type,
                    :debit_account, :credit_account, :amount, :currency, :description, CAST(:metadata AS jsonb))
            """),
            {
                "id": entry_uuid,
                "payment_id": pid_uuid,
                "refund_id": rid_uuid,
                "escrow_id": eid_uuid,
                "entry_type": entry_type,
                "debit_account": debit_account,
                "credit_account": credit_account,
                "amount": amount,
                "currency": currency,
                "description": description,
                "metadata": json.dumps(metadata or {}),
            },
        )
        entry_id = str(entry_uuid)

        logger.info(
            "ledger_entry_recorded",
            entry_id=entry_id,
            entry_type=entry_type,
            debit=debit_account,
            credit=credit_account,
            amount=amount,
        )

        return entry_id

    async def get_entries_for_payment(self, payment_id: str) -> list[dict[str, Any]]:
        """Get all ledger entries for a payment."""
        try:
            pid = uuid.UUID(str(payment_id))
        except Exception:
            pid = payment_id
        try:
            result = await self.session.execute(
                text("""
                    SELECT id, entry_type, debit_account, credit_account, amount, currency, description, created_at
                    FROM ledger_entries WHERE payment_id = :pid ORDER BY created_at
                """),
                {"pid": pid},
            )
            return [
                {
                    "entry_id": str(row[0]),
                    "entry_type": row[1],
                    "debit_account": row[2],
                    "credit_account": row[3],
                    "amount": float(row[4]),
                    "currency": row[5],
                    "description": row[6],
                    "created_at": str(row[7]),
                }
                for row in result.fetchall()
            ]
        except Exception:
            return []

    async def get_account_balance(self, account: str) -> dict[str, float]:
        """Calculate the balance of an account across all currencies."""
        try:
            result = await self.session.execute(
                text("""
                    SELECT currency,
                        COALESCE(SUM(CASE WHEN debit_account = :acct THEN amount ELSE 0 END), 0) as debits,
                        COALESCE(SUM(CASE WHEN credit_account = :acct THEN amount ELSE 0 END), 0) as credits
                    FROM ledger_entries
                    WHERE debit_account = :acct OR credit_account = :acct
                    GROUP BY currency
                """),
                {"acct": account},
            )
            balances = {}
            for row in result.fetchall():
                currency, debits, credits = row
                balances[currency] = float(credits) - float(debits)
            return balances
        except Exception:
            return {}
