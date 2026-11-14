from pathlib import PurePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from pydantic import AnyHttpUrl

from depends import get_rag_service
from models.rag import RagUnavailable
from schemas.rag import RagAnswerRead, RagAnswerRequest, RagJobCreated, RagJobRead
from services.rag import RagService


router = APIRouter(prefix="/internal/rag", tags=["rag"])
Service = Annotated[RagService, Depends(get_rag_service)]


@router.post("/documents", response_model=RagJobCreated, status_code=202)
async def upload_document(
    request: Request,
    service: Service,
    file: UploadFile,
    source_id: Annotated[str, Form(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_./:\-]+$")],
    title: Annotated[str, Form(min_length=1, max_length=250)],
    source_url: Annotated[AnyHttpUrl | None, Form()] = None,
):
    format = PurePath(file.filename or "").suffix.lower().removeprefix(".")
    limit = request.app.state.rag_settings.rag_max_upload_bytes
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
    job_id = await service.submit(source_id, title.strip(), str(source_url) if source_url else None, format, data)
    return RagJobCreated(job_id=job_id)


@router.get("/jobs/{job_id}", response_model=RagJobRead)
async def read_job(job_id: UUID, service: Service):
    job = await service.read_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job


@router.post("/answer", response_model=RagAnswerRead)
async def answer(question: RagAnswerRequest, service: Service):
    try:
        return await service.answer(question.question, question.standalone_question)
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="Document search temporarily unavailable") from error
