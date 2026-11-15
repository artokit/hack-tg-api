import re
from collections import defaultdict
from datetime import timedelta
from pathlib import PurePosixPath
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from db.models import RagDocument, RagGithubSync, RagJob
from models.github import GITHUB_BRANCH, GITHUB_REPOSITORY, GithubDocument
from models.rag import InvalidDocument, RagUnavailable
from repositories.rag_files import DOCUMENT_FORMATS, read_document
from repositories.rag_jobs import RagJobs


GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}"
GITHUB_RAW = f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}"
GIT_SHA = re.compile(r"[0-9a-f]{40}")
PENDING_STATUSES = ("queued", "running")


def valid_path(path: str) -> bool:
    return all(part not in ("", ".", "..") for part in path.split("/")) and "\x00" not in path


class GithubRepository:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def snapshot(self) -> list[GithubDocument]:
        try:
            head = await self.get_json(f"git/ref/heads/{GITHUB_BRANCH}")
            commit = head["object"]["sha"]
            if not GIT_SHA.fullmatch(commit):
                raise ValueError("Invalid commit SHA")
            tree = await self.get_json(f"git/trees/{commit}", recursive="1")
            if tree["truncated"] is not False:
                raise RagUnavailable("github_tree_truncated")
            if not isinstance(tree["tree"], list):
                raise ValueError("Invalid Git tree")
            documents = []
            for entry in tree["tree"]:
                if entry["type"] != "blob" or entry["mode"] not in ("100644", "100755"):
                    continue
                path = entry["path"]
                format = PurePosixPath(path).suffix.lower().removeprefix(".")
                if format not in DOCUMENT_FORMATS:
                    continue
                revision = entry["sha"]
                size = entry["size"]
                if not valid_path(path) or not GIT_SHA.fullmatch(revision) or not 0 <= size < 2**31:
                    raise ValueError("Invalid document metadata")
                documents.append(GithubDocument(path, commit, revision, format, size))
            return documents
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise RagUnavailable("github_unavailable") from error

    async def get_json(self, path: str, **params: str) -> dict:
        response = await self.http.get(f"{GITHUB_API}/{path}", params=params)
        response.raise_for_status()
        return response.json()

    async def download(self, locator: dict[str, str]) -> bytes:
        commit = locator.get("commit", "")
        path = locator.get("path", "")
        if not GIT_SHA.fullmatch(commit) or not valid_path(path):
            raise InvalidDocument("invalid_source_locator")
        try:
            async with self.http.stream(
                "GET", f"{GITHUB_RAW}/{commit}/{quote(path)}", headers={"Accept-Encoding": "identity"},
            ) as response:
                response.raise_for_status()
                return await read_document(response)
        except httpx.HTTPError as error:
            raise RagUnavailable("github_unavailable") from error


class GithubSyncRepository:
    def __init__(self, jobs: RagJobs, index_key: str):
        self.jobs = jobs
        self.index_key = index_key

    async def request(self) -> None:
        async with self.jobs.session(transaction=True) as session:
            statement = insert(RagGithubSync).values(index_key=self.index_key, request_id=uuid4())
            await session.execute(statement.on_conflict_do_update(
                index_elements=[RagGithubSync.index_key],
                set_={"request_id": statement.excluded.request_id, "retry_at": None},
            ))

    async def pending(self) -> UUID | None:
        async with self.jobs.session() as session:
            return await session.scalar(select(RagGithubSync.request_id).where(
                RagGithubSync.index_key == self.index_key,
                (RagGithubSync.retry_at.is_(None) | (RagGithubSync.retry_at <= func.now())),
            ))

    async def retry(self, request_id: UUID) -> None:
        async with self.jobs.session(transaction=True) as session:
            await session.execute(update(RagGithubSync).where(
                RagGithubSync.index_key == self.index_key, RagGithubSync.request_id == request_id,
            ).values(retry_at=func.now() + timedelta(minutes=1)))

    async def reconcile(self, request_id: UUID, documents: list[GithubDocument]) -> int:
        desired = {document.source_id: document for document in documents}
        async with self.jobs.session(transaction=True) as session:
            scope = (RagJob.index_key == self.index_key, RagJob.source_kind == "github", RagJob.status != "deleting")
            known = await session.scalars(select(RagJob.source_id).where(*scope).distinct())
            source_ids = set(known) | desired.keys()
            for source_id in sorted(source_ids):
                await self.jobs.lock_source(session, self.index_key, source_id)
            rows = await session.scalars(
                select(RagJob).where(*scope).order_by(RagJob.created_at.desc(), RagJob.id.desc()).with_for_update()
            )
            jobs_by_source: dict[str, list[RagJob]] = defaultdict(list)
            for job in rows:
                jobs_by_source[job.source_id].append(job)
            active_scope = (RagDocument.index_key == self.index_key, RagDocument.source_id.in_(source_ids))
            active = {row.source_id: row for row in await session.scalars(select(RagDocument).where(*active_scope))}
            removed = jobs_by_source.keys() - desired.keys()
            if removed:
                await session.execute(delete(RagDocument).where(*active_scope, RagDocument.source_id.in_(removed)))
                for source_id in removed:
                    await self.jobs.schedule_source_cleanup(session, jobs_by_source[source_id])
            enqueued = 0
            for source_id, document in desired.items():
                jobs = jobs_by_source[source_id]
                job = jobs[0] if jobs else None
                published = active.get(source_id)
                current = published is not None and published.source_revision == document.revision
                if job is None:
                    job = RagJob(index_key=self.index_key, source_id=source_id, source_kind="github")
                    session.add(job)
                elif (
                    job.status in PENDING_STATUSES and job.source_revision == document.revision
                    and (not current or (job.source_locator or {}).get("refresh_visuals") == "true")
                ):
                    continue
                elif current and published is not None:
                    if job.version != published.active_version:
                        self.jobs.requeue(job)
                        self.set_document(job, document)
                        self.jobs.restore_published(job, published)
                    continue
                else:
                    self.jobs.requeue(job)
                self.set_document(job, document)
                enqueued += 1
            await session.execute(delete(RagGithubSync).where(
                RagGithubSync.index_key == self.index_key, RagGithubSync.request_id == request_id,
            ))
            return enqueued

    @staticmethod
    def set_document(job: RagJob, document: GithubDocument) -> None:
        job.title = document.title
        job.source_url = document.url
        job.format = document.format
        job.size_bytes = document.size_bytes
        job.source_revision = document.revision
        job.source_locator = {"path": document.path, "commit": document.commit}
