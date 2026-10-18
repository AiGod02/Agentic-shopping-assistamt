"""
Payments API — create, capture, refund, escrow, and query payments.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from payment_server.domain.services.escrow_service import EscrowService, EscrowServiceError
from payment_server.domain.services.fraud_service import FraudService
from payment_server.domain.services.payment_service import PaymentService, PaymentServiceError
from payment_server.domain.services.refund_service import RefundService, RefundServiceError
from payment_server.domain.services.ledger_service import LedgerService
from shared.auth.jwt_handler import TokenPayload
from shared.auth.rbac import Role, get_current_user, get_optional_user, require_permission
from shared.db.session import get_db

router = APIRouter()


async def _verify_payment_ownership(payment_id: str, user: TokenPayload, db: AsyncSession) -> None:
    """Verify that the payment belongs to the current user or merchant."""
    if user.role in (Role.ADMIN, "admin"):
        return
    from sqlalchemy import text
    result = await db.execute(
        text("""
            SELECT p.user_id, l.merchant_id
            FROM payments p
            LEFT JOIN orders o ON p.order_id = o.id
            LEFT JOIN order_items oi ON o.id = oi.order_id
            LEFT JOIN listings l ON oi.listing_id = l.id
            WHERE p.id = :id
        """),
        {"id": payment_id},
    )
    rows = result.fetchall()
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

    is_owner = False
    for u_id, m_id in rows:
        if u_id and str(u_id) == str(user.sub):
            is_owner = True
            break
        if user.merchant_id and m_id and str(m_id) == str(user.merchant_id):
            is_owner = True
            break
    if not is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You do not have permission for this payment",
        )


# ── Request Schemas ──────────────────────────────────────────────

class CreatePaymentRequest(BaseModel):
    order_id: str
    user_id: str
    amount: float = Field(..., gt=0)
    currency: str = "USD"
    gateway: str = Field(..., description="stripe | razorpay")
    idempotency_key: str
    customer_email: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RefundRequest(BaseModel):
    amount: float | None = None  # None = full refund
    reason: str | None = None
    initiated_by: str | None = None


class EscrowHoldRequest(BaseModel):
    payment_id: str
    order_id: str
    amount: float = Field(..., gt=0)
    currency: str = "USD"
    release_conditions: dict[str, Any] = Field(default_factory=dict)


# ── Endpoints ─────────────────────────────────────────────────────

@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_payment(
    body: CreatePaymentRequest,
    user: TokenPayload | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    x_internal_service: str | None = Header(default=None),
):
    """Create a payment intent through the specified gateway.

    Accepts authenticated users OR internal service calls from merchant-server
    (identified by X-Internal-Service: merchant-server header).

    Flow:
    1. Auth check (user JWT or internal service header)
    2. Fraud check
    3. Create payment intent via gateway
    4. Store payment record with idempotency key
    5. Record ledger entry
    """
    # Reject unauthenticated external callers (no JWT, no internal service marker)
    if user is None and x_internal_service != "merchant-server":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Fraud check
    fraud = FraudService(db)
    check = await fraud.check_payment(
        user_id=body.user_id,
        amount=body.amount,
        currency=body.currency,
    )

    if not check.approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Payment declined by fraud check",
                "risk_score": check.risk_score,
                "reasons": check.reasons,
            },
        )

    service = PaymentService(db)
    try:
        result = await service.create_payment(
            order_id=body.order_id,
            user_id=body.user_id,
            amount=body.amount,
            currency=body.currency,
            gateway=body.gateway,
            idempotency_key=body.idempotency_key,
            customer_email=body.customer_email,
            metadata=body.metadata,
        )
        return result
    except PaymentServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{payment_id}/capture")
async def capture_payment(
    payment_id: str,
    user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Capture an authorized payment."""
    await _verify_payment_ownership(payment_id, user, db)
    service = PaymentService(db)
    try:
        result = await service.capture_payment(payment_id)
        return result
    except PaymentServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{payment_id}")
async def get_payment(payment_id: str, db: AsyncSession = Depends(get_db)):
    """Get payment details."""
    service = PaymentService(db)
    payment = await service.get_payment(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


@router.post("/{payment_id}/refund")
async def refund_payment(
    payment_id: str,
    body: RefundRequest,
    user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Issue a full or partial refund."""
    await _verify_payment_ownership(payment_id, user, db)
    service = RefundService(db)
    try:
        result = await service.create_refund(
            payment_id=payment_id,
            amount=body.amount,
            reason=body.reason,
            initiated_by=body.initiated_by,
        )
        return result
    except RefundServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/escrow/hold")
async def create_escrow_hold(
    body: EscrowHoldRequest,
    user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an escrow hold."""
    service = EscrowService(db)
    try:
        result = await service.create_hold(
            payment_id=body.payment_id,
            order_id=body.order_id,
            amount=body.amount,
            currency=body.currency,
            release_conditions=body.release_conditions,
        )
        return result
    except EscrowServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/escrow/{escrow_id}/release")
async def release_escrow(
    escrow_id: str,
    user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Release escrowed funds to merchant."""
    service = EscrowService(db)
    try:
        return await service.release_hold(escrow_id)
    except EscrowServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{payment_id}/ledger")
async def get_payment_ledger(payment_id: str, db: AsyncSession = Depends(get_db)):
    """Get all ledger entries for a payment."""
    service = LedgerService(db)
    entries = await service.get_entries_for_payment(payment_id)
    return {"payment_id": payment_id, "entries": entries}
