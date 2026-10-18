"""Order Repository — order persistence and querying."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from merchant_server.domain.models.order import Order, OrderItem


class OrderRepository:
    """Repository for Order CRUD operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _generate_order_number() -> str:
        """Generate a unique order number: ORD-YYYYMMDD-XXXX."""
        now = datetime.now(timezone.utc)
        rand = uuid.uuid4().hex[:8].upper()
        return f"ORD-{now.strftime('%Y%m%d')}-{rand}"

    async def create(self, order: Order) -> Order:
        if not order.order_number:
            order.order_number = self._generate_order_number()
        self.session.add(order)
        await self.session.flush()
        await self.session.refresh(order, ["items"])
        return order

    async def get_by_id(self, order_id: uuid.UUID) -> Order | None:
        stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, key: str) -> Order | None:
        """Check for existing order with same idempotency key."""
        stmt = select(Order).where(Order.idempotency_key == key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_order_number(self, order_number: str) -> Order | None:
        stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.order_number == order_number)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_merchant(self, order_id: uuid.UUID, merchant_id: uuid.UUID) -> Order | None:
        """Fetch an order only if it contains items belonging to this merchant or belongs to merchant user."""
        from merchant_server.domain.models.listing import Listing
        from merchant_server.domain.models.merchant import Merchant

        merchant_order_ids = (
            select(OrderItem.order_id)
            .join(Listing, OrderItem.listing_id == Listing.id)
            .where(Listing.merchant_id == merchant_id)
            .where(OrderItem.order_id == order_id)
        )
        merchant_user_id = select(Merchant.user_id).where(Merchant.id == merchant_id)

        stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(
                and_(
                    Order.id == order_id,
                    or_(
                        Order.id.in_(merchant_order_ids),
                        Order.user_id.in_(merchant_user_id),
                    ),
                )
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_user_orders(
        self, user_id: uuid.UUID, status: str | None = None, offset: int = 0, limit: int = 20
    ) -> tuple[list[Order], int]:
        conditions = [Order.user_id == user_id]
        if status:
            conditions.append(Order.status == status)

        where = and_(*conditions)
        count_stmt = select(func.count()).select_from(Order).where(where)
        total = (await self.session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(where)
            .order_by(Order.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_merchant_orders(
        self, merchant_id: uuid.UUID, status: str | None = None, offset: int = 0, limit: int = 20
    ) -> tuple[list[Order], int]:
        """List orders containing items from this merchant's listings."""
        from merchant_server.domain.models.listing import Listing

        # Subquery: order IDs that have items belonging to this merchant
        merchant_order_ids = (
            select(OrderItem.order_id)
            .join(Listing, OrderItem.listing_id == Listing.id)
            .where(Listing.merchant_id == merchant_id)
            .distinct()
            .subquery()
        )

        conditions = [Order.id.in_(select(merchant_order_ids.c.order_id))]
        if status:
            conditions.append(Order.status == status)

        where = and_(*conditions)
        count_stmt = select(func.count()).select_from(Order).where(where)
        total = (await self.session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(where)
            .order_by(Order.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_all_orders(
        self, status: str | None = None, offset: int = 0, limit: int = 20
    ) -> tuple[list[Order], int]:
        """Admin: list all orders."""
        conditions = []
        if status:
            conditions.append(Order.status == status)

        where = and_(*conditions) if conditions else True
        count_stmt = select(func.count()).select_from(Order).where(where)
        total = (await self.session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(where)
            .order_by(Order.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def update_status(self, order_id: uuid.UUID, status: str) -> bool:
        stmt = update(Order).where(Order.id == order_id).values(status=status)
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def update_saga_state(self, order_id: uuid.UUID, saga_state: str) -> bool:
        stmt = update(Order).where(Order.id == order_id).values(saga_state=saga_state)
        result = await self.session.execute(stmt)
        return result.rowcount > 0
