"""
Availability API — query and manage availability blocks.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.services.availability_service import AvailabilityService
from shared.auth.rbac import require_permission
from shared.db.session import get_db
from shared.schemas.base import BaseSchema

router = APIRouter()


class AvailabilityBlockResponse(BaseSchema):
    id: str
    listing_id: str
    variant_id: str | None
    start_date: str
    end_date: str
    capacity: int
    booked_count: int
    remaining: int
    price_override: float | None
    status: str


class CreateAvailabilityRequest(BaseModel):
    listing_id: str
    variant_id: str | None = None
    start_date: str
    end_date: str
    capacity: int = 1
    price_override: float | None = None
    start_time: str | None = None
    end_time: str | None = None


@router.get("/listing/{listing_id}", response_model=list[AvailabilityBlockResponse])
async def get_listing_availability(
    listing_id: uuid.UUID,
    from_date: str | None = None,
    to_date: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    service = AvailabilityService(db)
    blocks = await service.get_listing_availability(
        listing_id,
        dt.date.fromisoformat(from_date) if from_date else None,
        dt.date.fromisoformat(to_date) if to_date else None,
    )
    return [
        AvailabilityBlockResponse(
            id=str(b.id), listing_id=str(b.listing_id),
            variant_id=str(b.variant_id) if b.variant_id else None,
            start_date=str(b.start_date), end_date=str(b.end_date),
            capacity=b.capacity, booked_count=b.booked_count,
            remaining=b.remaining_capacity,
            price_override=float(b.price_override) if b.price_override else None,
            status=b.status,
        )
        for b in blocks
    ]


@router.post(
    "",
    response_model=AvailabilityBlockResponse,
    dependencies=[Depends(require_permission("listings:write"))],
)
async def create_availability_block(
    body: CreateAvailabilityRequest,
    db: AsyncSession = Depends(get_db),
):
    service = AvailabilityService(db)
    block = await service.create_availability_block(
        listing_id=uuid.UUID(body.listing_id),
        start_date=dt.date.fromisoformat(body.start_date),
        end_date=dt.date.fromisoformat(body.end_date),
        capacity=body.capacity,
        price_override=body.price_override,
        variant_id=uuid.UUID(body.variant_id) if body.variant_id else None,
    )
    return AvailabilityBlockResponse(
        id=str(block.id), listing_id=str(block.listing_id),
        variant_id=str(block.variant_id) if block.variant_id else None,
        start_date=str(block.start_date), end_date=str(block.end_date),
        capacity=block.capacity, booked_count=block.booked_count,
        remaining=block.remaining_capacity,
        price_override=float(block.price_override) if block.price_override else None,
        status=block.status,
    )
