import asyncio
import logging
from dataclasses import replace
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from agents.rag import Luna
from db.models import RagJob
from models.rag import Block, Chunk, InvalidDocument, RagUnavailable
from repositories.rag_extract import extract_blocks, table_blocks, text_blocks
from repositories.rag_index import RagIndex
from repositories.rag_jobs import RagJobs


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
        if group.first != expected or not group.first <= group.last < start + len(window):
            raise ValueError("Диапазоны должны покрывать всё окно по порядку без пропусков.")
        blocks = window[group.first - start:group.last - start + 1]
        if len(blocks) > MAX_GROUP_BLOCKS or sum(len(block.text) for block in blocks) > MAX_GROUP_CHARS:
            raise ValueError("Не больше 10 блоков и 6000 символов на диапазон.")
        if len(blocks) > 1 and any(block.identifiers or block.kind in ("visual", "scan") for block in blocks):
            raise ValueError("Блоки с кодами и изображения должны быть отдельными.")
        tables = {block.table_id for block in blocks if block.table_id}
        if len(tables) > 1:
            raise ValueError("Одна группа не может смешивать разные таблицы.")
        members = tuple(range(group.first, group.last + 1))
        if any(not 1 <= index <= document_size for index in group.related):
            raise ValueError("Связанные ID должны существовать в документе.")
        chunks.append(Chunk(members, tuple(dict.fromkeys(
            index for index in group.related if index not in members
        ))))
        expected = group.last + 1
    if expected != start + len(window):
        raise ValueError("Последний диапазон должен достигать конца окна.")
    return chunks


class RagIngest:
    def __init__(self, jobs: RagJobs, index: RagIndex, luna: Luna):
        self.jobs = jobs
        self.index = index
        self.luna = luna

    async def worker(self, engine: AsyncEngine) -> None:
        while True:
            try:
                async with self.jobs.worker_lock(engine, self.index.key) as locked:
                    if locked:
                        while claim := await self.jobs.claim(str(uuid4()), self.index.key):
                            job, previous_attempt = claim
                            if previous_attempt:
                                await self.discard(previous_attempt)
                            await self.process(job)
            except SQLAlchemyError as error:
                log.warning("RAG queue unavailable (%s)", type(error).__name__)
            await asyncio.sleep(1)

    async def discard(self, version: str) -> None:
        try:
            await self.index.discard(version)
        except RagUnavailable:
            log.warning("RAG could not discard inactive version %s", version)

    async def process(self, job: RagJob) -> None:
        try:
            async with asyncio.timeout(1800):
                blocks = await asyncio.to_thread(extract_blocks, job.data, job.format)
                blocks = await self.enrich(blocks)
                if not blocks:
                    raise InvalidDocument("empty_document")
                chunks = await self.chunk(blocks)
                entries = [self.entry(job, blocks, chunk, index) for index, chunk in enumerate(chunks)]
                await self.index.write(job.version, entries)
        except (InvalidDocument, RagUnavailable, TimeoutError) as error:
            code = str(error) if str(error) else "import_timeout"
            log.warning("RAG import %s failed (%s)", job.id, code)
            await self.jobs.fail(job, code)
            await self.discard(job.version)
        except Exception as error:
            log.error("RAG import %s failed (%s)", job.id, type(error).__name__)
            await self.jobs.fail(job, "import_failed")
            await self.discard(job.version)
        else:
            if await self.jobs.publish(job, self.index.key, len(entries)):
                log.info("RAG import %s published %d chunks", job.id, len(entries))
            else:
                await self.discard(job.version)

    async def enrich(self, blocks: list[Block]) -> list[Block]:
        async def read(index: int, block: Block) -> list[Block]:
            if block.image is None:
                return [block]
            visual = await self.luna.read_visual(block.image, block.kind, block.label)
            location = {"page": block.page, "box": block.box, "section": block.section, "label": block.label}
            parsed = [
                replace(part, kind=block.kind)
                for part in text_blocks(visual.text, **location)
            ]
            if visual.rows:
                if not visual.columns or any(len(row.cells) != len(visual.columns) for row in visual.rows):
                    raise InvalidDocument("unreadable_visual")
                parsed.extend(table_blocks(
                    [visual.columns, *(row.cells for row in visual.rows)],
                    block.table_id or f"vision:{index}",
                    **location,
                ))
                parsed = [
                    replace(part, kind=block.kind)
                    for part in parsed
                ]
            if not parsed and (block.kind == "scan" or block.table_id):
                raise InvalidDocument("unreadable_visual")
            return parsed

        output = []
        for start in range(0, len(blocks), 8):
            results = await asyncio.gather(
                *(read(index, block) for index, block in enumerate(blocks[start:start + 8], start)),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
                output.extend(result)
        return output

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
                plan = await self.luna.plan_chunks(inputs, correction)
                try:
                    chunks = validate_plan(plan.groups, window, start + 1, len(blocks))
                except ValueError as error:
                    correction = str(error)
                else:
                    break
            else:
                raise RagUnavailable("invalid_chunk_plan")
            if end < len(blocks) and not (
                blocks[end].identifiers or blocks[end].kind in ("visual", "scan")
            ):
                cut = max(start + 1, end - TAIL_BLOCKS)
                chunks = [chunk for chunk in chunks if chunk.blocks[-1] <= cut] or chunks[:1]
            result.extend(chunks)
            start = chunks[-1].blocks[-1]
        return result

    @staticmethod
    def entry(job: RagJob, blocks: list[Block], chunk: Chunk, order: int) -> dict:
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
            })
        return {
            "source_id": job.source_id,
            "version": job.version,
            "title": job.title,
            "source_url": job.source_url,
            "format": job.format,
            "order": order,
            "identifiers": list(dict.fromkeys(identifier for block in indexed for identifier in block.identifiers)),
            "block_ids": [part["id"] for part in evidence],
            "related": [f"{job.version}:{index}" for index in chunk.related],
            "evidence": evidence,
            "search_text": "\n".join(search),
        }
