from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SupportRequest


class SupportRequestRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, request_id: UUID) -> SupportRequest | None:
        return await self._session.get(SupportRequest, request_id)

    async def create(self, request: SupportRequest) -> SupportRequest:
        self._session.add(request)
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        await self._session.refresh(request)
        return request
