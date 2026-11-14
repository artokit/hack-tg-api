from typing import Any

import httpx

from utils.exceptions import ConfluenceTimeoutError, ConfluenceUnavailableError


class ConfluenceRepository:
    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def _get(
        self, path: str, params: dict[str, str] | None = None
    ) -> dict[str, Any] | None:
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException as error:
            raise ConfluenceTimeoutError("Confluence request timed out") from error
        except httpx.RequestError as error:
            raise ConfluenceUnavailableError("Confluence unavailable") from error

        if response.status_code == 404:
            return None
        if response.status_code in (401, 403):
            raise ConfluenceUnavailableError(
                "Confluence authentication failed or access denied"
            )
        if response.status_code == 429:
            raise ConfluenceUnavailableError("Confluence rate limit exceeded")
        if not response.is_success:
            raise ConfluenceUnavailableError("Confluence request failed")

        try:
            data = response.json()
        except ValueError as error:
            raise ConfluenceUnavailableError("Invalid response from Confluence") from error
        if not isinstance(data, dict):
            raise ConfluenceUnavailableError("Invalid response from Confluence")
        return data

    async def get_page(self, page_id: int) -> dict[str, Any] | None:
        return await self._get(
            f"api/v2/pages/{page_id}", params={"body-format": "view"}
        )

    async def get_space(self, space_id: str) -> dict[str, Any] | None:
        return await self._get(f"api/v2/spaces/{space_id}")
