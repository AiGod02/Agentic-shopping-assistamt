"""Listing Repository — async data access for listings and variants."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from merchant_server.domain.models.listing import Listing
from merchant_server.domain.models.variant import Variant


class ListingRepository:
    """Repository for Listing CRUD operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, listing: Listing) -> Listing:
        self.session.add(listing)
        await self.session.flush()
        await self.session.refresh(listing, ["variants", "merchant"])
        return listing

    async def get_by_id(self, listing_id: uuid.UUID) -> Listing | None:
        stmt = (
            select(Listing)
            .options(selectinload(Listing.variants), selectinload(Listing.merchant))
            .where(and_(Listing.id == listing_id, Listing.deleted_at.is_(None)))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_listings(
        self,
        merchant_id: uuid.UUID | None = None,
        listing_type: str | None = None,
        status: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        search_query: str | None = None,
        tags: list[str] | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Listing], int]:
        """List listings with filters and pagination."""
        conditions = [Listing.deleted_at.is_(None)]

        if merchant_id:
            conditions.append(Listing.merchant_id == merchant_id)
        if listing_type:
            conditions.append(Listing.type == listing_type)
        if status:
            conditions.append(Listing.status == status)
        if min_price is not None:
            conditions.append(Listing.base_price >= min_price)
        if max_price is not None:
            conditions.append(Listing.base_price <= max_price)
        if search_query:
            from sqlalchemy import or_
            term = f"%{search_query}%"
            conditions.append(
                or_(
                    Listing.search_vector.op("@@")(func.plainto_tsquery("english", search_query)),
                    Listing.title.ilike(term),
                    Listing.description.ilike(term),
                )
            )
        if tags:
            conditions.append(Listing.tags.overlap(tags))

        where_clause = and_(*conditions)

        # Count total
        count_stmt = select(func.count()).select_from(Listing).where(where_clause)
        total = (await self.session.execute(count_stmt)).scalar() or 0

        # Fetch items
        stmt = (
            select(Listing)
            .options(selectinload(Listing.variants), selectinload(Listing.merchant))
            .where(where_clause)
            .order_by(Listing.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def update(self, listing_id: uuid.UUID, **kwargs: Any) -> Listing | None:
        listing = await self.get_by_id(listing_id)
        if listing is None:
            return None
        for key, value in kwargs.items():
            if hasattr(listing, key):
                setattr(listing, key, value)
        await self.session.flush()
        await self.session.refresh(listing)
        return listing

    async def soft_delete(self, listing_id: uuid.UUID) -> bool:
        from datetime import datetime, timezone
        stmt = (
            update(Listing)
            .where(Listing.id == listing_id)
            .values(deleted_at=datetime.now(timezone.utc), status="archived")
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def update_rating(self, listing_id: uuid.UUID, avg: float, count: int) -> None:
        stmt = (
            update(Listing)
            .where(Listing.id == listing_id)
            .values(rating_avg=avg, rating_count=count)
        )
        await self.session.execute(stmt)
