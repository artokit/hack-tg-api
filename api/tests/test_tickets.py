import asyncio
import os
from unittest.mock import AsyncMock

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from main import app
from schemas.ticket import TicketRead
from tickets.jsm import TicketSystemError


def test_migrations_have_one_head():
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_heads() == ["0006"]
    assert len(list(scripts.walk_revisions())) == 6


def test_ticket_schema_has_no_external_keys():
    assert not {"external_id", "display_key"}.intersection(TicketRead.model_fields)
    assert list(app.openapi()["paths"]["/tickets"]) == ["post"]


def test_create_ticket_in_postgres(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated PostgreSQL test database")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("JWT_SECRET", "test-only-" + "x" * 32)
    adapter = AsyncMock()
    monkeypatch.setattr("services.ticket_service.build_adapter", lambda route: adapter)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        response = client.post(
            "/tickets", json={"title": "Filter broken", "description": "No results"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Filter broken"
        assert not {"external_id", "display_key"}.intersection(data)
        adapter.create.assert_awaited_once()
        adapter.create.side_effect = TicketSystemError("Unavailable")
        assert client.post(
            "/tickets", json={"title": "Another issue", "description": "Failure"}
        ).status_code == 502
        assert client.post("/tickets", json={"title": "x"}).status_code == 422

    async def check_saved():
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                title = await connection.scalar(
                    text("SELECT title FROM tickets WHERE id = :id"), {"id": data["id"]}
                )
                assert title == "Filter broken"
        finally:
            await engine.dispose()

    asyncio.run(check_saved())
