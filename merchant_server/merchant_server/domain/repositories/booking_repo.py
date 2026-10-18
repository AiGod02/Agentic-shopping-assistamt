"""Booking Repository."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.models.booking import Booking


class BookingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, booking: Booking) -> Booking:
        self.session.add(booking)
        await self.session.flush()
        await self.session.refresh(booking)
        return booking

    async def get_by_id(self, booking_id: uuid.UUID) -> Booking | None:
        stmt = select(Booking).where(Booking.id == booking_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_user_bookings(
        self,
        user_id: uuid.UUID,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Booking], int]:
        conditions = [Booking.user_id == user_id]
        if status:
            conditions.append(Booking.status == status)
        where = and_(*conditions)

        total = (await self.session.execute(
            select(func.count()).select_from(Booking).where(where)
        )).scalar() or 0

        stmt = (
            select(Booking)
            .where(where)
            .order_by(Booking.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def update_status(self, booking_id: uuid.UUID, status: str) -> bool:
        values: dict = {"status": status}
        if status == "confirmed":
            values["confirmed_at"] = dt.datetime.now(dt.timezone.utc)
        elif status == "cancelled":
            values["cancelled_at"] = dt.datetime.now(dt.timezone.utc)
        stmt = update(Booking).where(Booking.id == booking_id).values(**values)
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def check_conflicts(
        self,
        listing_id: uuid.UUID,
        check_in: dt.date,
        check_out: dt.date,
        variant_id: uuid.UUID | None = None,
    ) -> list[Booking]:
        """Check for conflicting bookings in the date range."""
        conditions = [
            Booking.listing_id == listing_id,
            Booking.status.in_(["pending", "confirmed"]),
            Booking.check_in < check_out,
            Booking.check_out > check_in,
        ]
        if variant_id:
            conditions.append(Booking.variant_id == variant_id)

        stmt = select(Booking).where(and_(*conditions))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
