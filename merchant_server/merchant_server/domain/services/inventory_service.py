"""
Inventory Service — atomic inventory management with optimistic locking.
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.models.variant import Variant
from shared.events.kafka_producer import save_outbox_event
from shared.observability.logging import get_logger

logger = get_logger(__name__)


class InsufficientInventoryError(Exception):
    def __init__(self, variant_id: str, requested: int, available: int) -> None:
        self.variant_id = variant_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient inventory for variant {variant_id}: requested={requested}, available={available}"
        )


class InventoryService:
    """Atomic inventory operations using optimistic locking (version check on inventory_count)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reserve_inventory(
        self, variant_id: uuid.UUID, quantity: int
    ) -> int:
        """Reserve inventory atomically. Returns new count.

        Uses atomic UPDATE with WHERE clause to prevent races:
        UPDATE variants SET inventory_count = inventory_count - :qty
        WHERE id = :id AND inventory_count >= :qty
        """
        stmt = (
            update(Variant)
            .where(
                and_(
                    Variant.id == variant_id,
                    Variant.inventory_count >= quantity,
                )
            )
            .values(inventory_count=Variant.inventory_count - quantity)
            .returning(Variant.inventory_count)
        )
        result = await self.session.execute(stmt)
        row = result.fetchone()

        if row is None:
            # Get current count for error message
            from sqlalchemy import select
            variant = await self.session.get(Variant, variant_id)
            available = variant.inventory_count if variant else 0
            raise InsufficientInventoryError(str(variant_id), quantity, available)

        new_count = row[0]
        logger.info(
            "inventory_reserved",
            variant_id=str(variant_id),
            quantity=quantity,
            new_count=new_count,
        )

        # Save event to outbox
        await save_outbox_event(
            db_session=self.session,
            topic="inventory",
            event_type="inventory.reserved",
            payload={
                "variant_id": str(variant_id),
                "quantity": quantity,
                "new_count": new_count,
            },
            source="merchant-server",
            key=str(variant_id),
        )

        return new_count

    async def release_inventory(
        self, variant_id: uuid.UUID, quantity: int
    ) -> int:
        """Release previously reserved inventory (compensation action)."""
        stmt = (
            update(Variant)
            .where(Variant.id == variant_id)
            .values(inventory_count=Variant.inventory_count + quantity)
            .returning(Variant.inventory_count)
        )
        result = await self.session.execute(stmt)
        row = result.fetchone()

        if row is None:
            logger.error("inventory_release_failed", variant_id=str(variant_id))
            raise ValueError(f"Variant {variant_id} not found for inventory release")

        new_count = row[0]
        logger.info(
            "inventory_released",
            variant_id=str(variant_id),
            quantity=quantity,
            new_count=new_count,
        )

        # Save event to outbox
        await save_outbox_event(
            db_session=self.session,
            topic="inventory",
            event_type="inventory.released",
            payload={
                "variant_id": str(variant_id),
                "quantity": quantity,
                "new_count": new_count,
            },
            source="merchant-server",
            key=str(variant_id),
        )

        return new_count

    async def check_availability(self, variant_id: uuid.UUID, quantity: int) -> bool:
        """Check if sufficient inventory exists without reserving."""
        from sqlalchemy import select
        stmt = select(Variant.inventory_count).where(Variant.id == variant_id)
        result = await self.session.execute(stmt)
        count = result.scalar()
        return count is not None and count >= quantity
