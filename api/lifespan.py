from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import AuthSettings, DatabaseSettings, InviteSettings, RedisSettings
from db.db import create_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = DatabaseSettings()
    app.state.auth_settings = AuthSettings()
    app.state.invite_settings = InviteSettings()
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
    try:
        yield
    finally:
        try:
            await redis.aclose()
        finally:
            await engine.dispose()
