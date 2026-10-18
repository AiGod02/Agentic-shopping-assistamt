"""
Cart Service — concurrency-safe cart operations with business validation.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.models.cart import Cart, CartItem
from merchant_server.domain.models.listing import Listing
from merchant_server.domain.models.variant import Variant
from merchant_server.domain.repositories.cart_repo import CartRepository
from merchant_server.domain.repositories.listing_repo import ListingRepository
from shared.observability.logging import get_logger
from shared.observability.metrics import cart_operations_total

logger = get_logger(__name__)


class CartServiceError(Exception):
    """Base exception for cart operations."""
    pass


class CartService:
    """Business logic for cart operations — validates inventory, availability, and pricing."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.cart_repo = CartRepository(session)
        self.listing_repo = ListingRepository(session)

    async def get_cart(self, user_id: uuid.UUID) -> Cart | None:
        """Get user's active cart."""
        return await self.cart_repo.get_active_cart(user_id)

    async def add_to_cart(
        self,
        user_id: uuid.UUID,
        listing_id: uuid.UUID,
        variant_id: uuid.UUID | None = None,
        quantity: int = 1,
        check_in: Any = None,
        check_out: Any = None,
        time_slot_start: Any = None,
        time_slot_end: Any = None,
        guests: int | None = None,
        metadata: dict | None = None,
    ) -> Cart:
        """Add item to cart with full validation."""
        # Validate listing exists and is active
        listing = await self.listing_repo.get_by_id(listing_id)
        if listing is None:
            raise CartServiceError("Listing not found")
        if listing.status != "active":
            raise CartServiceError("Listing is not available")

        # Resolve price
        unit_price = float(listing.base_price)
        if variant_id:
            variant = next(
                (v for v in listing.variants if str(v.id) == str(variant_id)),
                None,
            )
            if variant is None:
                raise CartServiceError("Variant not found")
            if not variant.is_active:
                raise CartServiceError("Variant is not available")
            if variant.price_override is not None:
                unit_price = float(variant.price_override)
            # Inventory check for products
            if listing.type in ("product", "electronics"):
                if variant.inventory_count < quantity:
                    raise CartServiceError(
                        f"Insufficient inventory. Available: {variant.inventory_count}"
                    )

        # Get or create cart (with locking)
        cart = await self.cart_repo.get_or_create_active_cart(user_id)

        # Ensure all items in the cart belong to the same merchant to prevent cross-merchant checkout payout errors
        if cart.items:
            first_item_listing = await self.listing_repo.get_by_id(cart.items[0].listing_id)
            if first_item_listing and str(first_item_listing.merchant_id) != str(listing.merchant_id):
                raise CartServiceError(
                    "Your cart contains items from another merchant. "
                    "Please checkout or clear your cart before adding items from this merchant."
                )

        # Create cart item
        item = CartItem(
            cart_id=cart.id,
            listing_id=listing_id,
            variant_id=variant_id,
            item_type=listing.type,
            quantity=quantity,
            unit_price=unit_price,
            check_in=check_in,
            check_out=check_out,
            time_slot_start=time_slot_start,
            time_slot_end=time_slot_end,
            guests=guests,
            metadata_=metadata or {},
        )

        await self.cart_repo.add_item(cart, item)
        cart_operations_total.labels(operation="add", service="merchant-server").inc()

        logger.info(
            "cart_item_added",
            user_id=str(user_id),
            listing_id=str(listing_id),
            item_type=listing.type,
            quantity=quantity,
        )

        # Refresh cart with all items
        return await self.cart_repo.get_or_create_active_cart(user_id)

    async def remove_from_cart(
        self, user_id: uuid.UUID, item_id: uuid.UUID
    ) -> Cart:
        """Remove an item from cart."""
        cart = await self.cart_repo.get_active_cart(user_id)
        if cart is None:
            raise CartServiceError("No active cart found")

        removed = await self.cart_repo.remove_item(cart.id, item_id)
        if not removed:
            raise CartServiceError("Cart item not found")

        cart_operations_total.labels(operation="remove", service="merchant-server").inc()
        return await self.cart_repo.get_or_create_active_cart(user_id)

    async def update_quantity(
        self, user_id: uuid.UUID, item_id: uuid.UUID, quantity: int
    ) -> Cart:
        """Update item quantity in cart."""
        if quantity < 1:
            raise CartServiceError("Quantity must be at least 1")

        cart = await self.cart_repo.get_active_cart(user_id)
        if cart is None:
            raise CartServiceError("No active cart found")

        item = await self.cart_repo.update_item_quantity(cart.id, item_id, quantity)
        if item is None:
            raise CartServiceError("Cart item not found")

        cart_operations_total.labels(operation="update_qty", service="merchant-server").inc()
        return await self.cart_repo.get_or_create_active_cart(user_id)

    async def clear_cart(self, user_id: uuid.UUID) -> None:
        """Clear all items from cart."""
        cart = await self.cart_repo.get_active_cart(user_id)
        if cart:
            await self.cart_repo.clear_cart(cart.id)
            cart_operations_total.labels(operation="clear", service="merchant-server").inc()
