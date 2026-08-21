import asyncio
import logging
import os
import re

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔤 Sort A–Z"), KeyboardButton(text="🔢 Sort 1–9")],
        [KeyboardButton(text="📖 How to Use")],
    ],
    resize_keyboard=True,
)

WELCOME = (
    "👋 <b>Welcome to Drew Academy Bot!</b>\n\n"
    "Your simple text-sorting assistant. 📚\n\n"
    "Send me a list of words, names, numbers, or items and I’ll organize them for you.\n\n"
    "🔤 <b>Sort A–Z</b> — Arrange text alphabetically.\n"
    "🔢 <b>Sort 1–9</b> — Arrange numbers from smallest to largest.\n"
    "📖 <b>How to Use</b> — See a quick guide.\n\n"
    "✨ <i>Fast, simple, and organized — just send your list!</i>"
)


def parse_items(text: str) -> list[str]:
    # Accept one item per line and comma-separated input.
    return [item.strip() for item in re.split(r"[\n,]+", text) if item.strip()]


def sort_numeric(items: list[str]) -> tuple[list[str], list[str]]:
    numbers, invalid = [], []
    for item in items:
        try:
            numbers.append((float(item), item))
        except ValueError:
            invalid.append(item)
    numbers.sort(key=lambda x: x[0])
    return [item for _, item in numbers], invalid


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(WELCOME, parse_mode="HTML", reply_markup=MENU)


@dp.message(Command("help"))
@dp.message(F.text == "📖 How to Use")
async def help_message(message: Message):
    await message.answer(
        "📖 <b>How to Use Drew Academy Bot</b>\n\n"
        "1️⃣ Tap <b>🔤 Sort A–Z</b> or <b>🔢 Sort 1–9</b>.\n"
        "2️⃣ Send your items, one per line or separated by commas.\n"
        "3️⃣ The bot returns your organized list.\n\n"
        "<b>Example:</b>\n"
        "Banana\nApple\nOrange\nMango\n\n"
        "The A–Z result will be:\n"
        "1. Apple\n2. Banana\n3. Mango\n4. Orange\n\n"
        "💡 Tip: You can also use /start at any time to return to the main menu.",
        parse_mode="HTML",
        reply_markup=MENU,
    )


@dp.message(F.text == "🔤 Sort A–Z")
async def choose_az(message: Message):
    await message.answer(
        "🔤 <b>Sort A–Z</b>\n\nSend your list now. Use one item per line or separate items with commas.",
        parse_mode="HTML",
    )


@dp.message(F.text == "🔢 Sort 1–9")
async def choose_numeric(message: Message):
    await message.answer(
        "🔢 <b>Sort 1–9</b>\n\nSend your numbers now. Use one number per line or separate them with commas.",
        parse_mode="HTML",
    )


@dp.message(F.text)
async def sort_text(message: Message):
    # Keep menu commands from being interpreted as data.
    if message.text in {"🔤 Sort A–Z", "🔢 Sort 1–9", "📖 How to Use"}:
        return

    items = parse_items(message.text)
    if not items:
        await message.answer("Please send at least one item to sort.", reply_markup=MENU)
        return

    # Default free-form input to A–Z sorting.
    sorted_items = sorted(items, key=lambda x: x.casefold())
    result = "🔤 <b>Sorted A–Z:</b>\n\n" + "\n".join(
        f"{i}. {item}" for i, item in enumerate(sorted_items, 1)
    )
    await message.answer(result, parse_mode="HTML", reply_markup=MENU)


async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")
    bot = Bot(TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
