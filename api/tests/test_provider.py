import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic_ai import ConversationTypeAdapter

from agents import support
from config import Settings


@pytest.mark.parametrize("api_key", [None, "configured-key"])
def test_openai_compatible_chat(
    api_key: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "OPENAI_CUSTOM_HEADERS", "Authorization: Bearer ambient\nX-Ambient: secret"
    )
    monkeypatch.setenv("OPENAI_ORG_ID", "unrelated-org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "unrelated-project")
    headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
    sent = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers.get("authorization") == headers.get("authorization")
        for header in ("X-Ambient", "OpenAI-Organization", "OpenAI-Project"):
            assert header not in request.headers
        payload = json.loads(request.content)
        assert payload["model"] == "bars-local"
        assert "tools" not in payload
        sent.append(payload["messages"])
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "bars-local",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Маяк"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    def build_client(**kwargs) -> AsyncOpenAI:
        return AsyncOpenAI(
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
            **kwargs,
        )

    monkeypatch.setattr(support, "AsyncOpenAI", build_client)
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://127.0.0.1/test",
        agent_api_token="test",
        chat_model="bars-local",
        chat_base_url="http://127.0.0.1:9101/v1",
        chat_api_key=api_key,
        chat_context_window=8192,
    )

    async def scenario() -> None:
        async with support.build_model_client(settings) as client:
            agent = support.build_agent(settings, client)
            result = await agent.run("Проект называется Маяк")
            saved = ConversationTypeAdapter.dump_json(result.conversation)
            previous = ConversationTypeAdapter.validate_json(saved)
            second = await agent.run("Как называется проект?", conversation=previous)
            assert second.output == "Маяк"

    asyncio.run(scenario())
    assert len(sent) == 2
    assert {"role": "user", "content": "Проект называется Маяк"} in sent[1]
