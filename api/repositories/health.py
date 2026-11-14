from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


class HealthRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def is_available(self) -> bool:
        try:
            await self._session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return False
        return True
