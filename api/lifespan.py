from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import AuthSettings, DatabaseSettings, InviteSettings
from db.db import create_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = DatabaseSettings()
    app.state.auth_settings = AuthSettings()
    app.state.invite_settings = InviteSettings()
    engine = create_engine(settings.database_url.get_secret_value())
    app.state.engine = engine
    app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield
    finally:
        await engine.dispose()
