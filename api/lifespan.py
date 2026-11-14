import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from agents.rag import Luna
from config import AuthSettings, DatabaseSettings, InviteSettings, RagSettings
from db.db import create_engine
from repositories.rag_index import RagIndex
from repositories.rag_jobs import RagJobs
from services.rag import RagService
from services.rag_ingest import RagIngest


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = DatabaseSettings()
    app.state.auth_settings = AuthSettings()
    app.state.invite_settings = InviteSettings()
    rag_settings = RagSettings()
    async with AsyncExitStack() as stack:
        engine = create_engine(settings.database_url.get_secret_value())
        stack.push_async_callback(engine.dispose)
        app.state.engine = engine
        app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
        app.state.rag_settings = rag_settings
        app.state.rag_service = None
        if rag_settings.rag_enabled:
            http = await stack.enter_async_context(httpx.AsyncClient(timeout=20))
            luna = Luna(rag_settings)
            stack.push_async_callback(luna.close)
            jobs = RagJobs(app.state.sessions)
            index = RagIndex(rag_settings, http)
            app.state.rag_service = RagService(jobs, index, luna)
            worker = asyncio.create_task(RagIngest(jobs, index, luna).worker(engine), name="rag-import")
            stack.push_async_callback(stop_worker, worker)
        yield


async def stop_worker(worker: asyncio.Task) -> None:
    worker.cancel()
    with suppress(asyncio.CancelledError):
        await worker
