import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import AuthSettings, DatabaseSettings, EmbeddingSettings, InviteSettings
from db.db import create_engine
from repositories.rag_index import RagIndex
from repositories.rag_jobs import RagJobs
from repositories.rag_model import RagModel
from repositories.rag_uploads import RagUploads
from services.rag import RagService
from services.rag_ingest import RagIngest


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = DatabaseSettings()
    app.state.auth_settings = AuthSettings()
    app.state.invite_settings = InviteSettings()
    embeddings = EmbeddingSettings()
    async with AsyncExitStack() as stack:
        engine = create_engine(settings.database_url.get_secret_value())
        stack.push_async_callback(engine.dispose)
        app.state.engine = engine
        app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
        app.state.rag_service = None
        if embeddings.embedding_base_url:
            base_url = str(embeddings.embedding_base_url)
            key = embeddings.embedding_api_key.get_secret_value() if embeddings.embedding_api_key else None
            http = await stack.enter_async_context(httpx.AsyncClient(timeout=20))
            token = app.state.invite_settings.bot_api_token
            model = RagModel(http, token.get_secret_value() if token else None)
            jobs = RagJobs(app.state.sessions, engine)
            index = RagIndex(http, base_url, key)
            uploads = RagUploads(index.key)
            app.state.rag_service = RagService(jobs, index, uploads)
            importer = RagIngest(jobs, index, model, uploads.load, uploads.discard)
            worker = asyncio.create_task(importer.worker(), name="rag-import")
            stack.push_async_callback(stop_worker, worker)
        yield


async def stop_worker(worker: asyncio.Task) -> None:
    worker.cancel()
    with suppress(asyncio.CancelledError):
        await worker
