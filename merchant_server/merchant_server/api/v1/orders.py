"""
Orders API — order listing, status updates.

Security: Merchants can only view orders that contain items from their own listings.
Customers can only view their own orders. Admins can view any order.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.services.order_service import OrderService, OrderServiceError
from shared.auth.rbac import Role, get_current_user, require_permission
from shared.db.session import get_db
from shared.schemas.base import BaseSchema, PaginatedResponse

router = APIRouter()


class OrderItemResponse(BaseSchema):
    id: str
    listing_id: str
    variant_id: str | None
    item_type: str
    quantity: int
    unit_price: float
    total_price: float


class OrderResponse(BaseSchema):
    id: str
    order_number: str
    status: str
    subtotal: float
    tax_amount: float
    discount_amount: float
    total_amount: float
    currency: str
    saga_state: str
    items: list[OrderItemResponse]
    created_at: str


def _order_to_response(order) -> OrderResponse:
    return OrderResponse(
        id=str(order.id),
        order_number=order.order_number,
        status=order.status,
        subtotal=float(order.subtotal),
        tax_amount=float(order.tax_amount),
        discount_amount=float(order.discount_amount),
        total_amount=float(order.total_amount),
        currency=order.currency,
        saga_state=order.saga_state,
        items=[
            OrderItemResponse(
                id=str(i.id),
                listing_id=str(i.listing_id),
                variant_id=str(i.variant_id) if i.variant_id else None,
                item_type=i.item_type,
                quantity=i.quantity,
                unit_price=float(i.unit_price),
                total_price=float(i.total_price),
            )
            for i in (order.items or [])
        ],
        created_at=order.created_at.isoformat(),
    )


async def _verify_order_ownership(order, user_token, db: AsyncSession) -> None:
    """Verify the requesting user has access to this order.

    - Admins: full access
    - Customers: can only see their own orders (order.user_id == token.sub)
    - Merchants: can only see orders containing their listings
    """
    if user_token.role == Role.ADMIN.value:
        return

    if user_token.role == Role.CUSTOMER.value:
        if str(order.user_id) != user_token.sub:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to view this order",
            )
        return

    if user_token.role == Role.MERCHANT.value:
        if not user_token.merchant_id:
            raise HTTPException(status_code=403, detail="No merchant profile found")

        # Check if any order item belongs to this merchant's listings
        from sqlalchemy import select
        from merchant_server.domain.models.listing import Listing

        merchant_uuid = uuid.UUID(user_token.merchant_id)
        listing_ids = [i.listing_id for i in (order.items or [])]

        if not listing_ids:
            raise HTTPException(status_code=403, detail="Not authorized to view this order")

        stmt = select(Listing.id).where(
            Listing.merchant_id == merchant_uuid,
            Listing.id.in_(listing_ids),
        )
        result = await db.execute(stmt)
        matched = result.scalars().all()

        if not matched:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to view this order",
            )
        return

    # Default deny for unknown roles
    raise HTTPException(status_code=403, detail="Access denied")


@router.get("", response_model=PaginatedResponse[OrderResponse], dependencies=[Depends(require_permission("orders:read"))])
async def list_orders(
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List orders with tenant isolation.

    - Customers: see only their own orders
    - Merchants: see only orders containing items from their listings
    - Admins: see all orders
    """
    service = OrderService(db)

    if user.role == Role.ADMIN.value:
        # Admin sees all — we'll use a special method
        items, total = await service.list_all_orders(status_filter, (page - 1) * page_size, page_size)
    elif user.role == Role.MERCHANT.value:
        # Merchant sees only orders related to their listings
        if not user.merchant_id:
            raise HTTPException(status_code=404, detail="No merchant profile found")
        items, total = await service.list_merchant_orders(
            uuid.UUID(user.merchant_id), status_filter, (page - 1) * page_size, page_size
        )
    else:
        # Customer sees only their own orders
        items, total = await service.list_user_orders(
            uuid.UUID(user.sub), status_filter, (page - 1) * page_size, page_size
        )

    return PaginatedResponse.create(
        items=[_order_to_response(o) for o in items],
        total=total, page=page, page_size=page_size,
    )


@router.get("/{order_id}", response_model=OrderResponse, dependencies=[Depends(require_permission("orders:read"))])
async def get_order(
    order_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single order. Enforces ownership — merchants/customers can only view their own orders."""
    service = OrderService(db)
    order = await service.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    # Enforce ownership
    await _verify_order_ownership(order, user, db)

    return _order_to_response(order)


@router.post(
    "/{order_id}/cancel",
    response_model=dict,
    dependencies=[Depends(require_permission("orders:cancel"))],
)
async def cancel_order(
    order_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel an order. Enforces ownership."""
    service = OrderService(db)

    # Verify the order exists and user has access
    order = await service.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    await _verify_order_ownership(order, user, db)

    try:
        cancelled = await service.cancel_order(order_id)
        if not cancelled:
            raise HTTPException(status_code=404, detail="Order not found")
        return {"status": "cancelled", "order_id": str(order_id)}
    except OrderServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
