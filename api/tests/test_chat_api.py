import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

import main

HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture
def configure_api(monkeypatch: pytest.MonkeyPatch) -> None:
    test_url = os.environ.get("TEST_DATABASE_URL")
    if not test_url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated PostgreSQL test database")
    for name, value in {
        "DATABASE_URL": test_url,
        "AGENT_API_TOKEN": "test-token",
        "CHAT_BASE_URL": "http://127.0.0.1:1/v1",
        "CHAT_MODEL": "test",
        "CHAT_CONTEXT_WINDOW": "8192",
    }.items():
        monkeypatch.setenv(name, value)


def chat(client: TestClient, user: int, text: str):
    return client.post(
        "/agent/chat", headers=HEADERS, json={"telegram_user_id": user, "text": text}
    )


def reset(client: TestClient, user: int):
    return client.post("/agent/reset", headers=HEADERS, json={"telegram_user_id": user})


def test_conversation_lifecycle(configure_api, monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release = Event(), Event()

    def reply(messages, info):
        prompts = [
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        ]
        if prompts[-1] == "error":
            raise UnexpectedModelBehavior("test failure")
        if prompts[-1] == "wait":
            entered.set()
            assert release.wait(timeout=10)
        return ModelResponse(parts=[TextPart(" / ".join(prompts))])

    monkeypatch.setattr(
        main, "build_agent", lambda settings, client: Agent(FunctionModel(reply))
    )
    with TestClient(main.app) as client:
        assert reset(client, 10001).status_code == 204
        assert reset(client, 10002).status_code == 204
        payload = {"telegram_user_id": 10001, "text": "  "}
        assert client.post("/agent/chat", json=payload).status_code == 401
        assert (
            client.post("/agent/chat", headers=HEADERS, json=payload).status_code == 422
        )
        assert chat(client, 10001, "первый").json() == {"answer": "первый"}
        assert chat(client, 10002, "чужой").json() == {"answer": "чужой"}
        assert chat(client, 10001, "error").status_code == 503
        user_data = {"telegram_user_id": 10001, "username": "tester"}
        user = client.post("/users", json=user_data).json()
        assert client.post("/users", json=user_data).json() == user
        assert client.get(f"/users/{user['id']}").json() == user
        assert client.get("/users/9999999999").status_code == 404
        assert (
            client.post("/users", json={"telegram_user_id": 2**63}).status_code == 422
        )

    with TestClient(main.app) as client:
        assert chat(client, 10001, "после перезапуска").json() == {
            "answer": "первый / после перезапуска"
        }
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(chat, client, 10001, "wait")
            try:
                assert entered.wait(timeout=5)
                assert chat(client, 10001, "second").status_code == 409
                assert reset(client, 10001).status_code == 409
                assert chat(client, 10002, "parallel").status_code == 200
            finally:
                release.set()
            assert pending.result(timeout=5).status_code == 200
        assert reset(client, 10001).status_code == 204
        assert chat(client, 10001, "новый").json() == {"answer": "новый"}


def test_steer_joins_the_active_turn(
    configure_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = Event(), Event()
    calls = 0

    async def reply(messages, _info):
        nonlocal calls
        calls += 1
        prompts = [
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        ]
        if calls == 1:
            assert prompts == ["Исходный вопрос"]
            entered.set()
            assert await asyncio.to_thread(release.wait, 10)
            return ModelResponse(parts=[TextPart("Промежуточный ответ")])
        assert prompts == ["Исходный вопрос", "Только три пункта"]
        return ModelResponse(parts=[TextPart("Итог с уточнением")])

    monkeypatch.setattr(
        main,
        "build_agent",
        lambda settings, client: Agent(FunctionModel(reply)),
    )
    user_id = 10003
    data = {
        "telegram_user_id": user_id,
        "turn_id": str(uuid4()),
        "text": "Исходный вопрос",
    }
    with TestClient(main.app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        assert reset(client, user_id).status_code == 204
        pending = pool.submit(
            client.post, "/agent/chat/stream", headers=HEADERS, json=data
        )
        try:
            assert entered.wait(timeout=5)
            assert (
                client.post(
                    "/agent/chat/steer",
                    headers=HEADERS,
                    json={
                        **data,
                        "turn_id": str(uuid4()),
                        "text": "Чужой ход",
                    },
                ).status_code
                == 409
            )
            assert (
                client.post(
                    "/agent/chat/steer",
                    headers=HEADERS,
                    json={
                        **data,
                        "telegram_user_id": 10004,
                        "text": "Чужой пользователь",
                    },
                ).status_code
                == 409
            )
            assert (
                client.post(
                    "/agent/chat/steer",
                    headers=HEADERS,
                    json={
                        **data,
                        "text": "Только три пункта",
                    },
                ).status_code
                == 202
            )
            assert calls == 1
        finally:
            release.set()
        response = pending.result(timeout=10)
        assert response.headers["Content-Type"].startswith("text/event-stream")
        events = [
            (
                lines[0].removeprefix("event: "),
                json.loads(lines[1].removeprefix("data: ")),
            )
            for frame in response.text.split("\n\n")
            if (lines := frame.splitlines()) and lines[0].startswith("event: ")
        ]
        assert [kind for kind, _ in events] == ["ready", "answer"]
        assert events[-1] == ("answer", "Итог с уточнением")
        assert (
            client.post("/agent/chat/steer", headers=HEADERS, json=data).status_code
            == 409
        )

        def read_snapshot(messages, _info):
            prompts = [
                part.content
                for message in messages
                for part in message.parts
                if isinstance(part, UserPromptPart)
            ]
            assert prompts == [
                "Исходный вопрос",
                "Только три пункта",
                "Следующий вопрос",
            ]
            return ModelResponse(parts=[TextPart("Снимок сохранён")])

        agent = main.app.state.chat_service.agent
        with agent.override(model=FunctionModel(read_snapshot)):
            assert chat(client, user_id, "Следующий вопрос").json() == {
                "answer": "Снимок сохранён"
            }
        assert reset(client, user_id).status_code == 204
