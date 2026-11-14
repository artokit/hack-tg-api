import logging
import re
from pathlib import PurePath
from uuid import UUID, uuid4

from models.rag import DocumentTooLarge, InvalidDocument, RagQueueUnavailable, RagUnavailable
from repositories.rag_extract import identifiers
from repositories.rag_files import DOCUMENT_FORMATS, MAX_DOCUMENT_BYTES, RagFiles
from repositories.rag_index import RagIndex
from repositories.rag_jobs import RagJobs


log = logging.getLogger(__name__)
REGISTRY = re.compile(
    r"\bреестр(?:а|е|у|ом|ы|ов)?\s+[«\"]?(мебели|техники)\b", re.IGNORECASE
)


class UnexpectedDocumentId(ValueError):
    pass


class RagOriginals:
    def __init__(self, files: RagFiles):
        self.files = files

    async def open(self, file_id: UUID, signature: str, byte_range: str | None):
        if self.files.permits(file_id, signature):
            return await self.files.open(file_id, byte_range)
        return None


class RagService:
    def __init__(self, jobs: RagJobs, index: RagIndex, files: RagFiles):
        self.jobs = jobs
        self.index = index
        self.files = files

    async def submit_file(
        self, source_id: str | None, title: str | None, filename: str, data: bytes,
    ) -> tuple[UUID, str, UUID]:
        name = PurePath(filename.replace("\\", "/")).name
        format = PurePath(name).suffix.lower().removeprefix(".")
        if format not in DOCUMENT_FORMATS:
            raise InvalidDocument("unsupported_source_format")
        if len(data) > MAX_DOCUMENT_BYTES:
            raise DocumentTooLarge("document_too_large")
        if not data:
            raise InvalidDocument("empty_document")
        job_id = uuid4()
        source_id = source_id or str(uuid4())
        file_id = await self.files.upload(name, data)
        await self.jobs.enqueue(
            job_id, self.index.key, source_id, title or name[:250], None, format, file_id,
        )
        return job_id, source_id, file_id

    async def submit_url(self, source_id: str | None, title: str | None, url: str) -> tuple[UUID, str]:
        job_id = uuid4()
        source_id = source_id or str(uuid4())
        await self.jobs.enqueue(job_id, self.index.key, source_id, title, url, "url")
        return job_id, source_id

    async def read_job(self, job_id: UUID):
        return await self.jobs.read(job_id, self.index.key)

    async def search(self, question: str, exact_id: str | None, original: str) -> list[dict]:
        allowed = identifiers(original) or identifiers(question)
        if exact_id and exact_id not in allowed:
            raise UnexpectedDocumentId("Unexpected document ID")
        try:
            versions = await self.jobs.active_versions(self.index.key)
        except RagQueueUnavailable as error:
            raise RagUnavailable("index_unavailable") from error
        if not versions:
            return []
        if exact_id:
            chunks = await self.index.exact(exact_id, versions)
            log.info("RAG retrieval (exact, %d candidates)", len(chunks))
            if not chunks:
                return []
            evidence = self.evidence(chunks, exact_id)
            anchor_keys = {block["id"] for block in evidence.values()}
            links = list(dict.fromkeys(
                ref for chunk in chunks[:12]
                if any(block["id"] in anchor_keys for block in chunk["evidence"])
                for ref in chunk["related"] if ref not in anchor_keys
            ))[:12]
            related = await self.index.related(links, versions)
            evidence.update({
                key: block for key, block in self.evidence(related, None, set(links)).items()
                if key not in evidence and not set(block["identifiers"]) - {exact_id}
            })
        else:
            chunks = await self.index.semantic(question, versions)
            log.info("RAG retrieval (semantic, %d candidates)", len(chunks))
            related = list(dict.fromkeys(ref for chunk in chunks[:3] for ref in chunk["related"]))[:6]
            evidence = self.evidence([*chunks, *await self.index.related(related, versions)], None)
        registries = {match.casefold() for match in REGISTRY.findall(question)}
        if len(registries) == 1:
            evidence = {
                key: block for key, block in evidence.items()
                if registries & {
                    match.casefold() for match in REGISTRY.findall(
                        " ".join([block["title"], *block["section"]])
                    )
                }
            }
        return list(evidence.values())

    def evidence(
        self, chunks: list[dict], identifier: str | None, linked: set[str] | None = None,
    ) -> dict[str, dict]:
        found: dict[str, dict] = {}
        size = 0
        for chunk in chunks:
            file_id = chunk.get("file_id")
            source_url = self.files.link(UUID(file_id)) if file_id else chunk["source_url"]
            for block in chunk["evidence"]:
                if (
                    block["id"] in found
                    or identifier and identifier not in block["identifiers"]
                    or linked is not None and block["id"] not in linked
                ):
                    continue
                size += len(block["text"])
                if size > 23500:
                    return found
                found[block["id"]] = {
                    **block, "title": chunk["title"], "source_url": source_url,
                    "format": chunk["format"],
                }
        return found
