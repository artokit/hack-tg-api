from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID

from sqlalchemy import case, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from db.models import RagDocument, RagJob
from models.rag import RagImport, RagQueueUnavailable


class RagJobs:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], engine: AsyncEngine):
        self.sessions = sessions
        self.engine = engine

    @asynccontextmanager
    async def session(self, *, transaction: bool = False):
        try:
            async with (self.sessions.begin() if transaction else self.sessions()) as session:
                yield session
        except SQLAlchemyError as error:
            raise RagQueueUnavailable("import_queue_unavailable") from error

    async def enqueue(
        self, job_id: UUID, index_key: str, source_id: str, title: str | None,
        source_url: str | None, format: str, file_id: UUID | None = None,
    ) -> None:
        async with self.session(transaction=True) as session:
            session.add(RagJob(
                id=job_id,
                index_key=index_key, source_id=source_id, title=title or "", source_url=source_url,
                format=format, file_id=file_id,
            ))

    async def read(self, job_id: UUID, index_key: str):
        async with self.session() as session:
            result = await session.execute(
                select(
                    RagJob.id, RagJob.source_id, RagJob.file_id, RagJob.status, RagJob.error_code,
                    RagJob.version, RagJob.chunk_count, RagJob.created_at, RagJob.updated_at,
                ).where(RagJob.id == job_id, RagJob.index_key == index_key)
            )
            return result.mappings().one_or_none()

    @asynccontextmanager
    async def worker_lock(self, index_key: str):
        try:
            async with self.advisory_lock(index_key) as acquired:
                yield acquired
        except SQLAlchemyError as error:
            raise RagQueueUnavailable("import_queue_unavailable") from error

    @asynccontextmanager
    async def advisory_lock(self, index_key: str):
        lock_key = int.from_bytes(bytes.fromhex(index_key[:16]), "big", signed=True)
        async with self.engine.connect() as connection:
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

    async def claim(self, version: str, index_key: str) -> RagImport | None:
        async with self.session(transaction=True) as session:
            job = await session.scalar(
                select(RagJob)
                .where(RagJob.index_key == index_key, RagJob.status.in_(("queued", "running")))
                .order_by(case((RagJob.status == "running", 0), else_=1), RagJob.created_at, RagJob.id)
                .with_for_update()
                .limit(1)
            )
            if job is None:
                return None
            resumed = job.status == "running"
            job.status = "running"
            job.version = job.version or version
            job.updated_at = func.now()
            return RagImport(
                job.id, job.source_id, job.title, job.source_url, job.format, job.version, resumed, job.file_id,
            )

    async def publish(self, job: RagImport, index_key: str, count: int) -> bool:
        async with self.session(transaction=True) as session:
            result = await session.execute(
                self.finish(job).values(status="succeeded", chunk_count=count).returning(RagJob.id)
            )
            if result.scalar_one_or_none() is None:
                return False
            previous = await session.scalar(
                select(RagDocument.active_version).where(
                    RagDocument.source_id == job.source_id, RagDocument.index_key == index_key,
                )
            )
            if previous:
                await session.execute(
                    update(RagJob).where(RagJob.index_key == index_key, RagJob.version == previous)
                    .values(updated_at=func.now())
                )
            await session.execute(
                insert(RagDocument)
                .values(source_id=job.source_id, active_version=job.version, index_key=index_key)
                .on_conflict_do_update(
                    index_elements=[RagDocument.source_id, RagDocument.index_key],
                    set_={"active_version": job.version},
                )
            )
            return True

    async def retired(self, index_key: str, grace: timedelta) -> list[tuple[UUID, str]]:
        active = select(RagDocument.active_version).where(RagDocument.index_key == index_key)
        async with self.session() as session:
            rows = await session.execute(
                select(RagJob.id, RagJob.version).where(
                    RagJob.index_key == index_key,
                    RagJob.status.in_(("succeeded", "failed")),
                    RagJob.purged_at.is_(None),
                    RagJob.version.is_not(None),
                    RagJob.version.not_in(active),
                    RagJob.updated_at < func.now() - grace,
                ).order_by(RagJob.updated_at).limit(20)
            )
            return [(job_id, version) for job_id, version in rows if version]

    async def mark_purged(self, job_id: UUID) -> None:
        async with self.session(transaction=True) as session:
            await session.execute(update(RagJob).where(RagJob.id == job_id).values(purged_at=func.now()))

    async def fail(self, job: RagImport, error_code: str) -> None:
        async with self.session(transaction=True) as session:
            await session.execute(self.finish(job).values(status="failed", error_code=error_code))

    def finish(self, job: RagImport):
        return (
            update(RagJob)
            .where(RagJob.id == job.id, RagJob.version == job.version, RagJob.status == "running")
            .values(updated_at=func.now())
        )

    async def active_versions(self, index_key: str) -> list[str]:
        async with self.session() as session:
            return list(await session.scalars(
                select(RagDocument.active_version).where(RagDocument.index_key == index_key)
            ))
