"""
Fraud Service — velocity checks, amount thresholds, and risk scoring.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.redis_client import get_redis
from shared.observability.logging import get_logger

logger = get_logger(__name__)


class FraudCheckResult:
    def __init__(self, approved: bool, risk_score: float, reasons: list[str]) -> None:
        self.approved = approved
        self.risk_score = risk_score  # 0.0 (safe) to 1.0 (fraudulent)
        self.reasons = reasons


class FraudService:
    """Pre-payment fraud checking with velocity limits and amount thresholds."""

    # Configurable thresholds
    MAX_AMOUNT_SINGLE = 50000.0  # Max single transaction
    MAX_DAILY_AMOUNT = 200000.0  # Max daily total per user
    MAX_DAILY_TRANSACTIONS = 100  # Max transactions per user per day
    MAX_HOURLY_TRANSACTIONS = 50
    HIGH_RISK_AMOUNT = 25000.0  # Flag for review

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def check_payment(
        self,
        user_id: str,
        amount: float,
        currency: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> FraudCheckResult:
        """Run fraud checks before processing a payment.

        Checks:
        1. Single transaction amount limit
        2. Daily transaction count (velocity)
        3. Hourly transaction count (velocity)
        4. Daily cumulative amount
        5. IP reputation (Redis-based)
        """
        reasons: list[str] = []
        risk_score = 0.0

        # 1. Amount threshold
        if amount > self.MAX_AMOUNT_SINGLE:
            reasons.append(f"Amount {amount} exceeds single transaction limit {self.MAX_AMOUNT_SINGLE}")
            risk_score += 0.4

        # 2. High-value flag
        if amount > self.HIGH_RISK_AMOUNT:
            reasons.append(f"High-value transaction: {amount}")
            risk_score += 0.1

        # 3. Velocity check — daily transactions
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        result = await self.session.execute(
            text("""
                SELECT COUNT(*), COALESCE(SUM(amount), 0)
                FROM payments
                WHERE user_id = :uid AND created_at >= :since AND status != 'failed'
            """),
            {"uid": user_id, "since": day_start},
        )
        row = result.fetchone()
        daily_count = row[0] if row else 0
        daily_amount = float(row[1]) if row else 0.0

        if daily_count >= self.MAX_DAILY_TRANSACTIONS:
            reasons.append(f"Daily transaction limit exceeded: {daily_count}/{self.MAX_DAILY_TRANSACTIONS}")
            risk_score += 0.3

        if daily_amount + amount > self.MAX_DAILY_AMOUNT:
            reasons.append(
                f"Daily amount would exceed limit: {daily_amount + amount}/{self.MAX_DAILY_AMOUNT}"
            )
            risk_score += 0.3

        # 4. Hourly velocity
        hour_start = now - timedelta(hours=1)
        result = await self.session.execute(
            text("""
                SELECT COUNT(*) FROM payments
                WHERE user_id = :uid AND created_at >= :since AND status != 'failed'
            """),
            {"uid": user_id, "since": hour_start},
        )
        hourly_count = (result.scalar() or 0)
        if hourly_count >= self.MAX_HOURLY_TRANSACTIONS:
            reasons.append(f"Hourly transaction limit exceeded: {hourly_count}/{self.MAX_HOURLY_TRANSACTIONS}")
            risk_score += 0.2

        # 5. IP reputation check (Redis)
        if ip_address:
            try:
                redis = await get_redis()
                ip_key = f"fraud:ip_failures:{ip_address}"
                failures = await redis.get(ip_key)
                if failures and int(failures) >= 5:
                    reasons.append(f"IP {ip_address} has {failures} recent failures")
                    risk_score += 0.3
            except Exception:
                pass  # If Redis is down, don't block payment

        # Normalize risk score
        risk_score = min(risk_score, 1.0)

        # Decision
        approved = risk_score < 0.5  # Configurable threshold

        if not approved:
            logger.warning(
                "fraud_check_failed",
                user_id=user_id,
                amount=amount,
                risk_score=risk_score,
                reasons=reasons,
            )
        else:
            logger.info(
                "fraud_check_passed",
                user_id=user_id,
                amount=amount,
                risk_score=risk_score,
            )

        return FraudCheckResult(
            approved=approved,
            risk_score=risk_score,
            reasons=reasons,
        )

    async def record_ip_failure(self, ip_address: str) -> None:
        """Record a payment failure from an IP for reputation tracking."""
        try:
            redis = await get_redis()
            key = f"fraud:ip_failures:{ip_address}"
            await redis.incr(key)
            await redis.expire(key, 86400)  # 24-hour window
        except Exception:
            pass
