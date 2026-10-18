"""
Cart API — add/remove/view cart items, checkout.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.services.cart_service import CartService, CartServiceError
from merchant_server.sagas.checkout_saga import CheckoutSaga
from shared.auth.rbac import get_optional_user
from shared.db.session import get_db
from shared.schemas.base import BaseSchema

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────

class AddToCartRequest(BaseModel):
    listing_id: str
    variant_id: str | None = None
    quantity: int = 1
    check_in: str | None = None  # ISO date
    check_out: str | None = None
    time_slot_start: str | None = None
    time_slot_end: str | None = None
    guests: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateQuantityRequest(BaseModel):
    quantity: int = Field(..., ge=1)


class CheckoutRequest(BaseModel):
    idempotency_key: str
    payment_gateway: str = "stripe"
    shipping_address: dict[str, Any] | None = None
    billing_address: dict[str, Any] | None = None
    pay_platform: bool = False


class CartItemResponse(BaseSchema):
    id: str
    listing_id: str
    variant_id: str | None
    item_type: str
    quantity: int
    unit_price: float
    line_total: float
    check_in: str | None
    check_out: str | None
    guests: int | None


class CartResponse(BaseSchema):
    id: str
    status: str
    items: list[CartItemResponse]
    subtotal: float
    item_count: int


def _cart_to_response(cart) -> CartResponse:
    return CartResponse(
        id=str(cart.id),
        status=cart.status,
        items=[
            CartItemResponse(
                id=str(i.id),
                listing_id=str(i.listing_id),
                variant_id=str(i.variant_id) if i.variant_id else None,
                item_type=i.item_type,
                quantity=i.quantity,
                unit_price=float(i.unit_price),
                line_total=i.line_total,
                check_in=str(i.check_in) if i.check_in else None,
                check_out=str(i.check_out) if i.check_out else None,
                guests=i.guests,
            )
            for i in cart.items
        ],
        subtotal=cart.subtotal,
        item_count=cart.item_count,
    )


# ── Endpoints ─────────────────────────────────────────────────────

def _parse_uuid(val: str | uuid.UUID | None) -> uuid.UUID:
    if isinstance(val, uuid.UUID):
        return val
    if not val:
        return uuid.uuid4()
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError):
        return uuid.uuid5(uuid.NAMESPACE_DNS, str(val))


def _resolve_user_id(request: Request, user: Any = None) -> uuid.UUID | None:
    if user and getattr(user, "sub", None):
        return _parse_uuid(user.sub)
    guest_header = (
        request.headers.get("X-Session-ID")
        or request.headers.get("X-Guest-ID")
        or request.cookies.get("cart_session_id")
        or request.cookies.get("acp_session_id")
    )
    if guest_header:
        return _parse_uuid(guest_header)
    return None


@router.get("", response_model=CartResponse)
async def view_cart(
    request: Request,
    user=Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's active cart (supports logged-in or guest users)."""
    user_id = _resolve_user_id(request, user)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required for cart operations",
        )
    service = CartService(db)
    cart = await service.get_cart(user_id)
    if cart is None:
        return CartResponse(id="", status="empty", items=[], subtotal=0, item_count=0)
    return _cart_to_response(cart)


