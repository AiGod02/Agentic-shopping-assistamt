"""
Checkout Saga — distributed transaction orchestrator for the checkout flow.

Steps:
1. Validate cart
2. Reserve inventory (for products) / Reserve availability (for bookings)
3. Create order
4. Create payment intent (via Payment Server)
5. On payment success → confirm order
6. On failure → compensate (release inventory, cancel order)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.config import settings
from merchant_server.domain.models.booking import Booking
from merchant_server.domain.repositories.booking_repo import BookingRepository
from merchant_server.domain.repositories.order_repo import OrderRepository
from merchant_server.domain.services.availability_service import AvailabilityService
from merchant_server.domain.services.cart_service import CartService
from merchant_server.domain.services.inventory_service import InventoryService
from merchant_server.domain.services.order_service import OrderService
from shared.middleware.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from shared.observability.logging import get_logger

logger = get_logger(__name__)

# Circuit breaker for payment service calls
payment_circuit = CircuitBreaker(
    "payment-server",
    CircuitBreakerConfig(failure_threshold=5, timeout_seconds=30),
)


class SagaStep(str, Enum):
    VALIDATE_CART = "validate_cart"
    RESERVE_INVENTORY = "reserve_inventory"
    RESERVE_AVAILABILITY = "reserve_availability"
    CREATE_ORDER = "create_order"
    CREATE_PAYMENT = "create_payment"
    CONFIRM_ORDER = "confirm_order"


@dataclass
class SagaContext:
    """Tracks the state of a checkout saga for compensation on failure."""

    user_id: uuid.UUID
    idempotency_key: str
    order_id: uuid.UUID | None = None
    payment_id: str | None = None
    reserved_variants: list[tuple[uuid.UUID, int]] = field(default_factory=list)  # (variant_id, qty)
    reserved_availability_blocks: list[tuple[uuid.UUID, int]] = field(default_factory=list)  # (block_id, count)
    booking_ids: list[uuid.UUID] = field(default_factory=list)
    completed_steps: list[SagaStep] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": str(self.user_id),
            "idempotency_key": self.idempotency_key,
            "order_id": str(self.order_id) if self.order_id else None,
            "payment_id": self.payment_id,
            "reserved_variants": [(str(vid), qty) for vid, qty in self.reserved_variants],
            "reserved_availability_blocks": [(str(bid), count) for bid, count in self.reserved_availability_blocks],
            "booking_ids": [str(bid) for bid in self.booking_ids],
            "completed_steps": [step.value for step in self.completed_steps],
            "error": self.error,
        }


class CheckoutSaga:
    """Orchestrates the distributed checkout transaction with compensating actions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.cart_service = CartService(session)
        self.order_service = OrderService(session)
        self.inventory_service = InventoryService(session)
        self.availability_service = AvailabilityService(session)
        self.order_repo = OrderRepository(session)
        self.booking_repo = BookingRepository(session)

    async def _save_saga_instance(self, ctx: SagaContext, status: str) -> None:
        from sqlalchemy import text
        import json
        
        # Check if exists
        result = await self.session.execute(
            text("SELECT id FROM saga_instances WHERE idempotency_key = :key"),
            {"key": ctx.idempotency_key}
        )
        row = result.fetchone()
        
        context_json = json.dumps(ctx.to_dict())
        
        if row:
            await self.session.execute(
                text("""
                    UPDATE saga_instances 
                    SET status = :status, context_data = :context, updated_at = NOW() 
                    WHERE idempotency_key = :key
                """),
                {"status": status, "context": context_json, "key": ctx.idempotency_key}
            )
        else:
            await self.session.execute(
                text("""
                    INSERT INTO saga_instances (user_id, idempotency_key, status, context_data)
                    VALUES (:user_id, :key, :status, :context)
                """),
                {
                    "user_id": ctx.user_id,
                    "key": ctx.idempotency_key,
                    "status": status,
                    "context": context_json,
                }
            )
        await self.session.flush()

    async def execute(
        self,
        user_id: uuid.UUID,
        idempotency_key: str,
        payment_gateway: str = "stripe",
        shipping_address: dict[str, Any] | None = None,
        billing_address: dict[str, Any] | None = None,
        pay_platform: bool = False,
    ) -> dict[str, Any]:
        """Execute the full checkout saga.

        Returns dict with order details and payment info on success.
        Raises on failure after compensating.
        """
        ctx = SagaContext(user_id=user_id, idempotency_key=idempotency_key)

        try:
            # Step 1: Validate cart
            cart = await self.cart_service.get_cart(user_id)
            if cart is None or not cart.items:
                raise ValueError("Cart is empty")
            ctx.completed_steps.append(SagaStep.VALIDATE_CART)
            await self._save_saga_instance(ctx, "validated")
            await self.order_repo.update_saga_state(
                ctx.order_id, "validated"
            ) if ctx.order_id else None

            # Step 2: Reserve inventory for product-type items
            for item in cart.items:
                if item.item_type in ("product", "electronics") and item.variant_id:
                    await self.inventory_service.reserve_inventory(
                        uuid.UUID(str(item.variant_id)), item.quantity
                    )
                    ctx.reserved_variants.append(
                        (uuid.UUID(str(item.variant_id)), item.quantity)
                    )
            ctx.completed_steps.append(SagaStep.RESERVE_INVENTORY)
            await self._save_saga_instance(ctx, "inventory_reserved")

            # Step 3: Reserve availability for booking-type items
            for item in cart.items:
                if item.item_type in ("hotel", "rental", "service") and item.check_in and item.check_out:
                    blocks = await self.availability_service.check_availability(
                        uuid.UUID(str(item.listing_id)),
                        item.check_in,
                        item.check_out,
                        uuid.UUID(str(item.variant_id)) if item.variant_id else None,
                        item.guests or 1,
                    )
                    if not blocks:
                        raise ValueError(
                            f"No availability for listing {item.listing_id} "
                            f"from {item.check_in} to {item.check_out}"
                        )
                    block = blocks[0]
                    await self.availability_service.reserve_availability(
                        block.id, item.guests or 1
                    )
                    ctx.reserved_availability_blocks.append(
                        (block.id, item.guests or 1)
                    )
            ctx.completed_steps.append(SagaStep.RESERVE_AVAILABILITY)
            await self._save_saga_instance(ctx, "availability_reserved")

            # Step 4: Create order
            order = await self.order_service.create_order_from_cart(
                user_id=user_id,
                idempotency_key=idempotency_key,
                shipping_address=shipping_address,
                billing_address=billing_address,
            )
            ctx.order_id = order.id
            await self.order_repo.update_saga_state(order.id, "inventory_reserved")
            ctx.completed_steps.append(SagaStep.CREATE_ORDER)
            await self._save_saga_instance(ctx, "order_created")
            await self.session.commit()

            # Step 5: Create bookings for booking-type items
            for item in cart.items:
                if item.item_type in ("hotel", "rental", "service"):
                    booking = Booking(
                        order_id=order.id,
                        user_id=user_id,
                        listing_id=item.listing_id,
                        variant_id=item.variant_id,
                        booking_type=item.item_type,
                        status="pending",
                        check_in=item.check_in,
                        check_out=item.check_out,
                        time_slot_start=item.time_slot_start,
                        time_slot_end=item.time_slot_end,
                        guests=item.guests or 1,
                        total_price=item.line_total,
                    )
                    booking = await self.booking_repo.create(booking)
                    ctx.booking_ids.append(booking.id)

            # Step 6: Create payment intent via Payment Server
            merchant_stripe_account = None
            merchant_razorpay_account = None
            
            if not pay_platform and order.items:
                from sqlalchemy import text
                from merchant_server.domain.models.listing import Listing
                first_item = order.items[0]
                listing = await self.session.get(Listing, first_item.listing_id)
                if listing:
                    result = await self.session.execute(
                        text("SELECT payout_account FROM merchants WHERE id = :mid"),
                        {"mid": listing.merchant_id}
                    )
                    row = result.fetchone()
                    if row and row[0]:
                        payout_data = row[0]
                        if isinstance(payout_data, dict):
                            merchant_stripe_account = payout_data.get("stripe_account_id")
                            merchant_razorpay_account = payout_data.get("razorpay_account_id")

            payment_metadata = {}
            if merchant_stripe_account:
                payment_metadata["merchant_stripe_account_id"] = merchant_stripe_account
            if merchant_razorpay_account:
                payment_metadata["merchant_razorpay_account_id"] = merchant_razorpay_account

            payment_data = await self._create_payment_intent(
                order_id=str(order.id),
                user_id=str(user_id),
                amount=float(order.total_amount),
                currency=order.currency,
                gateway=payment_gateway,
                idempotency_key=f"pay-{idempotency_key}",
                metadata=payment_metadata if payment_metadata else None,
            )
            ctx.payment_id = payment_data.get("payment_id")
            await self.order_repo.update_saga_state(order.id, "payment_pending")
            ctx.completed_steps.append(SagaStep.CREATE_PAYMENT)
            await self._save_saga_instance(ctx, "completed")

            logger.info(
                "checkout_saga_completed",
                order_id=str(order.id),
                payment_id=ctx.payment_id,
            )

            return {
                "order_id": str(order.id),
                "order_number": order.order_number,
                "total_amount": float(order.total_amount),
                "currency": order.currency,
                "payment_id": ctx.payment_id,
                "client_secret": payment_data.get("client_secret"),
                "gateway": payment_gateway,
                "status": "payment_pending",
            }

        except Exception as e:
            ctx.error = str(e)
            logger.error(
                "checkout_saga_failed",
                error=str(e),
                completed_steps=[s.value for s in ctx.completed_steps],
            )
            await self._save_saga_instance(ctx, "failed")
            await self._compensate(ctx)
            await self._save_saga_instance(ctx, "compensated")
            raise

    async def _create_payment_intent(
        self,
        order_id: str,
        user_id: str,
        amount: float,
        currency: str,
        gateway: str,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call Payment Server to create a payment intent."""
        async with httpx.AsyncClient(timeout=30.0) as client:

            @payment_circuit.protect
            async def _call():
                logger.info(
                    "payment_intent_creation_started",
                    order_id=order_id,
                    gateway=gateway,
                    payment_server_url=settings.payment_server_url,
                )
                response = await client.post(
                    f"{settings.payment_server_url}/api/v1/payments/create",
                    json={
                        "order_id": order_id,
                        "user_id": user_id,
                        "amount": amount,
                        "currency": currency,
                        "gateway": gateway,
                        "idempotency_key": idempotency_key,
                        "metadata": metadata or {},
                    },
                    headers={"X-Internal-Service": "merchant-server"},
                )
                response.raise_for_status()
                data = response.json()
                logger.info(
                    "payment_intent_creation_completed",
                    order_id=order_id,
                    gateway=gateway,
                    response=data,
                )
                return data

            return await _call()

    async def _compensate(self, ctx: SagaContext) -> None:
        """Execute compensating actions in reverse order."""
        logger.info(
            "saga_compensating",
            completed_steps=[s.value for s in ctx.completed_steps],
        )

        try:
            # Cancel bookings
            for booking_id in ctx.booking_ids:
                try:
                    await self.booking_repo.update_status(booking_id, "cancelled")
                except Exception:
                    logger.exception("compensation_booking_cancel_failed", booking_id=str(booking_id))

            # Cancel order
            if ctx.order_id:
                try:
                    await self.order_repo.update_status(ctx.order_id, "cancelled")
                    await self.order_repo.update_saga_state(ctx.order_id, "failed")
                except Exception:
                    logger.exception("compensation_order_cancel_failed", order_id=str(ctx.order_id))

            # Release availability
            for block_id, count in ctx.reserved_availability_blocks:
                try:
                    await self.availability_service.release_availability(block_id, count)
                except Exception:
                    logger.exception("compensation_availability_release_failed", block_id=str(block_id))

            # Release inventory
            for variant_id, qty in ctx.reserved_variants:
                try:
                    await self.inventory_service.release_inventory(variant_id, qty)
                except Exception:
                    logger.exception("compensation_inventory_release_failed", variant_id=str(variant_id))

        except Exception:
            logger.exception("saga_compensation_failed")
