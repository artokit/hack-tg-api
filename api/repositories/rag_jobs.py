from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import case, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from db.models import RagDocument, RagJob


class RagJobs:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def enqueue(
        self, index_key: str, source_id: str, title: str, source_url: str | None, format: str, data: bytes
    ) -> UUID:
        async with self.sessions.begin() as session:
            job = RagJob(
                index_key=index_key, source_id=source_id, title=title, source_url=source_url,
                format=format, data=data,
            )
            session.add(job)
            await session.flush()
            return job.id

    async def read(self, job_id: UUID, index_key: str):
        async with self.sessions() as session:
            result = await session.execute(
                select(
                    RagJob.id, RagJob.source_id, RagJob.status, RagJob.error_code,
                    RagJob.version, RagJob.chunk_count, RagJob.created_at, RagJob.updated_at,
                ).where(RagJob.id == job_id, RagJob.index_key == index_key)
            )
            return result.mappings().one_or_none()

    @asynccontextmanager
    async def worker_lock(self, engine: AsyncEngine, index_key: str):
        lock_key = int.from_bytes(bytes.fromhex(index_key[:16]), "big", signed=True)
        async with engine.connect() as connection:
            try:
                acquired = await connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key}
                )
                await connection.commit()
            except BaseException:
                await connection.invalidate()
                raise
            try:
                yield acquired
            finally:
                if acquired:
                    try:
                        await connection.execute(
                            text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key}
                        )
                        await connection.commit()
                    except BaseException:
                        await connection.invalidate()
                        raise

    async def claim(self, version: str, index_key: str) -> tuple[RagJob, str | None] | None:
        async with self.sessions.begin() as session:
            job = await session.scalar(
                select(RagJob)
                .where(RagJob.index_key == index_key, RagJob.status.in_(("queued", "running")))
                .order_by(case((RagJob.status == "running", 0), else_=1), RagJob.created_at, RagJob.id)
                .with_for_update()
                .limit(1)
            )
            if job is None:
                return None
            previous_attempt = job.version
            job.status = "running"
            job.version = version
            job.updated_at = func.now()
            return job, previous_attempt

    async def publish(self, job: RagJob, index_key: str, count: int) -> bool:
        async with self.sessions.begin() as session:
            result = await session.execute(
                self.finish(job).values(status="succeeded", chunk_count=count).returning(RagJob.id)
            )
            if result.scalar_one_or_none() is None:
                return False
            await session.execute(
                insert(RagDocument)
                .values(source_id=job.source_id, active_version=job.version, index_key=index_key)
                .on_conflict_do_update(
                    index_elements=[RagDocument.source_id, RagDocument.index_key],
                    set_={"active_version": job.version},
                )
            )
            return True

    async def fail(self, job: RagJob, error_code: str) -> None:
        async with self.sessions.begin() as session:
            await session.execute(self.finish(job).values(status="failed", error_code=error_code))

    def finish(self, job: RagJob):
        return (
            update(RagJob)
            .where(RagJob.id == job.id, RagJob.version == job.version, RagJob.status == "running")
            .values(data=None, updated_at=func.now())
        )

    async def active_versions(self, index_key: str) -> list[str]:
        async with self.sessions() as session:
            return list(await session.scalars(
                select(RagDocument.active_version).where(RagDocument.index_key == index_key)
            ))
