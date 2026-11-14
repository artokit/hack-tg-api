import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app


def test_users_in_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated PostgreSQL test database")
    monkeypatch.setenv("DATABASE_URL", url)
    payload = {"telegram_user_id": uuid4().int % 2**52, "username": "tester"}
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.post, "/users", json=payload)
            second = pool.submit(client.post, "/users", json=payload)
            created, repeated = first.result(), second.result()
        assert sorted([created.status_code, repeated.status_code]) == [201, 409]
        user = (created if created.status_code == 201 else repeated).json()
        assert user["telegram_user_id"] == payload["telegram_user_id"]
        assert client.get(f"/users/by-telegram-id/{payload['telegram_user_id']}").json() == user
        assert client.get("/users/by-telegram-id/-1").status_code == 404
        assert client.get(f"/users/{user['id']}").json() == user
        assert client.get("/users/9999999999").status_code == 404
        assert (
            client.post("/users", json={"telegram_user_id": 2**63}).status_code == 422
        )
