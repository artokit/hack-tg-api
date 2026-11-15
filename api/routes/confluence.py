from fastapi import APIRouter, Depends, HTTPException, Query

from depends import get_confluence_service, require_bot_token
from schemas.confluence import ConfluencePageRead
from services.confluence import ConfluenceService
from utils.exceptions import (
    ConfluenceNotConfiguredError,
    ConfluenceTimeoutError,
    ConfluenceUnavailableError,
)

router = APIRouter(
    prefix="/confluence",
    tags=["confluence"],
    dependencies=[Depends(require_bot_token)],
)


@router.get(
    "/pages",
    response_model=ConfluencePageRead,
    responses={
        401: {"description": "Invalid or missing bot token"},
        404: {"description": "Page not found in the specified space"},
        502: {"description": "Confluence request failed"},
        503: {"description": "Confluence credentials are not configured"},
        504: {"description": "Confluence request timed out"},
    },
)
async def get_page(
    space_id: str = Query(
        min_length=1,
        max_length=255,
        pattern=r"^\S+$",
        description="Numeric space ID or space key from the Confluence URL",
    ),
    page_id: int = Query(gt=0),
    service: ConfluenceService = Depends(get_confluence_service),
) -> ConfluencePageRead:
    try:
        return await service.get_page(space_id, page_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConfluenceNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ConfluenceTimeoutError as error:
        raise HTTPException(status_code=504, detail=str(error)) from error
    except ConfluenceUnavailableError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
