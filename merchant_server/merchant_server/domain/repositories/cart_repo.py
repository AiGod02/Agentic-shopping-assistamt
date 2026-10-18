"""Cart Repository — concurrency-safe cart operations."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from merchant_server.domain.models.cart import Cart, CartItem


class CartRepository:
    """Repository for Cart operations with concurrency safety."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_active_cart(self, user_id: uuid.UUID) -> Cart:
        """Get user's active cart or create one. Uses SELECT FOR UPDATE to prevent races."""
        from merchant_server.domain.models.user import User

        stmt = (
            select(Cart)
            .options(selectinload(Cart.items))
            .where(and_(Cart.user_id == user_id, Cart.status == "active"))
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        cart = result.scalar_one_or_none()

        if cart is None:
            user_res = await self.session.execute(select(User).where(User.id == user_id))
            if user_res.scalar_one_or_none() is None:
                guest_user = User(
                    id=user_id,
                    email=f"guest_{user_id}@guest.local",
                    password_hash="guest_unauthenticated",
                    full_name="Guest User",
                    role="customer",
                    is_active=True,
                    email_verified=False,
                )
                self.session.add(guest_user)
                await self.session.flush()

            cart = Cart(user_id=user_id, status="active")
            self.session.add(cart)
            await self.session.flush()
            await self.session.refresh(cart, ["items"])

        return cart


    async def get_active_cart(self, user_id: uuid.UUID) -> Cart | None:
        """Get user's active cart without locking."""
        stmt = (
            select(Cart)
            .options(selectinload(Cart.items))
            .where(and_(Cart.user_id == user_id, Cart.status == "active"))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_cart_by_id(self, cart_id: uuid.UUID) -> Cart | None:
        stmt = (
            select(Cart)
            .options(selectinload(Cart.items))
            .where(Cart.id == cart_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add_item(self, cart: Cart, item: CartItem) -> CartItem:
        """Add an item to cart. Merges quantity if same listing+variant exists."""
        # Check for existing item with same listing and variant
        for existing in cart.items:
            if (
                str(existing.listing_id) == str(item.listing_id)
                and str(existing.variant_id or "") == str(item.variant_id or "")
                and existing.item_type in ("product", "electronics")  # Only merge for quantity-based items
            ):
                existing.quantity += item.quantity
                await self.session.flush()
                return existing

        cart.items.append(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def remove_item(self, cart_id: uuid.UUID, item_id: uuid.UUID) -> bool:
        """Remove an item from cart."""
        stmt = select(CartItem).where(
            and_(CartItem.cart_id == cart_id, CartItem.id == item_id)
        )
        result = await self.session.execute(stmt)
        item = result.scalar_one_or_none()
        if item:
            await self.session.delete(item)
            return True
        return False

    async def update_item_quantity(
        self, cart_id: uuid.UUID, item_id: uuid.UUID, quantity: int
    ) -> CartItem | None:
        """Update item quantity. Returns None if item not found."""
        stmt = select(CartItem).where(
            and_(CartItem.cart_id == cart_id, CartItem.id == item_id)
        )
        result = await self.session.execute(stmt)
        item = result.scalar_one_or_none()
        if item:
            item.quantity = quantity
            await self.session.flush()
            return item
        return None

    async def clear_cart(self, cart_id: uuid.UUID) -> None:
        """Remove all items from a cart."""
        stmt = select(CartItem).where(CartItem.cart_id == cart_id)
        result = await self.session.execute(stmt)
        for item in result.scalars():
            await self.session.delete(item)

    async def mark_checked_out(self, cart_id: uuid.UUID) -> None:
        """Mark cart as checked out."""
        stmt = update(Cart).where(Cart.id == cart_id).values(status="checked_out")
        await self.session.execute(stmt)
