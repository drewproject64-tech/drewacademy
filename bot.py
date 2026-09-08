import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

TOKEN = os.getenv("BOT_TOKEN")

START_MESSAGE = "Get XAUUSD Daily 5-8 Free Signals Free Available Join Now 👊👇👇👇👇https://t.me/Drewcommunity"

dp = Dispatcher()
logging.basicConfig(level=logging.INFO)


@dp.message(CommandStart())
async def start_command(message: Message) -> None:
    await message.answer(START_MESSAGE)


async def main() -> None:
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")

    bot = Bot(token=TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
