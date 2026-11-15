import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from hashlib import sha256
from uuid import UUID, uuid4, uuid5

from models.rag import Block, Chunk, DocumentTooLarge, InvalidDocument, RagImport, RagQueueUnavailable, RagUnavailable
from repositories.rag_extract import extract_blocks, table_blocks, text_blocks
from repositories.rag_files import MAX_DOCUMENT_BYTES, RagFiles
from repositories.rag_index import RagIndex
from repositories.rag_jobs import RagJobs
from repositories.rag_model import RAG_MODEL_CONCURRENCY, RagModel
from repositories.rag_urls import load_url
from schemas.confluence import ConfluencePageRead
from services.confluence import ConfluenceService
from services.github import GithubService
from utils.exceptions import ConfluenceNotConfiguredError, ConfluenceTimeoutError, ConfluenceUnavailableError


log = logging.getLogger(__name__)
WINDOW_CHARS = 25000
WINDOW_BLOCKS = 30
TAIL_BLOCKS = 6
MAX_GROUP_CHARS = 6000
MAX_GROUP_BLOCKS = 10


def validate_plan(groups, window: list[Block], start: int, document_size: int) -> list[Chunk]:
    expected = start
    chunks = []
    for group in groups:
        if group["first"] != expected or not group["first"] <= group["last"] < start + len(window):
            raise ValueError("Диапазоны должны покрывать всё окно по порядку без пропусков.")
        blocks = window[group["first"] - start:group["last"] - start + 1]
        if len(blocks) > MAX_GROUP_BLOCKS or sum(len(block.text) for block in blocks) > MAX_GROUP_CHARS:
            raise ValueError("Не больше 10 блоков и 6000 символов на диапазон.")
        if len(blocks) > 1 and any(block.identifiers or block.kind in ("visual", "scan") for block in blocks):
            raise ValueError("Блоки с кодами и изображения должны быть отдельными.")
        tables = {block.table_id for block in blocks if block.table_id}
        if len(tables) > 1:
            raise ValueError("Одна группа не может смешивать разные таблицы.")
        members = tuple(range(group["first"], group["last"] + 1))
        if any(not 1 <= index <= document_size for index in group["related"]):
            raise ValueError("Связанные ID должны существовать в документе.")
        chunks.append(Chunk(members, tuple(dict.fromkeys(
            index for index in group["related"] if index not in members
        ))))
        expected = group["last"] + 1
    if expected != start + len(window):
        raise ValueError("Последний диапазон должен достигать конца окна.")
    return chunks


def group_adjacent(window: list[Block], start: int) -> list[Chunk]:
    chunks = []
    first = 0
    size = 0
    for offset, block in enumerate(window):
        anchor = window[first]
        if offset > first and (
            offset - first == MAX_GROUP_BLOCKS or size + len(block.text) > MAX_GROUP_CHARS
            or block.section != anchor.section or block.table_id != anchor.table_id
            or block.kind == "heading"
        ):
            chunks.append(Chunk(tuple(range(start + first, start + offset)), ()))
            first = offset
            size = 0
        size += len(block.text)
    chunks.append(Chunk(tuple(range(start + first, start + len(window))), ()))
    return chunks


