from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID

from sqlalchemy import case, delete, func, select, text, true, update
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from db.models import RagDocument, RagImportArtifact, RagJob
from models.rag import RETIRED_VERSION_GRACE, RagImport, RagQueueUnavailable


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
        source_url: str | None, format: str, file_id: UUID | None = None, size_bytes: int | None = None,
    ) -> None:
        async with self.session(transaction=True) as session:
            await self.lock_source(session, index_key, source_id)
            session.add(RagJob(
                id=job_id,
                index_key=index_key, source_id=source_id, title=title or "", source_url=source_url,
                format=format, file_id=file_id, size_bytes=size_bytes,
            ))

    @staticmethod
    async def lock_source(session: AsyncSession, index_key: str, source_id: str) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:source, 0))"),
            {"source": f"rag-source:{index_key}:{source_id}"},
        )

    async def source_for(self, job_id: UUID, index_key: str) -> str | None:
        async with self.session() as session:
            return await session.scalar(select(RagJob.source_id).where(
                RagJob.id == job_id, RagJob.index_key == index_key,
            ))

    @staticmethod
    def retire_attempt(session: AsyncSession, job: RagJob, *, deleted: bool = False) -> None:
        if not (job.version or job.file_id or (deleted and not job.source_url)):
            return
        session.add(RagImportArtifact(
            index_key=job.index_key, source_id=job.source_id, version=job.version,
            file_id=job.file_id,
            upload_job_id=job.id if job.file_id is None and not job.source_url else None,
            delete_original=deleted, retry_at=func.now() if deleted else func.now() + RETIRED_VERSION_GRACE,
        ))

    async def replace(
        self, job_id: UUID, index_key: str, source_id: str, title: str, format: str, file_id: UUID, size_bytes: int,
    ) -> bool:
        async with self.session(transaction=True) as session:
            await self.lock_source(session, index_key, source_id)
            job = await session.scalar(select(RagJob).where(
                RagJob.id == job_id, RagJob.index_key == index_key, RagJob.source_id == source_id,
            ).with_for_update())
            if job is None:
                session.add(RagImportArtifact(
                    index_key=index_key, source_id=source_id, file_id=file_id, delete_original=True, retry_at=func.now(),
                ))
                return False
            self.retire_attempt(session, job)
            job.title = title
            job.format = format
            job.file_id = file_id
            job.size_bytes = size_bytes
            job.source_url = None
            job.status = "queued"
            job.error_code = None
            job.version = None
            job.chunk_count = None
            job.purged_at = None
            job.created_at = func.clock_timestamp()
            job.updated_at = func.now()
            return True

    async def delete_source(self, job_id: UUID, index_key: str) -> bool:
        async with self.session(transaction=True) as session:
            source_id = await session.scalar(select(RagJob.source_id).where(
                RagJob.id == job_id, RagJob.index_key == index_key,
            ))
            if source_id is None:
                return False
            await self.lock_source(session, index_key, source_id)
            scope = (RagJob.index_key == index_key, RagJob.source_id == source_id)
            jobs = list(await session.scalars(select(RagJob).where(*scope).with_for_update()))
            if not any(job.id == job_id for job in jobs):
                return False
            await session.execute(delete(RagDocument).where(
                RagDocument.index_key == index_key, RagDocument.source_id == source_id,
            ))
            await session.execute(update(RagImportArtifact).where(
                RagImportArtifact.index_key == index_key, RagImportArtifact.source_id == source_id,
            ).values(delete_original=True, retry_at=func.now()))
            for job in jobs:
                self.retire_attempt(session, job, deleted=True)
            await session.execute(delete(RagJob).where(*scope))
            return True

    async def is_file_deleted(self, file_id: UUID) -> bool:
        async with self.session() as session:
            return bool(await session.scalar(select(select(RagImportArtifact.id).where(
                RagImportArtifact.file_id == file_id, RagImportArtifact.delete_original.is_(True),
            ).exists())))

    async def cleanup_candidates(self, index_key: str):
        async with self.session() as session:
            active = select(RagDocument.active_version).where(
                RagDocument.index_key == index_key, RagDocument.active_version == RagImportArtifact.version,
            ).exists()
            return list(await session.scalars(select(RagImportArtifact).where(
                RagImportArtifact.index_key == index_key, RagImportArtifact.retry_at <= func.now(), ~active,
            ).order_by(RagImportArtifact.retry_at, RagImportArtifact.id).limit(8)))

    async def finish_cleanup(self, artifact: RagImportArtifact, *, success: bool) -> None:
        async with self.session(transaction=True) as session:
            where = (RagImportArtifact.id == artifact.id, RagImportArtifact.delete_original == artifact.delete_original)
            if not success:
                statement = update(RagImportArtifact).where(*where).values(retry_at=func.now() + timedelta(seconds=30))
            elif not artifact.delete_original and artifact.file_id:
                statement = update(RagImportArtifact).where(*where).values(version=None, upload_job_id=None, retry_at=None)
            else:
                statement = delete(RagImportArtifact).where(*where)
            await session.execute(statement)

    async def read(self, job_id: UUID, index_key: str):
        async with self.session() as session:
            result = await session.execute(
                select(
                    RagJob.id, RagJob.source_id, RagJob.file_id, RagJob.status, RagJob.error_code,
                    RagJob.version, RagJob.chunk_count, RagJob.created_at, RagJob.updated_at,
                ).where(RagJob.id == job_id, RagJob.index_key == index_key)
            )
            return result.mappings().one_or_none()

    async def list_jobs(self, index_key: str, offset: int, limit: int, include_history: bool):
        scope = RagJob.index_key == index_key
        latest = (
            select(RagJob.id).where(scope).ext(distinct_on(RagJob.source_id))
            .order_by(RagJob.source_id, RagJob.created_at.desc(), RagJob.id.desc())
        )
        filters = (scope,) if include_history else (RagJob.id.in_(latest),)
        has_active_version = select(RagDocument.source_id).where(
            RagDocument.index_key == RagJob.index_key, RagDocument.source_id == RagJob.source_id,
        ).exists()
        page = (
            select(
                RagJob.id, RagJob.source_id, RagJob.file_id, RagJob.status, RagJob.error_code,
                RagJob.version, RagJob.chunk_count, RagJob.created_at, RagJob.updated_at,
                RagJob.title, RagJob.source_url, RagJob.format, RagJob.size_bytes,
                has_active_version.label("has_active_version"),
            ).where(*filters).order_by(RagJob.created_at.desc(), RagJob.id.desc())
            .offset(offset).limit(limit).subquery()
        )
        total = select(func.count().label("total")).select_from(RagJob).where(*filters).subquery()
        async with self.session() as session:
            result = await session.execute(
                select(page, total.c.total).select_from(total.outerjoin(page, true()))
                .order_by(page.c.created_at.desc(), page.c.id.desc())
            )
            rows = result.mappings().all()
            return [{key: value for key, value in row.items() if key != "total"} for row in rows if row["id"]], rows[0]["total"]

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

    async def publish(self, job: RagImport, index_key: str, count: int, size_bytes: int) -> bool:
        async with self.session(transaction=True) as session:
            await self.lock_source(session, index_key, job.source_id)
            result = await session.execute(
                self.finish(job).values(
                    status="succeeded", chunk_count=count, title=job.title, format=job.format, size_bytes=size_bytes,
                ).returning(RagJob.id)
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
                await session.execute(update(RagImportArtifact).where(
                    RagImportArtifact.index_key == index_key, RagImportArtifact.version == previous,
                ).values(retry_at=func.now() + RETIRED_VERSION_GRACE))
            await session.execute(
                insert(RagDocument)
                .values(source_id=job.source_id, active_version=job.version, index_key=index_key)
                .on_conflict_do_update(
                    index_elements=[RagDocument.source_id, RagDocument.index_key],
                    set_={"active_version": job.version},
                )
            )
            return True

    async def retired(self, index_key: str) -> list[tuple[UUID, str]]:
        active = select(RagDocument.active_version).where(RagDocument.index_key == index_key)
        async with self.session() as session:
            rows = await session.execute(
                select(RagJob.id, RagJob.version).where(
                    RagJob.index_key == index_key,
                    RagJob.status.in_(("succeeded", "failed")),
                    RagJob.purged_at.is_(None),
                    RagJob.version.is_not(None),
                    RagJob.version.not_in(active),
                    RagJob.updated_at < func.now() - RETIRED_VERSION_GRACE,
                ).order_by(RagJob.updated_at).limit(20)
            )
            return [(job_id, version) for job_id, version in rows if version]

    async def mark_purged(self, job_id: UUID, version: str) -> None:
        async with self.session(transaction=True) as session:
            await session.execute(update(RagJob).where(
                RagJob.id == job_id, RagJob.version == version,
            ).values(purged_at=func.now()))

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
