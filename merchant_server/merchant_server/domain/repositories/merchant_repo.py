"""Merchant Repository."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.models.merchant import Merchant


class MerchantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, merchant: Merchant) -> Merchant:
        self.session.add(merchant)
        await self.session.flush()
        await self.session.refresh(merchant)
        return merchant

    async def get_by_id(self, merchant_id: uuid.UUID) -> Merchant | None:
        stmt = select(Merchant).where(Merchant.id == merchant_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: uuid.UUID) -> Merchant | None:
        stmt = select(Merchant).where(Merchant.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_verification(self, merchant_id: uuid.UUID, status: str) -> bool:
        merchant = await self.get_by_id(merchant_id)
        if merchant:
            merchant.verification_status = status
            await self.session.flush()
            return True
        return False