class RagIngest:
    def __init__(
        self, jobs: RagJobs, index: RagIndex, model: RagModel,
        load: Callable[[RagImport], Awaitable[bytes]], discard_upload: Callable[[UUID], None],
        files: RagFiles,
        confluence: ConfluenceService, github: GithubService,
    ):
        self.jobs = jobs
        self.index = index
        self.model = model
        self.load = load
        self.discard_upload = discard_upload
        self.files = files
        self.confluence = confluence
        self.github = github

    async def worker(self) -> None:
        next_cleanup = 0.0
        while True:
            try:
                async with self.jobs.worker_lock(self.index.key) as locked:
                    if locked:
                        next_cleanup = await self.drain_queue(next_cleanup)
            except RagQueueUnavailable as error:
                log.warning("RAG queue unavailable (%s)", type(error).__name__)
            await asyncio.sleep(1)

    async def drain_queue(self, next_cleanup: float) -> float:
        running: dict[asyncio.Task[None], str] = {}
        async with asyncio.TaskGroup() as tasks:
            while True:
                try:
                    await self.github.sync_pending()
                    now = asyncio.get_running_loop().time()
                    if now >= next_cleanup:
                        active_sources = list(running.values())
                        await self.purge_artifacts(active_sources)
                        await self.purge_retired(active_sources)
                        next_cleanup = now + 30
                    while len(running) < 2:
                        job = await self.jobs.claim(str(uuid4()), self.index.key, list(running.values()))
                        if job is None:
                            break
                        running[tasks.create_task(self.process_job(job))] = job.source_id
                except RagQueueUnavailable as error:
                    log.warning("RAG queue unavailable (%s)", type(error).__name__)
                    await asyncio.sleep(1)
                if not running:
                    return next_cleanup
                done, _ = await asyncio.wait(
                    running, return_when=asyncio.FIRST_COMPLETED, timeout=1 if len(running) < 2 else None,
                )
                for task in done:
                    del running[task]

    async def process_job(self, job: RagImport) -> None:
        try:
            await self.process(job)
        except RagQueueUnavailable as error:
            log.warning("RAG import %s interrupted (%s)", job.id, type(error).__name__)
            await asyncio.sleep(1)

    async def purge_retired(self, active_sources: list[str]) -> None:
        for job_id, version in await self.jobs.retired(self.index.key, active_sources):
            if await self.discard(version):
                await self.jobs.mark_purged(job_id, version)

    async def purge_artifacts(self, active_sources: list[str]) -> None:
        async def purge(job_id: UUID, deleting: bool, artifact: dict) -> None:
            version = artifact["version"]
            file_id = artifact["file_id"]
            success = not version or await self.discard(version)
            if deleting and file_id:
                try:
                    await self.files.delete(UUID(file_id))
                except RagUnavailable:
                    log.warning("RAG could not delete original %s", file_id)
                    success = False
            if artifact["legacy"]:
                self.discard_upload(job_id)
            await self.jobs.finish_cleanup(job_id, artifact, deleting=deleting, success=success)

        rows = await self.jobs.cleanup_candidates(self.index.key, active_sources)
        results = await asyncio.gather(*(purge(**row) for row in rows), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def discard(self, version: str) -> bool:
        try:
            await self.index.discard(version)
            for file_id in await self.jobs.visual_files(self.index.key, version):
                await self.files.delete(file_id)
                await self.jobs.forget_visual_file(file_id)
        except RagUnavailable:
            log.warning("RAG could not discard inactive version %s", version)
            return False
        return True

    async def load_confluence(self, locator: dict[str, str]) -> ConfluencePageRead:
        try:
            page = await self.confluence.get_page(locator["space_id"], int(locator["page_id"]))
        except (KeyError, ValueError) as error:
            raise InvalidDocument("invalid_source_locator") from error
        except LookupError as error:
            raise InvalidDocument("confluence_page_not_found") from error
        except ConfluenceNotConfiguredError as error:
            raise RagUnavailable("confluence_not_configured") from error
        except ConfluenceTimeoutError as error:
            raise RagUnavailable("confluence_timeout") from error
        except ConfluenceUnavailableError as error:
            raise RagUnavailable("confluence_unavailable") from error
        if page.status != "current":
            raise InvalidDocument("confluence_page_not_current")
        return page

    async def process(self, job: RagImport) -> None:
        data = None
        try:
            async with asyncio.timeout(1800):
                if job.resumed and not await self.discard(job.version):
                    raise RagUnavailable("discard_unavailable")
                images = None
                if job.source_kind == "confluence":
                    page = await self.load_confluence(job.source_locator or {})
                    job = replace(job, title=page.title[:250], source_url=page.url, source_revision=str(page.version))
                    data = page.content_html.encode("utf-8")
                    if await self.jobs.restore_confluence(job, self.index.key, page.version, len(data)):
                        log.info("RAG import %s skipped Confluence version %d", job.id, page.version)
                        return
                    if len(data) > MAX_DOCUMENT_BYTES:
                        raise DocumentTooLarge("document_too_large")
                    try:
                        images = await self.confluence.page_images(page)
                    except ConfluenceTimeoutError as error:
                        raise RagUnavailable("confluence_timeout") from error
                    except ConfluenceUnavailableError as error:
                        raise RagUnavailable("confluence_unavailable") from error
                elif job.source_kind == "url" and job.source_url:
                    data, format, default_title = await load_url(job.source_url)
                    job = replace(job, title=job.title or default_title[:250], format=format)
                elif job.source_kind in ("file", "github"):
                    data = await self.load(job)
                else:
                    raise InvalidDocument("unsupported_source_kind")
                blocks = await asyncio.to_thread(extract_blocks, data, job.format, images)
                if job.format in ("docx", "html"):
                    blocks = await self.save_images(job.version, blocks)
                blocks = await self.enrich(blocks)
                if not blocks:
                    raise InvalidDocument("empty_document")
                chunks = await self.chunk(blocks)
                entries = [self.entry(job, blocks, chunk, index) for index, chunk in enumerate(chunks)]
                await self.index.write(job.version, entries)
        except (InvalidDocument, RagUnavailable, TimeoutError) as error:
            code = str(error) if str(error) else "import_timeout"
            log.warning("RAG import %s failed (%s)", job.id, code)
            await self.jobs.fail(job, code, len(data) if data is not None else None)
            await self.discard(job.version)
        except Exception as error:
            log.error("RAG import %s failed (%s)", job.id, type(error).__name__)
            await self.jobs.fail(job, "import_failed", len(data) if data is not None else None)
            await self.discard(job.version)
        else:
            if await self.jobs.publish(job, self.index.key, len(entries), len(data)):
                log.info("RAG import %s published %d chunks", job.id, len(entries))
            else:
                await self.discard(job.version)
        self.discard_upload(job.id)

    async def save_images(self, version: str, blocks: list[Block]) -> list[Block]:
        files: dict[UUID, bytes] = {}
        indexed = []
        for block in blocks:
            if block.image is not None:
                file_id = uuid5(UUID(version), sha256(block.image).hexdigest())
                files.setdefault(file_id, block.image)
                block = replace(block, image_file_id=file_id)
            indexed.append(block)
        await self.jobs.track_visual_files(self.index.key, version, list(files))
        for file_id, data in files.items():
            await self.files.put_visual(file_id, data)
        return indexed

    async def enrich(self, blocks: list[Block]) -> list[Block]:
        async def read(index: int, block: Block, image: bytes) -> list[Block]:
            visual = await self.model.read_visual(image, block.kind, block.label)
            location = {"page": block.page, "box": block.box, "section": block.section, "label": block.label}
            parsed = [
                replace(part, kind=block.kind)
                for part in text_blocks(visual["text"], **location)
            ]
            columns = visual["columns"]
            rows = [row["cells"] for row in visual["rows"] if columns and len(row["cells"]) == len(columns)]
            if len(rows) != len(visual["rows"]):
                log.warning("RAG skipped malformed visual table rows on page %s", block.page)
            if rows:
                parsed.extend(table_blocks(
                    [columns, *rows],
                    block.table_id or f"vision:{index}",
                    **location,
                ))
                parsed = [
                    replace(part, kind=block.kind)
                    for part in parsed
                ]
            if not parsed and block.kind == "scan":
                raise InvalidDocument("unreadable_visual")
            if not parsed and block.image_file_id:
                return [replace(block, image=None)]
            if not parsed and block.table_id:
                log.warning("RAG skipped an unreadable table on page %s", block.page)
            return [replace(part, image_file_id=block.image_file_id) for part in parsed]

        images = [
            (index, block, block.image)
            for index, block in enumerate(blocks) if block.image is not None
        ]
        remaining = iter(images)
        parsed: dict[int, list[Block]] = {}

        async def read_images() -> None:
            for index, block, image in remaining:
                parsed[index] = await read(index, block, image)

        pending = [asyncio.create_task(read_images()) for _ in range(min(len(images), RAG_MODEL_CONCURRENCY))]
        try:
            await asyncio.gather(*pending)
        except (Exception, asyncio.CancelledError):
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise
        return [
            part
            for index, block in enumerate(blocks)
            for part in (parsed[index] if index in parsed else [block])
        ]

    async def chunk(self, blocks: list[Block]) -> list[Chunk]:
        start = 0
        result = []
        while start < len(blocks):
            if blocks[start].identifiers or blocks[start].kind in ("visual", "scan"):
                related = tuple(
                    index + 1 for index in (start - 1, start + 1)
                    if 0 <= index < len(blocks)
                    and blocks[index].page == blocks[start].page
                    and blocks[index].section == blocks[start].section
                    and not blocks[index].identifiers
                    and blocks[index].kind in ("text", "heading")
                )
                result.append(Chunk((start + 1,), related))
                start += 1
                continue
            end = start
            size = 0
            while end < min(start + WINDOW_BLOCKS, len(blocks)):
                if blocks[end].identifiers or blocks[end].kind in ("visual", "scan"):
                    break
                if end > start and size + len(blocks[end].text) > WINDOW_CHARS:
                    break
                size += len(blocks[end].text)
                end += 1
            window = blocks[start:end]
            if len(window) == 1:
                result.append(Chunk((start + 1,), ()))
                start = end
                continue
            inputs = [
                {
                    "id": index, "kind": block.kind, "page": block.page, "section": block.section,
                    "text": block.text, "chars": len(block.text),
                    "identifiers": block.identifiers, "table": block.table_id,
                    "label": block.label,
                }
                for index, block in enumerate(window, start + 1)
            ]
            correction = ""
            for _ in range(2):
                try:
                    plan = await self.model.plan_chunks(inputs, correction)
                    chunks = validate_plan(plan["groups"], window, start + 1, len(blocks))
                except ValueError as error:
                    correction = str(error)
                except RagUnavailable:
                    chunks = group_adjacent(window, start + 1)
                    break
                else:
                    break
            else:
                chunks = group_adjacent(window, start + 1)
            if end < len(blocks) and not (
                blocks[end].identifiers or blocks[end].kind in ("visual", "scan")
            ):
                cut = max(start + 1, end - TAIL_BLOCKS)
                chunks = [chunk for chunk in chunks if chunk.blocks[-1] <= cut] or chunks[:1]
            result.extend(chunks)
            start = chunks[-1].blocks[-1]
        return result

    @staticmethod
    def entry(job: RagImport, blocks: list[Block], chunk: Chunk, order: int) -> dict:
        indexed = [blocks[index - 1] for index in chunk.blocks]
        search = [job.title]
        evidence = []
        for index, block in zip(chunk.blocks, indexed, strict=True):
            render = block.text
            if block.cells and block.columns:
                render = " | ".join(
                    f"{column}: {cell}" if column else cell
                    for column, cell in zip(block.columns, block.cells, strict=False)
                )
            search.extend(dict.fromkeys(
                item for item in (" / ".join(block.section), block.label, render) if item
            ))
            evidence.append({
                "id": f"{job.version}:{index}",
                "kind": block.kind,
                "text": block.text,
                "page": block.page,
                "box": [round(value * 100) for value in block.box] if block.box else None,
                "section": list(block.section),
                "cells": list(block.cells),
                "columns": list(block.columns),
                "table_id": block.table_id,
                "label": block.label,
                "identifiers": list(block.identifiers),
                "image_file_id": str(block.image_file_id) if block.image_file_id else None,
            })
        return {
            "source_id": job.source_id,
            "version": job.version,
            "title": job.title,
            "source_url": job.source_url,
            "file_id": str(job.file_id) if job.file_id else None,
            "format": job.format,
            "has_visual_file": any(block.image_file_id is not None for block in indexed),
            "order": order,
            "identifiers": list(dict.fromkeys(identifier for block in indexed for identifier in block.identifiers)),
            "block_ids": [part["id"] for part in evidence],
            "related": [f"{job.version}:{index}" for index in chunk.related],
            "evidence": evidence,
            "search_text": "\n".join(search),
        }
