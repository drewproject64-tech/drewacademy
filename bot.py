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
        [KeyboardButton(text="🧪 Try Example")],
        [KeyboardButton(text="📖 How to Use")],
    ],
    resize_keyboard=True,
)

WELCOME = (
    "👋 <b>Welcome to Drew Academy Bot!</b>\n\n"
    "A simple utility for organizing lists quickly and clearly. 📚\n\n"
    "🔤 <b>Sort A–Z</b> — Sort words, names, and items alphabetically.\n"
    "🔢 <b>Sort 1–9</b> — Sort numbers from smallest to largest.\n"
    "🧪 <b>Try Example</b> — See exactly how the bot works.\n"
    "📖 <b>How to Use</b> — Get a quick guide.\n\n"
    "<b>Quick example:</b>\n"
    "Tap <b>🔤 Sort A–Z</b>, then send:\n\n"
    "Banana\nApple\nOrange\nMango\n\n"
    "I’ll return the list in alphabetical order.\n\n"
    "✨ <i>Ready? Choose an option below.</i>"
)

AZ_EXAMPLE_INPUT = "Banana\nApple\nOrange\nMango"
NUMERIC_EXAMPLE_INPUT = "42\n7\n100\n3\n25"


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


def numbered(items: list[str]) -> str:
    return "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(WELCOME, parse_mode="HTML", reply_markup=MENU)


@dp.message(Command("help"))
@dp.message(F.text == "📖 How to Use")
async def help_message(message: Message):
    await message.answer(
        "📖 <b>How to Use Drew Academy Bot</b>\n\n"
        "<b>1.</b> Choose <b>🔤 Sort A–Z</b> or <b>🔢 Sort 1–9</b>.\n"
        "<b>2.</b> Send your items, one per line or separated by commas.\n"
        "<b>3.</b> I’ll return the sorted list immediately.\n\n"
        "<b>Example — A–Z</b>\n"
        "You send:\n"
        "Banana\nApple\nOrange\nMango\n\n"
        "I return:\n"
        "1. Apple\n2. Banana\n3. Mango\n4. Orange\n\n"
        "<b>Example — 1–9</b>\n"
        "You send:\n"
        "42, 7, 100, 3, 25\n\n"
        "I return:\n"
        "1. 3\n2. 7\n3. 25\n4. 42\n5. 100\n\n"
        "💡 You can use /start at any time to return to the main menu.",
        parse_mode="HTML",
        reply_markup=MENU,
    )


@dp.message(F.text == "🧪 Try Example")
async def try_example(message: Message):
    await message.answer(
        "🧪 <b>Try Drew Academy Bot</b>\n\n"
        "Let’s sort a sample list.\n\n"
        "<b>Step 1</b> — Tap <b>🔤 Sort A–Z</b>.\n"
        "<b>Step 2</b> — Send this exact example:\n\n"
        f"<code>{AZ_EXAMPLE_INPUT}</code>\n\n"
        "The bot will reply with:\n\n"
        "🔤 <b>Sorted A–Z:</b>\n\n"
        "1. Apple\n2. Banana\n3. Mango\n4. Orange\n\n"
        "You can then try your own list!",
        parse_mode="HTML",
        reply_markup=MENU,
    )


@dp.message(F.text == "🔤 Sort A–Z")
async def choose_az(message: Message):
    await message.answer(
        "🔤 <b>Sort A–Z</b>\n\n"
        "Send your list now. Use one item per line or separate items with commas.\n\n"
        "<b>Example:</b>\n"
        "Banana\nApple\nOrange\nMango",
        parse_mode="HTML",
    )


@dp.message(F.text == "🔢 Sort 1–9")
async def choose_numeric(message: Message):
    await message.answer(
        "🔢 <b>Sort 1–9</b>\n\n"
        "Send your numbers now. Use one number per line or separate them with commas.\n\n"
        "<b>Example:</b>\n"
        "42, 7, 100, 3, 25",
        parse_mode="HTML",
    )


@dp.message(F.text)
async def sort_text(message: Message):
    # Keep menu commands from being interpreted as data.
    if message.text in {"🔤 Sort A–Z", "🔢 Sort 1–9", "🧪 Try Example", "📖 How to Use"}:
        return

    items = parse_items(message.text)
    if not items:
        await message.answer(
            "Please send at least one word, name, item, or number to sort.",
            reply_markup=MENU,
        )
        return

    # Preserve the existing simple behavior: free-form text defaults to A–Z.
    sorted_items = sorted(items, key=lambda x: x.casefold())
    result = "🔤 <b>Sorted A–Z:</b>\n\n" + numbered(sorted_items)
    await message.answer(result, parse_mode="HTML", reply_markup=MENU)


async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")
    bot = Bot(TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
