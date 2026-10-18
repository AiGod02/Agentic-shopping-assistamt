"""
Subscriptions API — platform service subscription pricing and management.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.models.subscription import Subscription
from shared.auth.rbac import get_current_user
from shared.db.session import get_db
from shared.schemas.base import BaseSchema

router = APIRouter()


# ── Configuration Tiers ──────────────────────────────────────────

PLANS = {
    "starter": {"name": "Starter Plan", "price": 29.00, "description": "Ideal for small independent vendors"},
    "growth": {"name": "Growth Plan", "price": 79.00, "description": "Best for expanding operations"},
    "enterprise": {"name": "Enterprise Plan", "price": 199.00, "description": "Custom integrations and high capacity"},
}


class SubscribeRequest(BaseModel):
    plan_name: str = Field(..., pattern="^(starter|growth|enterprise)$")


class SubscriptionResponse(BaseSchema):
    id: str
    user_id: str
    plan_name: str
    status: str
    price: float
    billing_cycle: str
    current_period_start: datetime
    current_period_end: datetime
    client_secret: str | None = None
    payment_id: str | None = None


@router.get("/plans")
async def list_plans():
    """List available service subscription tiers and prices."""
    return PLANS


@router.post("/subscribe", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def subscribe(
    body: SubscribeRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Subscribe current user/merchant to a platform service plan."""
    from sqlalchemy import select, update
    import httpx
    from merchant_server.config import settings

    user_uuid = uuid.UUID(user.sub)
    plan = PLANS[body.plan_name]

    # Deactivate existing active subscriptions for this user securely
    await db.execute(
        update(Subscription)
        .where(Subscription.user_id == user_uuid, Subscription.status == "active")
        .values(status="deactivated")
    )

    # Establish new subscription period (initially pending payment)
    now = datetime.now(timezone.utc)
    end_date = now + timedelta(days=30)

    sub = Subscription(
        user_id=user_uuid,
        plan_name=body.plan_name,
        price=plan["price"],
        billing_cycle="monthly",
        current_period_start=now,
        current_period_end=end_date,
        status="pending_payment",
    )
    db.add(sub)
    await db.flush()

    # Call payment server to create platform-level subscription payment intent
    client_secret = None
    payment_id = None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.payment_server_url}/api/v1/payments/create",
                json={
                    "order_id": f"sub-{sub.id}",
                    "user_id": str(user_uuid),
                    "amount": float(plan["price"]),
                    "currency": "USD",
                    "gateway": "stripe",
                    "idempotency_key": f"sub-pay-{sub.id}-{now.timestamp()}",
                }
            )
            resp.raise_for_status()
            payment_data = resp.json()
            payment_id = payment_data.get("payment_id")
            client_secret = payment_data.get("client_secret")
    except Exception as e:
        # Rollback and raise if payment registration fails
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to register subscription payment: {str(e)}"
        )

    # Save payment_id reference
    sub.payment_id = payment_id
    await db.flush()
    await db.refresh(sub)

    return SubscriptionResponse(
        id=str(sub.id),
        user_id=str(sub.user_id),
        plan_name=sub.plan_name,
        status=sub.status,
        price=float(sub.price),
        billing_cycle=sub.billing_cycle,
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        client_secret=client_secret,
        payment_id=payment_id,
    )


@router.get("/me", response_model=SubscriptionResponse)
async def get_my_subscription(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve the current user's active platform subscription status."""
    from sqlalchemy import select

    user_uuid = uuid.UUID(user.sub)
    stmt = (
        select(Subscription)
        .where(Subscription.user_id == user_uuid, Subscription.status == "active")
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    sub = result.scalar_one_or_none()

    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active platform subscription found",
        )

    return SubscriptionResponse(
        id=str(sub.id),
        user_id=str(sub.user_id),
        plan_name=sub.plan_name,
        status=sub.status,
        price=float(sub.price),
        billing_cycle=sub.billing_cycle,
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
    )


@router.post("/activate/{subscription_id}", tags=["internal"])
async def activate_subscription(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """Internal callback to activate subscription upon successful platform checkout.

    Maintains 100% database schema decoupling/isolation between services.
    """
    from sqlalchemy import update

    await db.execute(
        update(Subscription)
        .where(Subscription.id == subscription_id)
        .values(status="active")
    )
    return {"status": "activated", "subscription_id": str(subscription_id)}
