from collections.abc import Awaitable, Callable
from functools import partial
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Path, Query, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

from depends import get_current_user, get_rag_originals, get_rag_service, require_bot_token
from models.rag import DocumentTooLarge, InvalidDocument, RagDocumentNotFound, RagUnavailable
from repositories.rag_files import MAX_DOCUMENT_BYTES
from schemas.rag import (
    CONFLUENCE_ID_PATTERN, SOURCE_ID_PATTERN, RagConfluenceImportCreate, RagEvidenceRead, RagFileUploadCreated,
    RagFileUploadError, RagJobCreated, RagJobPage, RagJobRead, RagSearchRequest, RagUrlRequest,
)
from services.rag import RagOriginals, RagService, UnexpectedDocumentId


router = APIRouter(tags=["rag"])
Service = Annotated[RagService, Depends(get_rag_service)]


@router.post(
    "/rag/documents", response_model=list[RagFileUploadCreated | RagFileUploadError],
    responses={202: {"model": RagJobCreated, "description": "Single file accepted"}},
    dependencies=[Depends(get_current_user)],
)
async def upload_document(
    service: Service,
    files: Annotated[list[UploadFile] | None, File(min_length=1)] = None,
    file: UploadFile | None = None,
    source_id: Annotated[str | None, Form(min_length=1, max_length=100, pattern=SOURCE_ID_PATTERN)] = None,
    title: Annotated[str | None, Form(min_length=1, max_length=250)] = None,
):
    if files is None:
        if file is None:
            raise HTTPException(status_code=422, detail="Provide file or files")
        job = await save_upload(file, title, partial(service.submit_file, source_id))
        return JSONResponse(status_code=202, content=job.model_dump(mode="json"))
    if file is not None:
        raise HTTPException(status_code=422, detail="Provide either file or files")
    if source_id is not None or title is not None:
        raise HTTPException(status_code=422, detail="Source metadata requires the file field")

    results: list[RagFileUploadCreated | RagFileUploadError] = []
    submit = partial(service.submit_file, None)
    for upload in files:
        filename = upload.filename or ""
        try:
            job = await save_upload(upload, None, submit)
        except HTTPException as error:
            results.append(RagFileUploadError(filename=filename, status_code=error.status_code, detail=error.detail))
        else:
            results.append(RagFileUploadCreated(filename=filename, **job.model_dump()))
    return results


async def save_upload(
    file: UploadFile, title: str | None,
    submit: Callable[[str | None, str, bytes], Awaitable[tuple[UUID, str, UUID]]],
) -> RagJobCreated:
    try:
        if title is not None and not title.strip():
            raise HTTPException(status_code=422, detail="Invalid source metadata")
        if file.size is not None and file.size > MAX_DOCUMENT_BYTES:
            raise HTTPException(status_code=413, detail="Document is too large")
        data = await file.read(MAX_DOCUMENT_BYTES + 1)
    finally:
        await file.close()
    try:
        job_id, source_id, file_id = await submit(title.strip() if title else None, file.filename or "", data)
    except RagDocumentNotFound as error:
        raise HTTPException(status_code=404, detail="Document not found") from error
    except DocumentTooLarge as error:
        raise HTTPException(status_code=413, detail="Document is too large") from error
    except InvalidDocument as error:
        status = 415 if str(error) == "unsupported_source_format" else 422
        raise HTTPException(status_code=status, detail=str(error)) from error
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="Document upload temporarily unavailable") from error
    return RagJobCreated(job_id=job_id, source_id=source_id, file_id=file_id)


@router.post(
    "/rag/documents/from-url", response_model=RagJobCreated, status_code=202,
    response_model_exclude_none=True, dependencies=[Depends(get_current_user)],
)
async def import_from_url(source: RagUrlRequest, service: Service):
    if source.url.username or source.url.password:
        raise HTTPException(status_code=422, detail="Invalid source URL")
    try:
        job_id, source_id = await service.submit_url(source.source_id, source.title, str(source.url))
    except InvalidDocument as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="Document import temporarily unavailable") from error
    return RagJobCreated(job_id=job_id, source_id=source_id)


@router.post(
    "/internal/rag/confluence/imports", response_model=RagJobCreated, status_code=202,
    response_model_exclude_none=True, dependencies=[Depends(require_bot_token)],
)
async def import_confluence_page(source: RagConfluenceImportCreate, service: Service):
    try:
        job_id, source_id = await service.submit_confluence(source.space_id, source.page_id)
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="Document import temporarily unavailable") from error
    return RagJobCreated(job_id=job_id, source_id=source_id)


