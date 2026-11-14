import asyncio
import os
import threading
import time
from base64 import b64encode
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from docx import Document
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from PIL import Image

from agents.rag import CitationSelection, ChunkPlan, FactCheck, ProposedFact, QueryPlan, VisualReading
from db.models import RagJob
from main import app
from models.rag import Block, Chunk, RagUnavailable
from repositories.rag_extract import extract_blocks
from repositories.rag_index import RagIndex
from services.rag import RagService
from services.rag_ingest import RagIngest


CODES = ("MS-2.11-002", "MS-2.11-004")
SERVICE_TOKEN = "test-only-rag-token-for-local-verification"
HEADERS = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
SOURCE = (
    "# Демографические группы\n"
    "| ID | Действие |\n| --- | --- |\n"
    "| MS-2.11-002 | Измеряйте качество работы системы по группам. |\n"
    "| MS-2.11-004 | Оцените охват подгрупп в обучающих данных. |\n"
)


def test_rag_migration_follows_invites():
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_revision("0008").down_revision == "0007"


def test_word_and_markdown_keep_table_identity_and_visuals():
    document = Document()
    document.add_heading("Правила", level=1)
    document.add_paragraph("Проверьте настройки.")
    table = document.add_table(rows=2, cols=2)
    for row, values in zip(table.rows, [("Описание", "Код"), ("Включите фильтр", CODES[0])]):
        for cell, value in zip(row.cells, values):
            cell.text = value
    image = BytesIO()
    Image.new("RGB", (160, 80), "white").save(image, "PNG")
    document.add_picture(BytesIO(image.getvalue()))
    buffer = BytesIO()
    document.save(buffer)
    word = extract_blocks(buffer.getvalue(), "docx")
    assert [block.kind for block in word] == ["heading", "text", "table_row", "visual"]
    assert word[2].section == ("Правила",)
    assert word[2].identifiers == (CODES[0],)
    assert word[3].image.startswith(b"\x89PNG")
    markdown = extract_blocks((SOURCE + "\n[Оригинал](https://example.com/)").encode(), "md")
    assert [block.identifiers for block in markdown if block.kind == "table_row"] == [(code,) for code in CODES]
    assert markdown[-1].text == "[Оригинал](https://example.com/)"
    inline_image = b64encode(image.getvalue()).decode()
    section = extract_blocks(
        f"## {CODES[0]}\n\nВключите проверку.\n\n![Схема](data:image/png;base64,{inline_image})".encode(),
        "md",
    )
    assert section[1].identifiers == (CODES[0],)
    assert section[-1].image.startswith(b"\x89PNG")
    assert all("base64" not in block.text for block in section)


def test_semantic_plan_carries_tail_across_page_boundary():
    class Planner:
        async def plan_chunks(self, blocks, correction):
            groups = []
            for block in blocks:
                index = block["id"]
                if index == 29:
                    groups.append({"first": index, "last": index + 1})
                elif index != 30:
                    groups.append({"first": index, "last": index})
            return ChunkPlan.model_validate({"groups": groups})

    blocks = [Block("text", f"Блок {index}", page=9 if index < 30 else 10) for index in range(1, 40)]
    chunks = asyncio.run(RagIngest(None, None, Planner()).chunk(blocks))
    assert [index for chunk in chunks for index in chunk.blocks] == list(range(1, 40))
    assert (29, 30) in [chunk.blocks for chunk in chunks]


class FixtureLuna:
    saw_image = False
    saw_sources = None
    incorrect_quote = False
    wrong_fact = False

    async def read_visual(self, image, kind, context):
        self.saw_image = True
        return VisualReading(text="Календарь справа под блоком «Местное время».")

    async def plan_chunks(self, blocks, correction):
        groups = [{"first": block["id"], "last": block["id"]} for block in blocks]
        return ChunkPlan.model_validate({"groups": groups})

    async def plan_query(self, question, standalone, codes):
        if " и что " in question:
            parts = [{"question": "Что измерять в работе системы?"}, {"question": "Что видно в обучающих данных?"}]
        else:
            parts = [{"question": standalone or question, "exact_id": codes[0] if codes else None}]
        return QueryPlan.model_validate({"parts": parts})

    async def propose(self, question, sources):
        self.saw_sources = sources
        is_visual = "календарь" in question.lower()
        code = CODES[1] if "обучающих" in question else CODES[0]
        source = next(
            (
                item for item in sources
                if (
                    item["kind"] in ("visual", "scan") and "Календарь" in item["text"]
                    if is_visual else code in item["identifiers"]
                )
            ),
            None,
        )
        if source is None:
            return ProposedFact(status="unsupported")
        statement = "Ложное утверждение" if self.wrong_fact else source["text"]
        return ProposedFact(status="supported", statement=statement, evidence_ids=[source["id"]])

    async def verify(self, question, statement, sources, original_question):
        if self.wrong_fact:
            return FactCheck(supported=False)
        item = sources[0]
        quote = "Выдуманная цитата" if self.incorrect_quote else item["text"]
        return FactCheck(
            supported=True,
            citations=[CitationSelection(id=item["id"], quote=quote if item["kind"] == "table_row" else None)],
        )

    async def close(self):
        pass


