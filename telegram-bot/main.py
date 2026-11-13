from aiogram import Bot, Dispatcher

from config import settings

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()


async def main():
    from routers import start, ask

    dp.include_router(start.router)
    dp.include_router(ask.router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
