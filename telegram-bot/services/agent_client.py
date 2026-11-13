import httpx


class AgentClient:
    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}

    async def reply(self, telegram_user_id: int, text: str) -> str:
        response = await self.client.post(
            "agent/chat",
            json={"telegram_user_id": telegram_user_id, "text": text},
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()["answer"]

    async def reset(self, telegram_user_id: int) -> None:
        response = await self.client.post(
            "agent/reset",
            json={"telegram_user_id": telegram_user_id},
            headers=self.headers,
        )
        response.raise_for_status()