@router.delete(
    "/internal/rag/confluence/sources/{page_id}", status_code=204, dependencies=[Depends(require_bot_token)],
)
async def delete_confluence_page(
    page_id: Annotated[str, Path(pattern=CONFLUENCE_ID_PATTERN)],
    space_id: Annotated[str, Query(pattern=CONFLUENCE_ID_PATTERN)],
    service: Service,
):
    try:
        await service.delete_confluence_document(space_id, page_id)
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="Document deletion temporarily unavailable") from error


@router.get("/file-service/{file_id}")
async def open_file(
    file_id: UUID, originals: Annotated[RagOriginals, Depends(get_rag_originals)],
    sig: Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")],
    byte_range: Annotated[str | None, Header(alias="Range", max_length=100)] = None,
):
    try:
        upstream = await originals.open(file_id, sig, byte_range)
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="File temporarily unavailable") from error
    if upstream is None:
        raise HTTPException(status_code=404, detail="File not found")
    if upstream.status_code in (404, 416):
        await upstream.aclose()
        return Response(status_code=upstream.status_code, headers={
            name: upstream.headers[name] for name in ("content-range",) if name in upstream.headers
        })

    async def stream():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    headers = {
        name: upstream.headers[name] for name in
        ("content-type", "content-disposition", "content-length", "content-range", "accept-ranges")
        if name in upstream.headers
    }
    headers.update({
        "cache-control": "private, no-store", "x-content-type-options": "nosniff", "referrer-policy": "no-referrer",
    })
    return StreamingResponse(stream(), status_code=upstream.status_code, headers=headers)


@router.get("/rag/jobs", response_model=RagJobPage, dependencies=[Depends(get_current_user)])
async def list_jobs(
    service: Service,
    page: Annotated[int, Query(ge=1, le=2**31 - 1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    include_history: bool = False,
):
    try:
        return await service.list_jobs(page, page_size, include_history)
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="Import list temporarily unavailable") from error


@router.get("/rag/jobs/{job_id}", response_model=RagJobRead, dependencies=[Depends(get_current_user)])
async def read_job(job_id: UUID, service: Service):
    try:
        job = await service.read_job(job_id)
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="Import status temporarily unavailable") from error
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job


@router.put(
    "/rag/jobs/{job_id}", response_model=RagJobCreated, status_code=202, dependencies=[Depends(get_current_user)],
)
async def replace_document(
    job_id: UUID, service: Service, file: UploadFile,
    title: Annotated[str | None, Form(min_length=1, max_length=250)] = None,
):
    return await save_upload(file, title, partial(service.replace_file, job_id))


@router.delete("/rag/jobs/{job_id}", status_code=204, dependencies=[Depends(get_current_user)])
async def delete_document(job_id: UUID, service: Service):
    try:
        await service.delete_document(job_id)
    except RagDocumentNotFound as error:
        raise HTTPException(status_code=404, detail="Document not found") from error
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="Document deletion temporarily unavailable") from error


@router.post(
    "/internal/rag/search", response_model=list[RagEvidenceRead], dependencies=[Depends(require_bot_token)],
)
async def search(query: RagSearchRequest, service: Service):
    try:
        return await service.search(
            query.question, query.exact_id, query.original_question, standalone=query.standalone,
            include_visual=query.include_visual,
        )
    except UnexpectedDocumentId as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="Document search temporarily unavailable") from error


@router.get("/internal/rag/visual/{block_id}", dependencies=[Depends(require_bot_token)])
async def visual(
    block_id: Annotated[str, Path(pattern=r"^[a-f0-9-]{36}:[1-9][0-9]{0,5}$")], service: Service, telegram: bool = False,
):
    try:
        image = await service.visual(block_id, telegram=telegram)
    except (RagDocumentNotFound, InvalidDocument) as error:
        raise HTTPException(status_code=404, detail="Document image unavailable") from error
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="Document image temporarily unavailable") from error
    return Response(image, media_type="image/png", headers={"cache-control": "private, no-store"})


@router.post(
    "/rag/jobs/{job_id}/refresh-visuals", response_model=RagJobCreated, response_model_exclude_none=True,
    status_code=202, dependencies=[Depends(get_current_user)],
)
async def refresh_visuals(job_id: UUID, service: Service):
    try:
        refresh_id, source_id = await service.refresh_visuals(job_id)
    except RagDocumentNotFound as error:
        raise HTTPException(status_code=404, detail="Document not found") from error
    except InvalidDocument as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RagUnavailable as error:
        raise HTTPException(status_code=503, detail="Document import temporarily unavailable") from error
    return RagJobCreated(job_id=refresh_id, source_id=source_id)
