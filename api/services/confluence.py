from urllib.parse import quote

from pydantic import ValidationError

from config import ConfluenceSettings
from repositories.confluence import ConfluenceRepository
from schemas.confluence import (
    ConfluencePageData,
    ConfluencePageRead,
    ConfluenceSpaceData,
)
from utils.exceptions import ConfluenceNotConfiguredError, ConfluenceUnavailableError


class ConfluenceService:
    def __init__(self, repository: ConfluenceRepository, settings: ConfluenceSettings):
        self._repository = repository
        self._settings = settings

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