@router.post("/items", response_model=CartResponse)
async def add_to_cart(
    request: Request,
    body: AddToCartRequest,
    user=Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Add an item to the cart (supports logged-in or guest users)."""
    from datetime import date
    user_id = _resolve_user_id(request, user)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required for cart operations",
        )
    service = CartService(db)
    try:
        cart = await service.add_to_cart(
            user_id=user_id,
            listing_id=_parse_uuid(body.listing_id),
            variant_id=_parse_uuid(body.variant_id) if body.variant_id else None,
            quantity=body.quantity,
            check_in=date.fromisoformat(body.check_in) if body.check_in else None,
            check_out=date.fromisoformat(body.check_out) if body.check_out else None,
            guests=body.guests,
            metadata=body.metadata,
        )
        return _cart_to_response(cart)
    except CartServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/items/{item_id}",
    response_model=CartResponse,
)
async def remove_from_cart(
    item_id: str,
    request: Request,
    user=Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove an item from the cart."""
    user_id = _resolve_user_id(request, user)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required for cart operations",
        )
    service = CartService(db)
    try:
        cart = await service.remove_from_cart(user_id, _parse_uuid(item_id))
        return _cart_to_response(cart)
    except CartServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch(
    "/items/{item_id}",
    response_model=CartResponse,
)
async def update_cart_item_quantity(
    item_id: str,
    body: UpdateQuantityRequest,
    request: Request,
    user=Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the quantity of a cart item."""
    user_id = _resolve_user_id(request, user)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required for cart operations",
        )
    service = CartService(db)
    try:
        cart = await service.update_quantity(user_id, _parse_uuid(item_id), body.quantity)
        return _cart_to_response(cart)
    except CartServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/checkout")
async def checkout(
    body: CheckoutRequest,
    user=Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Execute checkout — runs the full checkout saga. Only registered logged-in users can checkout."""
    if not user or not user.sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required for checkout",
        )
    user_id = _parse_uuid(user.sub)

    # Verify user is a registered user account in the database (unlogin/guest users must log in to checkout)
    from sqlalchemy import select
    from merchant_server.domain.models.user import User
    user_stmt = select(User).where(User.id == user_id)
    user_res = await db.execute(user_stmt)
    registered_user = user_res.scalar_one_or_none()
    if not registered_user or registered_user.password_hash == "guest_unauthenticated" or registered_user.email.endswith("@guest.local"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Only logged-in registered users can checkout. Please log in or register to complete your order.",
        )

    saga = CheckoutSaga(db)
    try:
        result = await saga.execute(
            user_id=user_id,
            idempotency_key=body.idempotency_key,
            payment_gateway=body.payment_gateway,
            shipping_address=body.shipping_address,
            billing_address=body.billing_address,
            pay_platform=body.pay_platform,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cart(
    request: Request,
    user=Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear all items from the cart."""
    user_id = _resolve_user_id(request, user)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required for cart operations",
        )
    service = CartService(db)
    await service.clear_cart(user_id)


class ClaimCartRequest(BaseModel):
    guest_user_id: str


@router.post("/claim", response_model=CartResponse)
async def claim_cart(
    body: ClaimCartRequest,
    request: Request,
    user=Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Claim/merge guest cart items into the current authenticated user's cart."""
    user_id = _resolve_user_id(request, user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required to claim cart")

    guest_id = _parse_uuid(body.guest_user_id)
    if guest_id == user_id:
        service = CartService(db)
        cart = await service.get_cart(user_id)
        return _cart_to_response(cart) if cart else CartResponse(id="", status="empty", items=[], subtotal=0, item_count=0)

    from merchant_server.domain.repositories.cart_repo import CartRepository
    repo = CartRepository(db)
    guest_cart = await repo.get_active_cart(guest_id)
    if not guest_cart or not guest_cart.items:
        service = CartService(db)
        cart = await service.get_cart(user_id)
        return _cart_to_response(cart) if cart else CartResponse(id="", status="empty", items=[], subtotal=0, item_count=0)

    target_cart = await repo.get_or_create_cart(user_id)
    for g_item in guest_cart.items:
        await repo.add_item(
            cart_id=target_cart.id,
            listing_id=g_item.listing_id,
            variant_id=g_item.variant_id,
            item_type=g_item.item_type,
            quantity=g_item.quantity,
            unit_price=float(g_item.unit_price),
            check_in=g_item.check_in,
            check_out=g_item.check_out,
            guests=g_item.guests,
            metadata=g_item.metadata_,
        )
    guest_cart.status = "merged"
    await db.flush()

    service = CartService(db)
    updated_cart = await service.get_cart(user_id)
    return _cart_to_response(updated_cart)
