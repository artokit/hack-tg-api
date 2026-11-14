import logging
import re
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from models.rag import RagUnavailable
from repositories.rag_extract import identifiers
from repositories.rag_index import RagIndex
from repositories.rag_jobs import RagJobs


log = logging.getLogger(__name__)
REGISTRY = re.compile(
    r"\bреестр(?:а|е|у|ом|ы|ов)?\s+[«\"]?(мебели|техники)\b", re.IGNORECASE
)


class UnexpectedDocumentId(ValueError):
    pass


class RagService:
    def __init__(self, jobs: RagJobs, index: RagIndex):
        self.jobs = jobs
        self.index = index

    async def submit(
        self, source_id: str, title: str, source_url: str | None, format: str, data: bytes
    ) -> UUID:
        return await self.jobs.enqueue(self.index.key, source_id, title, source_url, format, data)

    async def read_job(self, job_id: UUID):
        return await self.jobs.read(job_id, self.index.key)

    async def search(self, question: str, exact_id: str | None, original: str) -> list[dict]:
        allowed = identifiers(original) or identifiers(question)
        if exact_id and exact_id not in allowed:
            raise UnexpectedDocumentId("Unexpected document ID")
        try:
            versions = await self.jobs.active_versions(self.index.key)
        except SQLAlchemyError as error:
            raise RagUnavailable("index_unavailable") from error
        if not versions:
            return []
        if exact_id:
            chunks = await self.index.exact(exact_id, versions)
            log.info("RAG retrieval (exact, %d candidates)", len(chunks))
            if not chunks:
                return []
        else:
            chunks = await self.index.semantic(question, versions)
            log.info("RAG retrieval (semantic, %d candidates)", len(chunks))
            related = list(dict.fromkeys(ref for chunk in chunks[:3] for ref in chunk["related"]))[:6]
            chunks.extend(await self.index.related(related, versions))
        evidence = self.evidence(chunks, exact_id)
        named_registries = {match.casefold() for match in REGISTRY.findall(original)}
        registries = named_registries if len(named_registries) == 1 else {
            match.casefold() for match in REGISTRY.findall(question)
        }
        if len(registries) == 1:
            evidence = {
                key: block for key, block in evidence.items()
                if registries & {
                    match.casefold() for match in REGISTRY.findall(
                        " ".join([block["title"], block["text"], *block["section"]])
                    )
                }
            }
        return list(evidence.values())

    @staticmethod
    def evidence(chunks: list[dict], identifier: str | None) -> dict[str, dict]:
        found: dict[str, dict] = {}
        size = 0
        for chunk in chunks:
            for block in chunk["evidence"]:
                if block["id"] in found or identifier and identifier not in block["identifiers"]:
                    continue
                size += len(block["text"])
                if size > 23500:
                    return found
                found[block["id"]] = {
                    **block, "title": chunk["title"], "source_url": chunk["source_url"],
                    "format": chunk["format"],
                }
        return found
