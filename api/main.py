from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import DatabaseSettings
from db.db import create_engine
from routes import tickets, users
from services.users import UserService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = DatabaseSettings()
    engine = create_engine(settings.database_url.get_secret_value())
    app.state.engine = engine
    app.state.user_service = UserService(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="БАРС API", lifespan=lifespan)
app.include_router(users.router)
app.include_router(tickets.router)


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    try:
        async with request.app.state.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(503, "Database unavailable") from None
    return {"status": "ok"}
