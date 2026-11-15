from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from depends import get_github_service, require_bot_token
from models.rag import RagQueueUnavailable
from services.github import GithubService


router = APIRouter(tags=["github"])


@router.post(
    "/internal/rag/github/sync", status_code=202, response_class=Response, dependencies=[Depends(require_bot_token)],
)
async def sync_github(
    service: Annotated[GithubService, Depends(get_github_service)],
) -> Response:
    try:
        await service.request_sync()
    except RagQueueUnavailable as error:
        raise HTTPException(status_code=503, detail="RAG queue unavailable") from error
    return Response(status_code=202)
