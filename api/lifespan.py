import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import AuthSettings, ChatSettings, DatabaseSettings, InviteSettings
from db.db import create_engine
from repositories.rag_index import RagIndex
from repositories.rag_jobs import RagJobs
from repositories.rag_model import RagModel
from services.rag import RagService
from services.rag_ingest import RagIngest


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = DatabaseSettings()
    app.state.auth_settings = AuthSettings()
    app.state.invite_settings = InviteSettings()
    chat = ChatSettings()
    async with AsyncExitStack() as stack:
        engine = create_engine(settings.database_url.get_secret_value())
        stack.push_async_callback(engine.dispose)
        app.state.engine = engine
        app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
        app.state.rag_service = None
        if chat.chat_base_url:
            base_url = str(chat.chat_base_url)
            key = chat.chat_api_key.get_secret_value() if chat.chat_api_key else None
            http = await stack.enter_async_context(httpx.AsyncClient(timeout=20))
            token = app.state.invite_settings.bot_api_token
            model = RagModel(http, token.get_secret_value() if token else None)
            jobs = RagJobs(app.state.sessions)
            index = RagIndex(http, base_url, key)
            app.state.rag_service = RagService(jobs, index)
            worker = asyncio.create_task(RagIngest(jobs, index, model).worker(engine), name="rag-import")
            stack.push_async_callback(stop_worker, worker)
        yield


async def stop_worker(worker: asyncio.Task) -> None:
    worker.cancel()
    with suppress(asyncio.CancelledError):
        await worker
