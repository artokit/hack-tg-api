import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models import Employee, Invite
from main import app
from repositories.invites import InviteRepository


def test_private_invite_and_employee_lookup(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated PostgreSQL test database")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("JWT_SECRET", "test-only-" + "x" * 32)
    token = "test-only-" + "x" * 32
    monkeypatch.setenv("BOT_API_TOKEN", token)
    asyncio.run(check_invite_and_employee_lookup(url, token))


async def check_invite_and_employee_lookup(url: str, token: str):
    headers = {"X-Bot-Token": token}
    ids = (3120000001, 3120000002)
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    invite_id: UUID | None = None
    try:
        async with sessions() as session:
            invite = await InviteRepository(session).create(1, None, None)
            invite_id = invite.id
        with TestClient(app) as client:
            path = f"/private/invites/{invite_id}/accept"
            lookup = "/private/employees/by-telegram-id"
            assert client.get(f"{lookup}/{ids[0]}").status_code == 401
            assert client.get(f"{lookup}/{ids[0]}", headers=headers).status_code == 404

            def accept(telegram_id):
                return client.post(
                    path, headers=headers, json={"telegram_id": telegram_id, "first_name": "Иван"}
                )

            with ThreadPoolExecutor(max_workers=2) as workers:
                responses = list(workers.map(accept, ids))
            assert sorted(response.status_code for response in responses) == [201, 404]
            winner = next(response.json() for response in responses if response.status_code == 201)
            telegram_id = winner["telegram_id"]
            employee = client.get(f"{lookup}/{telegram_id}", headers=headers)
            assert employee.status_code == 200
            assert employee.json()["first_name"] == "Иван"
            async with sessions() as session:
                await session.execute(delete(Employee).where(Employee.telegram_id == telegram_id))
                await session.commit()
            assert client.get(f"{lookup}/{telegram_id}", headers=headers).status_code == 404
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(Employee).where(Employee.telegram_id.in_(ids)))
            if invite_id is not None:
                await connection.execute(delete(Invite).where(Invite.id == invite_id))
        await engine.dispose()
