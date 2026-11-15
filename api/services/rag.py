import asyncio
import logging
import re
from pathlib import PurePath
from unicodedata import normalize
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError

from models.github import GITHUB_SOURCE_PREFIX
from models.rag import DocumentTooLarge, InvalidDocument, RagDocumentNotFound, RagQueueUnavailable, RagUnavailable
from repositories.rag_cache import RagCache
from repositories.rag_extract import identifiers, render_pdf_region, telegram_png
from repositories.rag_files import DOCUMENT_FORMATS, MAX_DOCUMENT_BYTES, RagFiles
from repositories.rag_index import RagIndex
from repositories.rag_jobs import RagJobs
from schemas.rag import RagAnswerRead, RagCachedEvidence


log = logging.getLogger(__name__)
CACHED_EVIDENCE = TypeAdapter(list[RagCachedEvidence])
REGISTRY = re.compile(
    r"\bреестр(?:а|е|у|ом|ы|ов)?\s+[«\"]?(мебели|техники)\b", re.IGNORECASE
)


class UnexpectedDocumentId(ValueError):
    pass


class RagOriginals:
    def __init__(self, files: RagFiles, jobs: RagJobs):
        self.files = files
        self.jobs = jobs

    async def open(self, file_id: UUID, signature: str, byte_range: str | None):
        if self.files.permits(file_id, signature) and not await self.jobs.is_file_deleted(file_id):
            return await self.files.open(file_id, byte_range)
        return None


