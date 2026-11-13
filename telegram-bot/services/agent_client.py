import json
from collections.abc import AsyncIterator
from uuid import UUID

import httpx


class AgentStreamError(Exception):
    pass


class AgentClient:
    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}

    async def stream(
        self, user_id: int, turn_id: UUID, text: str
    ) -> AsyncIterator[tuple[str, str]]:
        async with self.client.stream(
            "POST",
            "agent/chat/stream",
            json={"telegram_user_id": user_id, "turn_id": str(turn_id), "text": text},
            headers=self.headers,
        ) as response:
            response.raise_for_status()
            kind = ""
            text = ""
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    kind = line.removeprefix("event: ")
                elif line.startswith("data: "):
                    try:
                        value = json.loads(line.removeprefix("data: "))
                    except ValueError:
                        raise AgentStreamError("invalid event") from None
                    if not isinstance(value, str):
                        raise AgentStreamError("invalid event payload")
                    text = value
                elif not line and kind:
                    yield kind, text
                    kind, text = "", ""

    async def steer(self, user_id: int, turn_id: UUID, text: str) -> bool:
        response = await self.client.post(
            "agent/chat/steer",
            json={"telegram_user_id": user_id, "turn_id": str(turn_id), "text": text},
            headers=self.headers,
        )
        if response.status_code == 409:
            return False
        response.raise_for_status()
        return True

    async def reset(self, telegram_user_id: int) -> None:
        response = await self.client.post(
            "agent/reset",
            json={"telegram_user_id": telegram_user_id},
            headers=self.headers,
        )
        response.raise_for_status()
