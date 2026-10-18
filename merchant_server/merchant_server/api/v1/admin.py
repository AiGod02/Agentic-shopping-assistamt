"""
Admin API — platform administration, client management, and subscription tracking.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.models.merchant import Merchant
from merchant_server.domain.models.user import User
from merchant_server.domain.models.subscription import Subscription
from shared.auth.rbac import Role, require_role, get_current_user
from shared.db.session import get_db
from shared.schemas.base import BaseSchema, PaginatedResponse

router = APIRouter()


class AdminUserResponse(BaseSchema):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


class AdminMerchantResponse(BaseSchema):
    id: str
    business_name: str
    business_type: str
    verification_status: str
    is_active: bool
    email: str


class AdminSubscriptionResponse(BaseSchema):
    id: str
    user_email: str
    plan_name: str
    status: str
    price: float
    current_period_end: datetime


@router.get(
    "/users",
    response_model=PaginatedResponse[AdminUserResponse],
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def list_users(
    role_filter: str | None = Query(None, alias="role"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List system users with pagination."""
    from sqlalchemy import select, func, and_

    conditions = []
    if role_filter:
        conditions.append(User.role == role_filter)

    where = and_(*conditions) if conditions else True

    # Count total
    count_stmt = select(func.count()).select_from(User).where(where)
    total = (await db.execute(count_stmt)).scalar() or 0

    # Fetch users
    stmt = (
        select(User)
        .where(where)
        .order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    users = result.scalars().all()

    return PaginatedResponse.create(
        items=[
            AdminUserResponse(
                id=str(u.id),
                email=u.email,
                full_name=u.full_name,
                role=u.role,
                is_active=u.is_active,
                created_at=u.created_at,
            )
            for u in users
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/users/{user_id}/toggle-active",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def toggle_user_active(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Toggle a user's active/deactivated state."""
    from sqlalchemy import select

    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = not user.is_active
    await db.flush()

    return {"status": "success", "is_active": user.is_active}


@router.get(
    "/merchants",
    response_model=PaginatedResponse[AdminMerchantResponse],
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def list_merchants(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all merchants details for verification or management."""
    from sqlalchemy import select, func

    count_stmt = select(func.count()).select_from(Merchant)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(Merchant, User.email)
        .join(User, Merchant.user_id == User.id)
        .order_by(Merchant.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return PaginatedResponse.create(
        items=[
            AdminMerchantResponse(
                id=str(row[0].id),
                business_name=row[0].business_name,
                business_type=row[0].business_type,
                verification_status=row[0].verification_status,
                is_active=row[0].is_active,
                email=row[1],
            )
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/subscriptions",
    response_model=PaginatedResponse[AdminSubscriptionResponse],
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def list_subscriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all system subscriptions for billing overview."""
    from sqlalchemy import select, func

    count_stmt = select(func.count()).select_from(Subscription)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(Subscription, User.email)
        .join(User, Subscription.user_id == User.id)
        .order_by(Subscription.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return PaginatedResponse.create(
        items=[
            AdminSubscriptionResponse(
                id=str(row[0].id),
                user_email=row[1],
                plan_name=row[0].plan_name,
                status=row[0].status,
                price=float(row[0].price),
                current_period_end=row[0].current_period_end,
            )
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
