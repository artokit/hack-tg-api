import asyncio
import logging
import re
from urllib.parse import parse_qs, quote, unquote, urlsplit

import httpx
from PIL import Image
from pydantic import ValidationError

from config import ConfluenceSettings
from models.rag import InvalidDocument
from repositories.confluence import ConfluenceRepository
from repositories.rag_extract import MAX_IMAGES_BYTES, HtmlImageKey, html_image_key, image_png, visible_html
from schemas.confluence import (
    ConfluencePageData,
    ConfluencePageRead,
    ConfluenceSpaceData,
)
from utils.exceptions import ConfluenceNotConfiguredError, ConfluenceTimeoutError, ConfluenceUnavailableError


log = logging.getLogger(__name__)


def attachment_reference(key: HtmlImageKey, page_id: str, by_id: dict, by_title: dict, by_media_id: dict):
    resource_id, resource_version, media_id, src = key
    try:
        uri = urlsplit(src)
    except ValueError:
        return None
    legacy = re.search(r"/download/(?:attachments|thumbnails)/([0-9]+)/([^/]+)$", uri.path)
    if legacy and legacy[1] != page_id:
        return None
    attachment = by_id.get(resource_id.removeprefix("att")) or by_media_id.get(media_id)
    if not attachment and legacy:
        attachment = by_title.get(unquote(legacy[2]))
    if not attachment:
        return None
    revision = attachment.get("version")
    versions = (resource_version, parse_qs(uri.query).get("version", [""])[0],
                str(revision.get("number") or "") if isinstance(revision, dict) else "")
    version = next((int(value) for value in versions if re.fullmatch(r"[1-9][0-9]{0,8}", value)), None)
    return str(attachment["id"]), version


class ConfluenceService:
    def __init__(self, repository: ConfluenceRepository, settings: ConfluenceSettings):
        self._repository = repository
        self._settings = settings

    async def page_images(self, page: ConfluencePageRead) -> dict[HtmlImageKey, bytes]:
        keys = list(dict.fromkeys(html_image_key(element) for element in visible_html(page.content_html).iter("img")))
        if not keys:
            return {}
        attachments = await self._repository.page_attachments(page.page_id)
        items = [
            item for item in attachments
            if re.fullmatch(r"(?:att)?[0-9]+", str(item.get("id") or ""))
            and isinstance(item.get("mediaType"), str) and item["mediaType"].startswith("image/")
        ]
        by_id = {str(item["id"]).removeprefix("att"): item for item in items}
        by_title = {item["title"]: item for item in items if isinstance(item.get("title"), str)}
        by_media_id = {item["fileId"]: item for item in items if isinstance(item.get("fileId"), str)}
        images: dict[HtmlImageKey, bytes] = {}
        downloaded: dict[tuple[str, int | None], bytes | None] = {}
        size = 0
        for key in keys:
            reference = attachment_reference(key, page.page_id, by_id, by_title, by_media_id)
            if reference is None:
                continue
            if reference not in downloaded:
                if size >= MAX_IMAGES_BYTES:
                    continue
                try:
                    data = await self._repository.attachment_image(page.page_id, *reference)
                except httpx.HTTPStatusError as error:
                    if error.response.status_code not in (404, 410):
                        raise ConfluenceUnavailableError("Confluence image download failed") from error
                    log.warning("Confluence page %s image %s removed", page.page_id, reference[0])
                    downloaded[reference] = None
                    continue
                except (httpx.TimeoutException, TimeoutError) as error:
                    raise ConfluenceTimeoutError("Confluence image request timed out") from error
                except (httpx.RequestError, OSError) as error:
                    raise ConfluenceUnavailableError("Confluence image download failed") from error
                except (InvalidDocument, KeyError):
                    log.warning("Confluence page %s image %s unavailable", page.page_id, reference[0])
                    downloaded[reference] = None
                    continue
                try:
                    png = await asyncio.to_thread(image_png, data)
                    downloaded[reference] = png if size + len(png) <= MAX_IMAGES_BYTES else None
                    if downloaded[reference] is not None:
                        size += len(png)
                except (OSError, Image.DecompressionBombError):
                    log.warning("Confluence page %s image %s unavailable", page.page_id, reference[0])
                    downloaded[reference] = None
            image = downloaded[reference]
            if image is not None:
                images[key] = image
        return images

    async def get_page(self, space_id: str, page_id: int) -> ConfluencePageRead:
        if (
            not self._settings.confluence_email.strip()
            or not self._settings.confluence_api_token.get_secret_value()
        ):
            raise ConfluenceNotConfiguredError("Confluence credentials are not configured")

        data = await self._repository.get_page(page_id)
        if data is None:
            raise LookupError("Confluence page not found")
        try:
            page = ConfluencePageData.model_validate(data)
        except ValidationError as error:
            raise ConfluenceUnavailableError("Invalid response from Confluence") from error

        space_data = await self._repository.get_space(page.space_id)
        if space_data is None:
            raise LookupError("Confluence space not found")
        try:
            space = ConfluenceSpaceData.model_validate(space_data)
        except ValidationError as error:
            raise ConfluenceUnavailableError("Invalid response from Confluence") from error

        if space.id != page.space_id:
            raise ConfluenceUnavailableError("Invalid response from Confluence")
        if space_id not in (space.id, space.key):
            raise LookupError("Confluence page not found in this space")

        base_url = self._settings.confluence_base_url.rstrip("/")
        return ConfluencePageRead(
            page_id=page.id,
            space_id=space.id,
            space_key=space.key,
            title=page.title,
            status=page.status,
            content_html=page.body.view.value,
            version=page.version.number,
            updated_at=page.version.created_at,
            url=f"{base_url}/spaces/{quote(space.key, safe='')}/pages/{page.id}",
        )