class RagService:
    def __init__(self, jobs: RagJobs, index: RagIndex, files: RagFiles, cache: RagCache):
        self.jobs = jobs
        self.index = index
        self.files = files
        self.cache = cache

    async def submit_file(
        self, source_id: str | None, title: str | None, filename: str, data: bytes,
        *, replaces: UUID | None = None,
    ) -> tuple[UUID, str, UUID]:
        if source_id and source_id.startswith(("confluence:", GITHUB_SOURCE_PREFIX)):
            raise InvalidDocument("reserved_source_id")
        name = PurePath(filename.replace("\\", "/")).name
        format = PurePath(name).suffix.lower().removeprefix(".")
        if format not in DOCUMENT_FORMATS:
            raise InvalidDocument("unsupported_source_format")
        if len(data) > MAX_DOCUMENT_BYTES:
            raise DocumentTooLarge("document_too_large")
        if not data:
            raise InvalidDocument("empty_document")
        job_id = replaces or uuid4()
        source_id = source_id or str(uuid4())
        file_id = await self.files.upload(name, data)
        title = title or name[:250]
        if replaces is None:
            await self.jobs.enqueue(
                job_id, self.index.key, source_id, title, None, format, file_id, len(data), source_kind="file",
            )
        else:
            replaced = await self.jobs.replace(job_id, self.index.key, source_id, title, format, file_id, len(data))
            if replaced is None:
                await self.files.delete(file_id)
            if not replaced:
                raise RagDocumentNotFound
        return job_id, source_id, file_id

    async def replace_file(self, job_id: UUID, title: str | None, filename: str, data: bytes) -> tuple[UUID, str, UUID]:
        source_id = await self.jobs.replaceable_source(job_id, self.index.key)
        if source_id is None:
            raise RagDocumentNotFound
        return await self.submit_file(source_id, title, filename, data, replaces=job_id)

    async def delete_document(self, job_id: UUID) -> None:
        if not await self.jobs.delete_source(job_id, self.index.key):
            raise RagDocumentNotFound

    async def delete_confluence_document(self, space_id: str, page_id: str) -> None:
        await self.jobs.delete_confluence_source(self.index.key, space_id, page_id)

    async def submit_url(self, source_id: str | None, title: str | None, url: str) -> tuple[UUID, str]:
        if source_id and source_id.startswith(("confluence:", GITHUB_SOURCE_PREFIX)):
            raise InvalidDocument("reserved_source_id")
        job_id = uuid4()
        source_id = source_id or str(uuid4())
        await self.jobs.enqueue(job_id, self.index.key, source_id, title, url, "url", source_kind="url")
        return job_id, source_id

    async def submit_confluence(self, space_id: str, page_id: str) -> tuple[UUID, str]:
        source_id = f"confluence:{page_id}"
        job_id = await self.jobs.enqueue_confluence(self.index.key, source_id, space_id, page_id)
        return job_id, source_id

    async def read_job(self, job_id: UUID):
        return await self.jobs.read(job_id, self.index.key)

    async def refresh_visuals(self, job_id: UUID) -> tuple[UUID, str]:
        return await self.jobs.enqueue_visual_refresh(job_id, self.index.key)

    async def list_jobs(self, page: int, page_size: int, include_history: bool):
        rows, total = await self.jobs.list_jobs(self.index.key, (page - 1) * page_size, page_size, include_history)
        items = []
        for row in rows:
            item = dict(row)
            url = item.pop("source_url")
            address = urlsplit(url) if url else None
            if not item["title"]:
                name = unquote(address.path.rsplit("/", 1)[-1]).strip() if address else ""
                item["title"] = (name or (address.hostname if address else None) or item["source_id"])[:250]
            item["document_url"] = self.files.link(item["file_id"]) if item["file_id"] else (
                url if address and address.scheme in ("https", "http") and address.hostname
                and not address.username and not address.password else None
            )
            items.append(item)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def visual(self, block_id: str, *, telegram: bool = False) -> bytes:
        versions = await self.jobs.active_versions(self.index.key)
        for chunk in await self.index.related([block_id], versions):
            for block in chunk["evidence"]:
                if block["id"] != block_id or block["kind"] not in ("visual", "scan"):
                    continue
                if block.get("image_file_id"):
                    image = await self.files.load(UUID(block["image_file_id"]))
                elif chunk["format"] == "pdf" and chunk.get("file_id") and block.get("box") and block.get("page"):
                    data = await self.files.load(UUID(chunk["file_id"]))
                    image = await asyncio.to_thread(render_pdf_region, data, block["page"], block["box"])
                else:
                    continue
                return await asyncio.to_thread(telegram_png, image) if telegram else image
        raise RagDocumentNotFound

    async def active_versions(self) -> list[str]:
        try:
            return await self.jobs.active_versions(self.index.key)
        except RagQueueUnavailable as error:
            raise RagUnavailable("index_unavailable") from error

    def answer_key(self, snapshot: str, question: str) -> str:
        normalized = normalize("NFC", " ".join(question.split()))
        return self.cache.answer_key(self.index.key, snapshot, normalized.removesuffix("?").rstrip() or normalized)

    async def cached_answer(self, question: str) -> RagAnswerRead | None:
        versions = await self.active_versions()
        if not versions:
            return None
        cached = await self.cache.get(self.answer_key(self.cache.snapshot(versions), question))
        if cached is None:
            return None
        try:
            answer = RagAnswerRead.model_validate_json(cached)
        except ValidationError:
            log.debug("RAG cached answer failed validation")
            return None
        for source in answer.sources:
            if source.file_id:
                source.url = self.files.link(source.file_id)
                if source.url and source.page:
                    source.url += f"#page={source.page}"
        return answer

    async def cache_answer(self, question: str, snapshot: str, answer: RagAnswerRead) -> None:
        sources = [source.model_copy(update={"url": None}) if source.file_id else source for source in answer.sources]
        cached = answer.model_copy(update={"sources": sources})
        await self.cache.set(self.answer_key(snapshot, question), cached.model_dump_json().encode())

    async def search(
        self, question: str, exact_id: str | None, original: str, *,
        standalone: bool = False, include_visual: bool = False,
    ) -> tuple[list[dict], str | None]:
        allowed = identifiers(original) or identifiers(question)
        if exact_id and exact_id not in allowed:
            raise UnexpectedDocumentId("Unexpected document ID")
        versions = await self.active_versions()
        if not versions:
            return [], None
        snapshot = self.cache.snapshot(versions)
        key = self.cache.search_key(self.index.key, snapshot, question, exact_id, include_visual=include_visual)
        original_key = self.cache.search_key(
            self.index.key, snapshot, original, exact_id, include_visual=include_visual,
        ) if standalone else None
        results = None
        cacheable = True
        if original_key:
            results = self.read_cached(await self.cache.get_by_original(original_key))
        if results is None:
            results = self.read_cached(await self.cache.get(key))
            if results is None:
                evidence, cacheable = await self.retrieve(question, exact_id, versions, include_visual=include_visual)
                results = CACHED_EVIDENCE.validate_python(evidence)
                if results and cacheable:
                    await self.cache.set(key, CACHED_EVIDENCE.dump_json(results))
            if original_key and results and cacheable:
                await self.cache.bind_original(original_key, key)
        evidence = [
            {
                **block.model_dump(exclude={"box", "image_file_id"}),
                "source_url": self.files.link(block.file_id) if block.file_id else block.source_url,
                "box": block.box if (
                    block.file_id and block.format == "pdf" and block.kind in ("visual", "scan")
                ) else None,
                "image_key": self.image_key(block),
            }
            for block in results
        ]
        return evidence, snapshot if standalone and evidence and cacheable else None

    @staticmethod
    def image_key(block: RagCachedEvidence) -> str | None:
        if block.kind not in ("visual", "scan"):
            return None
        if block.image_file_id:
            return str(block.image_file_id)
        if block.format == "pdf" and block.file_id and block.page and block.box:
            return f"{block.file_id}:{block.page}:{','.join(map(str, block.box))}"
        return None

    @staticmethod
    def read_cached(cached: bytes | None) -> list[RagCachedEvidence] | None:
        if cached is None:
            return None
        try:
            return CACHED_EVIDENCE.validate_json(cached) or None
        except ValidationError:
            log.debug("RAG cache entry failed validation")
            return None

    async def retrieve(
        self, question: str, exact_id: str | None, versions: list[str], *, include_visual: bool = False,
    ) -> tuple[list[dict], bool]:
        cacheable = True
        if exact_id:
            chunks = await self.index.exact(exact_id, versions)
            log.info("RAG retrieval (exact, %d candidates)", len(chunks))
            if not chunks:
                return [], cacheable
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
            chunks, visual_chunks = await self.index.semantic(question, versions, include_visual=include_visual)
            log.info("RAG retrieval (semantic, %d candidates)", len(chunks))
            related = list(dict.fromkeys(ref for chunk in chunks[:3] for ref in chunk["related"]))[:6]
            evidence = self.evidence([*chunks, *await self.index.related(related, versions)], None)
            cacheable = visual_chunks is not None
            if visual_chunks:
                visual_ids = {
                    block["id"] for chunk in visual_chunks for block in chunk["evidence"]
                    if block["kind"] in ("visual", "scan") and (
                        block.get("image_file_id")
                        or chunk["format"] == "pdf" and chunk.get("file_id") and block.get("page") and block.get("box")
                    )
                }
                visual_evidence = self.evidence(visual_chunks, None, visual_ids)
                for rank, (key, block) in enumerate(visual_evidence.items(), 1):
                    evidence.setdefault(key, block)["visual_rank"] = rank
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
        return list(evidence.values()), cacheable

    def evidence(
        self, chunks: list[dict], identifier: str | None, linked: set[str] | None = None,
    ) -> dict[str, dict]:
        found: dict[str, dict] = {}
        size = 0
        for chunk in chunks:
            file_id = chunk.get("file_id")
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
                    **block, "title": chunk["title"], "file_id": file_id,
                    "source_url": None if file_id else chunk["source_url"],
                    "format": chunk["format"],
                }
        return found
