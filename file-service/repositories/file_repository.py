from typing import Optional
from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from db.db import async_session_maker
from models.file import File


class FileRepository:
    async def add_file(self, file_name: str, file_id: UUID, extension: str | None):
        async with async_session_maker() as session:
            await session.execute(insert(File).values(
                id=file_id,
                name=file_name,
                extension=extension
            ))
            await session.commit()

    async def get_file_by_id(self, file_id: UUID) -> Optional[File]:
        async with async_session_maker() as session:
            file = await session.execute(select(File).where(
                File.id == file_id
            ))
            await session.commit()
        res = file.one_or_none()

        return res[0] if res else None

    async def reserve_visual(self, file_id: UUID) -> bool:
        async with async_session_maker.begin() as session:
            await session.execute(pg_insert(File).values(
                id=file_id, name="screenshot.png", extension="png",
            ).on_conflict_do_nothing(index_elements=[File.id]))
            file = await session.get(File, file_id)
            return bool(file and file.name == "screenshot.png" and file.extension == "png")

    async def delete_file(self, file_id: UUID) -> None:
        async with async_session_maker.begin() as session:
            await session.execute(delete(File).where(File.id == file_id))
