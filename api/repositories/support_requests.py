from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SupportRequest


class SupportRequestRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, request_id: UUID) -> SupportRequest | None:
        return await self._session.get(SupportRequest, request_id)

    async def cost_summary(
        self, from_at: datetime | None, to_at: datetime | None,
    ) -> tuple[int, int, Decimal | None]:
        query = select(
            func.count(SupportRequest.id), func.count(SupportRequest.model_cost_usd),
            func.sum(SupportRequest.model_cost_usd),
        )
        if from_at is not None:
            query = query.where(SupportRequest.closed_at >= from_at)
        if to_at is not None:
            query = query.where(SupportRequest.closed_at < to_at)
        return (await self._session.execute(query)).one()._tuple()

    async def create(self, request: SupportRequest) -> SupportRequest:
        self._session.add(request)
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        await self._session.refresh(request)
        return request
