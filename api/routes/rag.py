from pathlib import PurePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import AnyHttpUrl

from depends import get_current_user, get_rag_service, require_bot_token
from models.rag import RagUnavailable
from schemas.rag import RagEvidenceRead, RagJobCreated, RagJobRead, RagSearchRequest
from services.rag import RagService, UnexpectedDocumentId


router = APIRouter(tags=["rag"])
Service = Annotated[RagService, Depends(get_rag_service)]
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.post(
    "/rag/documents", response_model=RagJobCreated, status_code=202, dependencies=[Depends(get_current_user)],
)
async def upload_document(
    service: Service,
    file: UploadFile,
    source_id: Annotated[str, Form(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_./:\-]+$")],
    title: Annotated[str, Form(min_length=1, max_length=250)],
    source_url: Annotated[AnyHttpUrl | None, Form()] = None,
):
    format = PurePath(file.filename or "").suffix.lower().removeprefix(".")
    limit = MAX_UPLOAD_BYTES
    try:
        if format not in {"pdf", "docx", "md"}:
            raise HTTPException(status_code=415, detail="Use a PDF, DOCX or Markdown file")
        if not title.strip() or source_url and (source_url.username or source_url.password):
            raise HTTPException(status_code=422, detail="Invalid source metadata")
        if file.size is not None and file.size > limit:
            raise HTTPException(status_code=413, detail="Document is too large")
        data = await file.read(limit + 1)
    finally:
        await file.close()
    if len(data) > limit:
        raise HTTPException(status_code=413, detail="Document is too large")
    if not data:
        raise HTTPException(status_code=422, detail="Document is empty")
    try:
        job_id = await service.submit(source_id, title.strip(), str(source_url) if source_url else None, format, data)
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="Document upload temporarily unavailable") from error
    return RagJobCreated(job_id=job_id)


@router.get("/rag/jobs/{job_id}", response_model=RagJobRead, dependencies=[Depends(get_current_user)])
async def read_job(job_id: UUID, service: Service):
    try:
        job = await service.read_job(job_id)
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="Import status temporarily unavailable") from error
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job


@router.post(
    "/internal/rag/search", response_model=list[RagEvidenceRead], dependencies=[Depends(require_bot_token)],
)
async def search(query: RagSearchRequest, service: Service):
    try:
        return await service.search(query.question, query.exact_id, query.original_question)
    except UnexpectedDocumentId as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="Document search temporarily unavailable") from error
