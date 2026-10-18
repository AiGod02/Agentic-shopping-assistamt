"""Review Repository."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.models.review import Review


class ReviewRepository:
    """Operations related to listing reviews and user feedback."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_listing_reviews(
        self,
        listing_id: uuid.UUID,
        status: str = "approved",
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[Review], int]:
        """List approved reviews for a specific listing."""
        query = select(Review).where(
            Review.listing_id == listing_id,
            Review.status == status,
        ).order_by(Review.created_at.desc()).offset(offset).limit(limit)

        result = await self.db.execute(query)
        items = result.scalars().all()

        count_query = select(func.count()).select_from(Review).where(
            Review.listing_id == listing_id,
            Review.status == status,
        )
        total = await self.db.scalar(count_query) or 0

        return items, total
