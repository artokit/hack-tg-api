import asyncio
import logging

import httpx
from aiogram import Bot, Dispatcher

from config import Settings
from routers import agent, start
from services.agent_client import AgentClient


async def main() -> None:
    settings = Settings()
    bot = Bot(token=settings.bot_token.get_secret_value())
    dispatcher = Dispatcher()
    dispatcher.include_routers(start.router, agent.router)

    async with (
        bot.context(),
        httpx.AsyncClient(base_url=str(settings.api_url), timeout=55) as client,
    ):
        await dispatcher.start_polling(
            bot,
            close_bot_session=False,
            api_client=client,
            agent_client=AgentClient(
                client, settings.agent_api_token.get_secret_value()
            ),
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
