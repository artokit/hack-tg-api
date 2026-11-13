from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from agents.support import build_agent, build_model_client
from config import Settings
from db.db import create_engine
from routes import chat, users
from services.chat import ChatService
from services.live_turns import LiveTurns
from services.users import UserService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    engine = create_engine(settings.database_url.get_secret_value())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with build_model_client(settings) as client:
            app.state.agent_api_token = (
                settings.agent_api_token.get_secret_value().encode()
            )
            app.state.user_service = UserService(sessions)
            app.state.chat_service = ChatService(
                build_agent(settings, client), sessions
            )
            app.state.live_turns = LiveTurns(app.state.chat_service)
            yield
    finally:
        await engine.dispose()


app = FastAPI(title="Hackathon API", lifespan=lifespan)
app.include_router(users.router)
app.include_router(chat.router)
