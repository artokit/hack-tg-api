from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import ValidationError

from depends import get_github_service
from models.rag import RagQueueUnavailable
from schemas.github import GithubDelivery
from services.github import GithubService


router = APIRouter(tags=["github"])
MAX_WEBHOOK_BYTES = 25 * 1024 * 1024


@router.post("/webhooks/github", status_code=202, responses={204: {"description": "Event ignored"}})
async def github_webhook(
    request: Request,
    service: Annotated[GithubService, Depends(get_github_service)],
    x_hub_signature_256: Annotated[str | None, Header()] = None,
    x_github_event: Annotated[str | None, Header()] = None,
) -> Response:
    if not x_hub_signature_256 or len(x_hub_signature_256) != 71:
        raise HTTPException(status_code=401, detail="Invalid GitHub signature")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_WEBHOOK_BYTES:
            raise HTTPException(status_code=413, detail="GitHub payload too large")
        body.extend(chunk)
    if not service.verify(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid GitHub signature")
    if x_github_event not in ("ping", "push"):
        return Response(status_code=204)
    try:
        delivery = GithubDelivery.model_validate_json(body)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="Invalid GitHub payload") from error
    try:
        accepted = await service.accept(x_github_event, delivery)
    except RagQueueUnavailable as error:
        raise HTTPException(status_code=503, detail="RAG queue unavailable") from error
    return Response(status_code=202 if accepted else 204)
