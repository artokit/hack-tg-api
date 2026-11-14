from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Admin


class AdminRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_email(self, email: str) -> Admin | None:
        return await self._session.scalar(select(Admin).where(Admin.email == email))

    async def get_by_id(self, admin_id: UUID) -> Admin | None:
        return await self._session.get(Admin, admin_id)
