import logging
import re
from uuid import UUID, uuid4

from models.rag import RagQueueUnavailable, RagUnavailable
from repositories.rag_extract import identifiers
from repositories.rag_index import RagIndex
from repositories.rag_jobs import RagJobs
from repositories.rag_uploads import RagUploads


log = logging.getLogger(__name__)
REGISTRY = re.compile(
    r"\bреестр(?:а|е|у|ом|ы|ов)?\s+[«\"]?(мебели|техники)\b", re.IGNORECASE
)


class UnexpectedDocumentId(ValueError):
    pass


class RagService:
    def __init__(self, jobs: RagJobs, index: RagIndex, uploads: RagUploads):
        self.jobs = jobs
        self.index = index
        self.uploads = uploads

    async def submit(
        self, source_id: str, title: str, source_url: str | None, format: str, data: bytes
    ) -> UUID:
        job_id = uuid4()
        try:
            await self.uploads.save(job_id, data)
        except OSError as error:
            raise RagUnavailable("upload_storage_unavailable") from error
        try:
            await self.jobs.enqueue(job_id, self.index.key, source_id, title, source_url, format)
        except RagQueueUnavailable:
            self.uploads.discard(job_id)
            raise
        return job_id

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

    @staticmethod
    def evidence(
        chunks: list[dict], identifier: str | None, linked: set[str] | None = None,
    ) -> dict[str, dict]:
        found: dict[str, dict] = {}
        size = 0
        for chunk in chunks:
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
                    **block, "title": chunk["title"], "source_url": chunk["source_url"],
                    "format": chunk["format"],
                }
        return found