def test_exact_match_filters_out_neighbor_and_rejects_wrong_quote():
    class Jobs:
        async def active_versions(self, key):
            return ["a"]

    source = RagJob(source_id="nist", version="a", title="NIST", format="md")
    blocks = [block for block in extract_blocks(SOURCE.encode(), "md") if block.identifiers]
    chunks = [RagIngest.entry(source, blocks, Chunk((i + 1,), ()), i) for i in range(2)]

    class Index:
        key = "test"

        async def exact(self, identifier, version):
            return chunks if identifier == CODES[0] else []

    luna = FixtureLuna()
    service = RagService(Jobs(), Index(), luna)
    question = f"Что рекомендует {CODES[0]}?"
    answer = asyncio.run(service.answer(question, None))
    assert answer.status == "answered"
    assert [item["identifiers"] for item in luna.saw_sources] == [[CODES[0]]]
    assert answer.sources[0].quote == blocks[0].text
    followup = asyncio.run(service.answer("А что рекомендует этот пункт?", question))
    assert followup.status == "answered"
    assert followup.sources[0].quote == blocks[0].text
    luna.wrong_fact = True
    assert asyncio.run(service.answer(question, None)).status == "not_found"
    luna.wrong_fact = False
    luna.incorrect_quote = True
    assert asyncio.run(service.answer(question, None)).status == "not_found"


def wait_job(client, job_id):
    for _ in range(120):
        response = client.get(f"/internal/rag/jobs/{job_id}", headers=HEADERS)
        assert response.status_code == 200
        result = response.json()
        if result["status"] in ("succeeded", "failed"):
            return result
        time.sleep(0.1)
    pytest.fail("Import job did not finish")


def test_rag_routes_publish_only_verified_versions(monkeypatch):
    database = os.environ.get("TEST_DATABASE_URL")
    qdrant = os.environ.get("TEST_RAG_QDRANT_URL")
    if not database or not qdrant:
        pytest.skip("Set TEST_DATABASE_URL and TEST_RAG_QDRANT_URL")
    for key, value in {
        "DATABASE_URL": database, "RAG_ENABLED": "true", "RAG_SERVICE_TOKEN": SERVICE_TOKEN,
        "RAG_QDRANT_URL": qdrant, "RAG_COLLECTION": "test_rag_" + uuid4().hex,
        "RAG_EMBEDDING_BASE_URL": "http://127.0.0.1:2/v1",
        "RAG_LUNA_BASE_URL": "http://127.0.0.1:2/v1",
    }.items():
        monkeypatch.setenv(key, value)
    example = FixtureLuna()
    monkeypatch.setattr("lifespan.Luna", lambda _: example)

    async def vectors(self, inputs):
        return [[1.0] + [0.0] * 4095 for _ in inputs]

    monkeypatch.setattr(RagIndex, "vectors", vectors)
    with TestClient(app) as client:
        endpoint = "/internal/rag"
        metadata = {"source_id": "nist", "title": "NIST", "source_url": "https://example.com/nist"}
        assert client.post(endpoint + "/answer", json={"question": "Что нового?"}).status_code == 401
        upload = client.post(
            endpoint + "/documents", headers=HEADERS, data=metadata,
            files={"file": ("source.md", SOURCE.encode(), "text/markdown")},
        )
        assert upload.status_code == 202
        good = wait_job(client, upload.json()["job_id"])
        assert good["status"] == "succeeded", good
        assert client.get(endpoint + "/jobs/" + str(uuid4()), headers=HEADERS).status_code == 404
        assert client.post(
            endpoint + "/documents", headers=HEADERS, data=metadata, files={"file": ("source.txt", b"x")}
        ).status_code == 415

        img = BytesIO()
        Image.new("RGB", (160, 90), "white").save(img, "PNG")
        word = Document()
        word.add_heading("Календарь", level=1)
        word.add_picture(BytesIO(img.getvalue()))
        docx = BytesIO()
        word.save(docx)
        for filename, data in [
            ("calendar.docx", docx.getvalue()),
            ("calendar.pdf", make_scan()),
        ]:
            uploaded = client.post(
                endpoint + "/documents", headers=HEADERS,
                data={**metadata, "source_id": filename, "title": filename},
                files={"file": (filename, data)},
            )
            assert uploaded.status_code == 202
            state = wait_job(client, uploaded.json()["job_id"])
            assert state["status"] == "succeeded", state
        assert example.saw_image

        def ask(question):
            response = client.post(endpoint + "/answer", headers=HEADERS, json={"question": question})
            assert response.status_code == 200
            return response.json()

        assert CODES[0] in ask(f"Что рекомендует {CODES[0]}?")["sources"][0]["quote"]
        assert CODES[1] in ask(f"Что рекомендует {CODES[1]} про обучающих данных?")["sources"][0]["quote"]
        assert ask("Что рекомендует MS-2.11-999?")["status"] == "not_found"
        combined = ask("Что измерять в работе системы и что видно в обучающих данных?")
        assert combined["status"] == "answered"
        assert all(code in quote for code, quote in zip(CODES, [s["quote"] for s in combined["sources"]]))
        calendar = ask("Где календарь?")
        assert calendar["status"] == "answered"
        assert calendar["sources"][0]["visual"] is True
        assert calendar["sources"][0]["quote"] is None
        if trip_file := os.environ.get("TEST_RAG_TRIP_PDF"):
            trip = client.post(
                endpoint + "/documents", headers=HEADERS,
                data={**metadata, "source_id": "trip", "title": "Командировка"},
                files={"file": ("trip.pdf", Path(trip_file).read_bytes(), "application/pdf")},
            )
            assert trip.status_code == 202
            trip_status = wait_job(client, trip.json()["job_id"])
            assert trip_status["status"] == "succeeded", trip_status
        write = RagIndex.write

        async def fail_after_write(self, version, entries):
            await write(self, version, entries)
            raise RagUnavailable("index_verification_failed")

        monkeypatch.setattr(RagIndex, "write", fail_after_write)
        upload = client.post(
            endpoint + "/documents", headers=HEADERS, data=metadata,
            files={"file": ("source.md", SOURCE.replace("качество", "новую метрику").encode())},
        )
        rejected = wait_job(client, upload.json()["job_id"])
        assert rejected["status"] == "failed"
        assert "качество" in ask(f"Что рекомендует {CODES[0]}?")["sources"][0]["quote"]


