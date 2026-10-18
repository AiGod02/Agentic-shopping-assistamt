"""Bookings API — list and manage bookings."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.repositories.booking_repo import BookingRepository
from shared.auth.rbac import get_current_user, require_permission
from shared.db.session import get_db
from shared.schemas.base import BaseSchema, PaginatedResponse

router = APIRouter()


class BookingResponse(BaseSchema):
    id: str
    order_id: str | None
    listing_id: str
    booking_type: str
    status: str
    check_in: str | None
    check_out: str | None
    guests: int
    total_price: float
    currency: str
    created_at: str


@router.get("", response_model=PaginatedResponse[BookingResponse], dependencies=[Depends(require_permission("bookings:read"))])
async def list_bookings(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = BookingRepository(db)
    items, total = await repo.list_user_bookings(
        uuid.UUID(user.sub), status, (page - 1) * page_size, page_size
    )
    return PaginatedResponse.create(
        items=[
            BookingResponse(
                id=str(b.id), order_id=str(b.order_id) if b.order_id else None,
                listing_id=str(b.listing_id), booking_type=b.booking_type,
                status=b.status,
                check_in=str(b.check_in) if b.check_in else None,
                check_out=str(b.check_out) if b.check_out else None,
                guests=b.guests, total_price=float(b.total_price),
                currency=b.currency, created_at=b.created_at.isoformat(),
            )
            for b in items
        ],
        total=total, page=page, page_size=page_size,
    )


@router.post("/{booking_id}/cancel", dependencies=[Depends(require_permission("bookings:cancel"))])
async def cancel_booking(booking_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    repo = BookingRepository(db)
    updated = await repo.update_status(booking_id, "cancelled")
    if not updated:
        raise HTTPException(status_code=404, detail="Booking not found")
    return {"status": "cancelled", "booking_id": str(booking_id)}
