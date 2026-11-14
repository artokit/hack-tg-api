from typing import Optional
from uuid import UUID

from sqlalchemy import insert, select
from db.db import async_session_maker
from models.file import File


class FileRepository:
    async def add_file(self, file_name: str, file_id: UUID, extension: str):
        async with async_session_maker() as session:
            await session.execute(insert(File).values(
                id=file_id,
                name=file_name,
                extension=extension
            ))
            await session.commit()

    async def get_file_by_id(self, file_id: str) -> Optional[File]:
        async with async_session_maker() as session:
            file = await session.execute(select(File).where(
                File.id == file_id
            ))
            await session.commit()
        res = file.one_or_none()

        return res[0] if res else None
