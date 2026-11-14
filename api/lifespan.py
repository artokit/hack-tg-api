from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import (
    AuthSettings,
    ConfluenceSettings,
    DatabaseSettings,
    InviteSettings,
    RedisSettings,
)
from db.db import create_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = DatabaseSettings()
    app.state.auth_settings = AuthSettings()
    app.state.invite_settings = InviteSettings()
    confluence_settings = ConfluenceSettings()
    app.state.confluence_settings = confluence_settings
    redis_settings = RedisSettings()
    redis = Redis.from_url(
        redis_settings.redis_url.get_secret_value(),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    engine = create_engine(settings.database_url.get_secret_value())
    app.state.engine = engine
    app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
    app.state.redis = redis
    async with httpx.AsyncClient(
        base_url=confluence_settings.confluence_base_url.rstrip("/") + "/",
        auth=(
            confluence_settings.confluence_email,
            confluence_settings.confluence_api_token.get_secret_value(),
        ),
        headers={"Accept": "application/json"},
        timeout=30,
    ) as confluence_client:
        app.state.confluence_client = confluence_client
        try:
            yield
        finally:
            try:
                await redis.aclose()
            finally:
                await engine.dispose()
