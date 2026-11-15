import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import (
    AnalyticsSettings,
    AuthSettings,
    ConfluenceSettings,
    DatabaseSettings,
    EmbeddingSettings,
    FileSettings,
    InviteSettings,
    RedisSettings,
)
from db.db import create_engine
from models.rag import RagImport
from repositories.confluence import ConfluenceRepository
from repositories.rag_cache import RagCache
from repositories.rag_files import RagFiles
from repositories.rag_index import RagIndex
from repositories.rag_jobs import RagJobs
from repositories.rag_model import RagModel
from repositories.rag_uploads import RagUploads
from repositories.technical_analytics import PrometheusRepository
from services.confluence import ConfluenceService
from services.rag import RagOriginals, RagService
from services.rag_ingest import RagIngest


def redact_file_signature(record: logging.LogRecord) -> bool:
    args = record.args
    if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str) and args[2].startswith("/file-service/"):
        record.args = (*args[:2], args[2].partition("?")[0], *args[3:])
    return True


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = DatabaseSettings()
    app.state.auth_settings = AuthSettings()
    app.state.invite_settings = InviteSettings()
    confluence_settings = ConfluenceSettings()
    embeddings = EmbeddingSettings()
    redis_settings = RedisSettings()
    analytics = AnalyticsSettings()
    async with AsyncExitStack() as stack:
        app.state.prometheus = None
        if analytics.prometheus_url:
            prometheus_client = await stack.enter_async_context(httpx.AsyncClient(
                base_url=str(analytics.prometheus_url), timeout=3,
            ))
            app.state.prometheus = PrometheusRepository(prometheus_client)
        access_log = logging.getLogger("uvicorn.access")
        access_log.addFilter(redact_file_signature)
        stack.callback(access_log.removeFilter, redact_file_signature)
        engine = create_engine(settings.database_url.get_secret_value())
        stack.push_async_callback(engine.dispose)
        app.state.engine = engine
        app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
        redis = Redis.from_url(
            redis_settings.redis_url.get_secret_value(),
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        stack.push_async_callback(redis.aclose)
        app.state.redis = redis
        confluence_client = await stack.enter_async_context(
            httpx.AsyncClient(
                base_url=confluence_settings.confluence_base_url.rstrip("/") + "/",
                auth=(
                    confluence_settings.confluence_email,
                    confluence_settings.confluence_api_token.get_secret_value(),
                ),
                headers={"Accept": "application/json"},
                timeout=30,
            )
        )
        confluence = ConfluenceService(ConfluenceRepository(confluence_client), confluence_settings)
        app.state.confluence_service = confluence
        app.state.rag_service = None
        file_settings = FileSettings()
        http = await stack.enter_async_context(httpx.AsyncClient(timeout=20))
        token = app.state.invite_settings.bot_api_token
        secret = token.get_secret_value() if token else None
        files = RagFiles(http, str(file_settings.file_service_url), str(file_settings.rag_files_public_url), secret)
        jobs = RagJobs(app.state.sessions, engine)
        app.state.rag_originals = RagOriginals(files, jobs)
        if embeddings.embedding_base_url:
            rag_redis = Redis.from_url(
                redis_settings.rag_redis_url.get_secret_value(),
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
                retry=Retry(NoBackoff(), 0),
            )
            stack.push_async_callback(rag_redis.aclose)
            base_url = str(embeddings.embedding_base_url)
            key = embeddings.embedding_api_key.get_secret_value() if embeddings.embedding_api_key else None
            model = RagModel(http, secret)
            index = RagIndex(http, base_url, key)
            uploads = RagUploads(index.key)
            app.state.rag_service = RagService(jobs, index, files, RagCache(rag_redis))

            async def load_import(job: RagImport) -> bytes:
                return await files.load(job.file_id) if job.file_id else await uploads.load(job)

            importer = RagIngest(jobs, index, model, load_import, uploads.discard, files.delete, confluence)
            worker = asyncio.create_task(importer.worker(), name="rag-import")
            stack.push_async_callback(stop_worker, worker)
        yield


async def stop_worker(worker: asyncio.Task) -> None:
    worker.cancel()
    with suppress(asyncio.CancelledError):
        await worker


@asynccontextmanager
async def internal_lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = DatabaseSettings()
    engine = create_engine(settings.database_url.get_secret_value())
    app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield
    finally:
        await engine.dispose()
