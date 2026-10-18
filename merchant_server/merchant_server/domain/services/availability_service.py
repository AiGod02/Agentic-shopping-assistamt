"""
Availability Service — date-range availability management for hotels, rentals, services.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.models.availability import AvailabilityBlock
from shared.observability.logging import get_logger

logger = get_logger(__name__)


class AvailabilityError(Exception):
    pass


class AvailabilityService:
    """Manage date/time-based availability for bookable items."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def check_availability(
        self,
        listing_id: uuid.UUID,
        start_date: dt.date,
        end_date: dt.date,
        variant_id: uuid.UUID | None = None,
        required_capacity: int = 1,
    ) -> list[AvailabilityBlock]:
        """Find available blocks that cover the requested date range."""
        conditions = [
            AvailabilityBlock.listing_id == listing_id,
            AvailabilityBlock.status == "available",
            AvailabilityBlock.start_date <= start_date,
            AvailabilityBlock.end_date >= end_date,
            (AvailabilityBlock.capacity - AvailabilityBlock.booked_count) >= required_capacity,
        ]
        if variant_id:
            conditions.append(AvailabilityBlock.variant_id == variant_id)

        stmt = select(AvailabilityBlock).where(and_(*conditions))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def reserve_availability(
        self,
        block_id: uuid.UUID,
        count: int = 1,
    ) -> AvailabilityBlock:
        """Reserve capacity in an availability block atomically.

        Uses atomic UPDATE with WHERE to prevent overbooking.
        """
        stmt = (
            update(AvailabilityBlock)
            .where(
                and_(
                    AvailabilityBlock.id == block_id,
                    AvailabilityBlock.status == "available",
                    (AvailabilityBlock.capacity - AvailabilityBlock.booked_count) >= count,
                )
            )
            .values(booked_count=AvailabilityBlock.booked_count + count)
            .returning(AvailabilityBlock.id, AvailabilityBlock.booked_count, AvailabilityBlock.capacity)
        )
        result = await self.session.execute(stmt)
        row = result.fetchone()

        if row is None:
            raise AvailabilityError(
                f"Availability block {block_id} cannot accommodate {count} guests/units"
            )

        logger.info(
            "availability_reserved",
            block_id=str(block_id),
            count=count,
            booked=row[1],
            capacity=row[2],
        )

        block = await self.session.get(AvailabilityBlock, block_id)
        return block

    async def release_availability(
        self, block_id: uuid.UUID, count: int = 1
    ) -> None:
        """Release previously reserved availability (compensation action)."""
        stmt = (
            update(AvailabilityBlock)
            .where(AvailabilityBlock.id == block_id)
            .values(booked_count=AvailabilityBlock.booked_count - count)
        )
        await self.session.execute(stmt)
        logger.info("availability_released", block_id=str(block_id), count=count)

    async def create_availability_block(
        self,
        listing_id: uuid.UUID,
        start_date: dt.date,
        end_date: dt.date,
        capacity: int = 1,
        price_override: float | None = None,
        variant_id: uuid.UUID | None = None,
        start_time: dt.time | None = None,
        end_time: dt.time | None = None,
        metadata: dict | None = None,
    ) -> AvailabilityBlock:
        """Create a new availability block."""
        block = AvailabilityBlock(
            listing_id=listing_id,
            variant_id=variant_id,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            capacity=capacity,
            price_override=price_override,
            metadata_=metadata or {},
        )
        self.session.add(block)
        await self.session.flush()
        await self.session.refresh(block)
        return block

    async def get_listing_availability(
        self,
        listing_id: uuid.UUID,
        from_date: dt.date | None = None,
        to_date: dt.date | None = None,
    ) -> list[AvailabilityBlock]:
        """Get all availability blocks for a listing within a date range."""
        conditions = [
            AvailabilityBlock.listing_id == listing_id,
            AvailabilityBlock.status == "available",
        ]
        if from_date:
            conditions.append(AvailabilityBlock.end_date >= from_date)
        if to_date:
            conditions.append(AvailabilityBlock.start_date <= to_date)

        stmt = select(AvailabilityBlock).where(and_(*conditions)).order_by(AvailabilityBlock.start_date)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
