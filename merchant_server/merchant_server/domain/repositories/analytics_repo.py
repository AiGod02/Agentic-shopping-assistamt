"""Analytics Repository — aggregated queries for merchant dashboards.

All queries are scoped to a specific merchant_id for tenant isolation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.models.listing import Listing
from merchant_server.domain.models.order import Order, OrderItem
from merchant_server.domain.models.page_views import PageView


class AnalyticsRepository:
    """Repository for analytics data — all queries scoped by merchant_id."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _merchant_order_ids_subquery(self, merchant_id: uuid.UUID):
        """Subquery: order IDs that contain items from this merchant's listings."""
        return (
            select(OrderItem.order_id)
            .join(Listing, OrderItem.listing_id == Listing.id)
            .where(Listing.merchant_id == merchant_id)
            .distinct()
            .subquery()
        )

    async def get_dashboard_summary(
        self,
        merchant_id: uuid.UUID,
        period_days: int = 30,
    ) -> dict:
        """Get a summary of key metrics for the merchant dashboard."""
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=period_days)
        prev_period_start = period_start - timedelta(days=period_days)

        merchant_orders = self._merchant_order_ids_subquery(merchant_id)

        # Current period metrics
        current_stmt = select(
            func.count(Order.id).label("order_count"),
            func.coalesce(func.sum(Order.total_amount), 0).label("total_revenue"),
            func.coalesce(func.avg(Order.total_amount), 0).label("avg_order_value"),
        ).where(
            and_(
                Order.id.in_(select(merchant_orders.c.order_id)),
                Order.created_at >= period_start,
                Order.status != "cancelled",
            )
        )
        current = (await self.session.execute(current_stmt)).one()

        # Previous period metrics (for comparison)
        prev_stmt = select(
            func.count(Order.id).label("order_count"),
            func.coalesce(func.sum(Order.total_amount), 0).label("total_revenue"),
        ).where(
            and_(
                Order.id.in_(select(merchant_orders.c.order_id)),
                Order.created_at >= prev_period_start,
                Order.created_at < period_start,
                Order.status != "cancelled",
            )
        )
        prev = (await self.session.execute(prev_stmt)).one()

        # Active listings count
        listings_stmt = select(func.count(Listing.id)).where(
            and_(
                Listing.merchant_id == merchant_id,
                Listing.deleted_at.is_(None),
                Listing.status == "active",
            )
        )
        active_listings = (await self.session.execute(listings_stmt)).scalar() or 0

        # Page views (current period)
        views_stmt = select(func.count(PageView.id)).where(
            and_(
                PageView.merchant_id == merchant_id,
                PageView.created_at >= period_start,
            )
        )
        page_views = (await self.session.execute(views_stmt)).scalar() or 0

        # Page views (previous period)
        prev_views_stmt = select(func.count(PageView.id)).where(
            and_(
                PageView.merchant_id == merchant_id,
                PageView.created_at >= prev_period_start,
                PageView.created_at < period_start,
            )
        )
        prev_page_views = (await self.session.execute(prev_views_stmt)).scalar() or 0

        # Unique visitors (current period)
        unique_visitors_stmt = select(
            func.count(func.distinct(PageView.visitor_id))
        ).where(
            and_(
                PageView.merchant_id == merchant_id,
                PageView.created_at >= period_start,
            )
        )
        unique_visitors = (await self.session.execute(unique_visitors_stmt)).scalar() or 0

        def _pct_change(current_val, prev_val):
            if prev_val == 0:
                return 100.0 if current_val > 0 else 0.0
            return round(((current_val - prev_val) / prev_val) * 100, 1)

        return {
            "period_days": period_days,
            "orders": {
                "count": current.order_count,
                "change_pct": _pct_change(current.order_count, prev.order_count),
            },
            "revenue": {
                "total": float(current.total_revenue),
                "change_pct": _pct_change(float(current.total_revenue), float(prev.total_revenue)),
                "currency": "USD",
            },
            "avg_order_value": float(current.avg_order_value),
            "active_listings": active_listings,
            "traffic": {
                "page_views": page_views,
                "change_pct": _pct_change(page_views, prev_page_views),
                "unique_visitors": unique_visitors,
            },
        }

    async def get_sales_timeseries(
        self,
        merchant_id: uuid.UUID,
        days: int = 30,
        granularity: str = "day",
    ) -> list[dict]:
        """Get sales data as a time series for charting."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)

        merchant_orders = self._merchant_order_ids_subquery(merchant_id)

        if granularity == "day":
            date_trunc = func.date_trunc("day", Order.created_at)
        elif granularity == "week":
            date_trunc = func.date_trunc("week", Order.created_at)
        else:
            date_trunc = func.date_trunc("month", Order.created_at)

        stmt = (
            select(
                date_trunc.label("period"),
                func.count(Order.id).label("order_count"),
                func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
            )
            .where(
                and_(
                    Order.id.in_(select(merchant_orders.c.order_id)),
                    Order.created_at >= start,
                    Order.status != "cancelled",
                )
            )
            .group_by(date_trunc)
            .order_by(date_trunc)
        )

        result = await self.session.execute(stmt)
        return [
            {
                "period": row.period.isoformat() if row.period else None,
                "order_count": row.order_count,
                "revenue": float(row.revenue),
            }
            for row in result.all()
        ]

    async def get_traffic_timeseries(
        self,
        merchant_id: uuid.UUID,
        days: int = 30,
    ) -> list[dict]:
        """Get page view data as a daily time series."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)

        date_trunc = func.date_trunc("day", PageView.created_at)

        stmt = (
            select(
                date_trunc.label("period"),
                func.count(PageView.id).label("views"),
                func.count(func.distinct(PageView.visitor_id)).label("unique_visitors"),
            )
            .where(
                and_(
                    PageView.merchant_id == merchant_id,
                    PageView.created_at >= start,
                )
            )
            .group_by(date_trunc)
            .order_by(date_trunc)
        )

        result = await self.session.execute(stmt)
        return [
            {
                "period": row.period.isoformat() if row.period else None,
                "views": row.views,
                "unique_visitors": row.unique_visitors,
            }
            for row in result.all()
        ]

    async def get_top_products(
        self,
        merchant_id: uuid.UUID,
        limit: int = 10,
        days: int = 30,
    ) -> list[dict]:
        """Get top-selling products by revenue for the merchant."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)

        stmt = (
            select(
                Listing.id,
                Listing.title,
                Listing.type,
                Listing.base_price,
                func.sum(OrderItem.quantity).label("total_sold"),
                func.sum(OrderItem.total_price).label("total_revenue"),
                func.count(func.distinct(OrderItem.order_id)).label("order_count"),
            )
            .join(OrderItem, OrderItem.listing_id == Listing.id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                and_(
                    Listing.merchant_id == merchant_id,
                    Order.created_at >= start,
                    Order.status != "cancelled",
                )
            )
            .group_by(Listing.id, Listing.title, Listing.type, Listing.base_price)
            .order_by(func.sum(OrderItem.total_price).desc())
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        return [
            {
                "listing_id": str(row.id),
                "title": row.title,
                "type": row.type,
                "base_price": float(row.base_price),
                "total_sold": row.total_sold,
                "total_revenue": float(row.total_revenue),
                "order_count": row.order_count,
            }
            for row in result.all()
        ]

    async def get_orders_by_status(self, merchant_id: uuid.UUID, days: int = 30) -> dict:
        """Get order count breakdown by status."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)

        merchant_orders = self._merchant_order_ids_subquery(merchant_id)

        stmt = (
            select(
                Order.status,
                func.count(Order.id).label("count"),
            )
            .where(
                and_(
                    Order.id.in_(select(merchant_orders.c.order_id)),
                    Order.created_at >= start,
                )
            )
            .group_by(Order.status)
        )

        result = await self.session.execute(stmt)
        return {row.status: row.count for row in result.all()}
