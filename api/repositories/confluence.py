from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from repositories.rag_files import read_document
from repositories.rag_urls import public_address
from utils.exceptions import ConfluenceTimeoutError, ConfluenceUnavailableError


class ConfluenceRepository:
    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def _get(
        self, path: str, params: dict[str, str] | None = None
    ) -> tuple[dict[str, Any] | None, str | None]:
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException as error:
            raise ConfluenceTimeoutError("Confluence request timed out") from error
        except httpx.RequestError as error:
            raise ConfluenceUnavailableError("Confluence unavailable") from error

        if response.status_code == 404:
            return None, None
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
        return data, response.links.get("next", {}).get("url")

    async def get_page(self, page_id: int) -> dict[str, Any] | None:
        page, _ = await self._get(
            f"api/v2/pages/{page_id}", params={"body-format": "view"}
        )
        return page

    async def get_space(self, space_id: str) -> dict[str, Any] | None:
        space, _ = await self._get(f"api/v2/spaces/{space_id}")
        return space

    async def page_attachments(self, page_id: str) -> list[dict[str, Any]]:
        attachments: list[dict[str, Any]] = []
        params = {"limit": "100", "status": "current"}
        seen = set()
        while True:
            page, next_link = await self._get(f"api/v2/pages/{page_id}/attachments", params)
            if page is None:
                return attachments
            items = page.get("results")
            if not isinstance(items, list):
                raise ConfluenceUnavailableError("Invalid attachment list")
            attachments.extend(item for item in items if isinstance(item, dict))
            links = page.get("_links")
            next_url = next_link or (links.get("next") if isinstance(links, dict) else None)
            if not next_url:
                return attachments
            if not isinstance(next_url, str):
                raise ConfluenceUnavailableError("Invalid attachment cursor")
            cursor = parse_qs(urlsplit(next_url).query).get("cursor", [""])[0]
            if not cursor or cursor in seen:
                raise ConfluenceUnavailableError("Invalid attachment cursor")
            seen.add(cursor)
            params["cursor"] = cursor

    async def attachment_image(self, page_id: str, attachment_id: str, version: int | None) -> bytes:
        path = f"rest/api/content/{page_id}/child/attachment/{attachment_id}/download"
        headers = {"Accept": "image/*, application/octet-stream", "Accept-Encoding": "identity"}
        params = {"version": str(version)} if version else None
        async with self._client.stream("GET", path, params=params, headers=headers, follow_redirects=False) as response:
            if not response.is_redirect:
                response.raise_for_status()
                return await read_document(response)
            url = response.url.join(response.headers["location"])
        if url.scheme != "https":
            raise ConfluenceUnavailableError("Invalid attachment CDN URL")
        address = await public_address(url)
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            async with client.stream(
                "GET", url.copy_with(host=address),
                headers={**headers, "Host": url.raw_host.decode("ascii")},
                extensions={"sni_hostname": url.raw_host.decode("ascii")},
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                return await read_document(response)