def make_scan() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (420, 250), "lightblue").save(buffer, "PDF")
    return buffer.getvalue()


def test_job_can_resume_after_api_restart(monkeypatch):
    database = os.environ.get("TEST_DATABASE_URL")
    qdrant = os.environ.get("TEST_RAG_QDRANT_URL")
    if not database or not qdrant:
        pytest.skip("Set TEST_DATABASE_URL and TEST_RAG_QDRANT_URL")
    for key, value in {
        "DATABASE_URL": database, "RAG_ENABLED": "true", "RAG_SERVICE_TOKEN": SERVICE_TOKEN,
        "RAG_QDRANT_URL": qdrant, "RAG_COLLECTION": "test_rag_" + uuid4().hex,
        "RAG_EMBEDDING_BASE_URL": "http://127.0.0.1:2/v1",
        "RAG_LUNA_BASE_URL": "http://127.0.0.1:2/v1",
    }.items():
        monkeypatch.setenv(key, value)
    invoked = threading.Event()
    first_worker = True

    class InterruptedPlanner(FixtureLuna):
        async def plan_chunks(self, blocks, correction):
            if first_worker:
                invoked.set()
                await asyncio.Event().wait()
            return await super().plan_chunks(blocks, correction)

    async def vectors(self, inputs):
        return [[1.0] + [0.0] * 4095 for _ in inputs]

    monkeypatch.setattr("lifespan.Luna", lambda _: InterruptedPlanner())
    monkeypatch.setattr(RagIndex, "vectors", vectors)
    with TestClient(app) as client:
        response = client.post(
            "/internal/rag/documents", headers=HEADERS,
            data={"source_id": "restart", "title": "Restart"},
            files={"file": ("restart.md", b"# First section\n\nA statement about a restart.\n")},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert invoked.wait(timeout=8)
        running = client.get(f"/internal/rag/jobs/{job_id}", headers=HEADERS).json()
        assert running["status"] == "running"
    first_worker = False
    with TestClient(app) as client:
        finished = wait_job(client, job_id)
        assert finished["status"] == "succeeded", finished
        assert finished["version"] != running["version"]


def test_trip_pdf_preserves_budget_rule_and_table_regions():
    trip_file = os.environ.get("TEST_RAG_TRIP_PDF")
    if not trip_file:
        pytest.skip("Set TEST_RAG_TRIP_PDF to the hackathon fixture")
    blocks = extract_blocks(Path(trip_file).read_bytes(), "pdf")
    page9 = [block.text for block in blocks if block.page == 9]
    page10 = [block.text for block in blocks if block.page == 10]
    assert any("остаток по" in block for block in page9)
    assert any("билетам меньше 1000 руб." in block for block in page10)
    tables = [block for block in blocks if block.page == 10 and block.table_id]
    assert len({block.table_id for block in tables}) == 2
    assert any("бюджету сделки" in block.label for block in tables)
    assert any("бюджету подразделения" in block.label for block in tables)
