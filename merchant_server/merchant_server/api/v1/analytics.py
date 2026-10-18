"""
Analytics API — merchant dashboard data endpoints.

Security: ALL endpoints derive merchant_id from the JWT token.
No merchant identity is accepted from URL parameters.
A merchant can ONLY see their own analytics data.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.repositories.analytics_repo import AnalyticsRepository
from shared.auth.rbac import Role, get_current_user, require_role
from shared.db.session import get_db

router = APIRouter()


def _get_merchant_id(user) -> uuid.UUID:
    """Extract and validate merchant_id from JWT token."""
    if not user.merchant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No merchant profile associated with this account",
        )
    return uuid.UUID(user.merchant_id)


@router.get(
    "/dashboard",
    dependencies=[Depends(require_role(Role.MERCHANT, Role.ADMIN))],
)
async def get_dashboard_summary(
    period: int = Query(30, ge=1, le=365, description="Period in days"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full dashboard summary: orders, revenue, traffic, listings.

    merchant_id is extracted from JWT — not from URL.
    """
    merchant_id = _get_merchant_id(user)
    repo = AnalyticsRepository(db)

    summary = await repo.get_dashboard_summary(merchant_id, period)
    status_breakdown = await repo.get_orders_by_status(merchant_id, period)

    return {
        **summary,
        "order_status_breakdown": status_breakdown,
    }


@router.get(
    "/sales",
    dependencies=[Depends(require_role(Role.MERCHANT, Role.ADMIN))],
)
async def get_sales_data(
    days: int = Query(30, ge=1, le=365),
    granularity: str = Query("day", pattern="^(day|week|month)$"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sales time series data for charting.

    Returns daily/weekly/monthly revenue and order counts.
    """
    merchant_id = _get_merchant_id(user)
    repo = AnalyticsRepository(db)

    data = await repo.get_sales_timeseries(merchant_id, days, granularity)
    return {"granularity": granularity, "days": days, "data": data}


@router.get(
    "/traffic",
    dependencies=[Depends(require_role(Role.MERCHANT, Role.ADMIN))],
)
async def get_traffic_data(
    days: int = Query(30, ge=1, le=365),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Page view and visitor traffic data for charting."""
    merchant_id = _get_merchant_id(user)
    repo = AnalyticsRepository(db)

    data = await repo.get_traffic_timeseries(merchant_id, days)
    return {"days": days, "data": data}


@router.get(
    "/top-products",
    dependencies=[Depends(require_role(Role.MERCHANT, Role.ADMIN))],
)
async def get_top_products(
    limit: int = Query(10, ge=1, le=50),
    days: int = Query(30, ge=1, le=365),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Top-selling products by revenue."""
    merchant_id = _get_merchant_id(user)
    repo = AnalyticsRepository(db)

    data = await repo.get_top_products(merchant_id, limit, days)
    return {"days": days, "data": data}
