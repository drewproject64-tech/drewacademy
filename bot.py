import asyncio
import logging
import os
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "tasks.db")

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()
ADDING_USERS = set()

# Reply keyboard keeps the main controls directly above the chat input.
MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Add Task"), KeyboardButton(text="📋 My Tasks")],
        [KeyboardButton(text="❓ How to Use")],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Choose an option or type a command",
)

WELCOME = (
    "👋 <b>Welcome to Drew Bot!</b>\n\n"
    "📝 A simple to-do list for organizing tasks directly in Telegram.\n\n"
    "<b>Quick example:</b>\n"
    "1. Tap <b>📝 Add Task</b> below.\n"
    "2. Send: <code>Buy groceries</code>\n"
    "3. Tap <b>📋 My Tasks</b> to see it.\n"
    "4. Use <code>complete ID</code> or <code>delete ID</code> to manage it.\n\n"
    "Your tasks are saved to your account. Choose an option below 👇"
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tasks ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "user_id INTEGER NOT NULL, "
        "text TEXT NOT NULL, "
        "completed INTEGER NOT NULL DEFAULT 0, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    return conn


async def start(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    await message.answer(WELCOME, parse_mode="HTML", reply_markup=MENU)


@dp.message(Command("help"))
@dp.message(F.text == "❓ How to Use")
async def help_message(message: Message):
    await message.answer(
        "❓ <b>HOW TO USE</b>\n\n"
        "📝 <b>Add Task</b> — tap the button, then send your task.\n"
        "📋 <b>My Tasks</b> — view your saved tasks.\n"
        "✅ <b>Complete</b> — send <code>complete ID</code>.\n"
        "🗑️ <b>Delete</b> — send <code>delete ID</code>.\n\n"
        "<b>Example:</b> Add Task → <code>Buy groceries</code> → My Tasks.\n\n"
        "Your tasks are stored separately for your Telegram account.",
        parse_mode="HTML",
        reply_markup=MENU,
    )


@dp.message(F.text == "📝 Add Task")
async def add_task(message: Message):
    ADDING_USERS.add(message.from_user.id)
    await message.answer(
        "📝 <b>ADD A TASK</b>\n\n"
        "Send the task you want to save.\n\n"
        "<b>Example:</b> <code>Buy groceries</code>",
        parse_mode="HTML",
        reply_markup=MENU,
    )


@dp.message(F.text == "📋 My Tasks")
async def my_tasks(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, text, completed FROM tasks WHERE user_id=? ORDER BY completed, id",
        (message.from_user.id,),
    ).fetchall()
    conn.close()

    if not rows:
        await message.answer(
            "📋 <b>MY TASKS</b>\n\n"
            "You don't have any tasks yet.\n\n"
            "Tap 📝 Add Task to create your first one.",
            parse_mode="HTML",
            reply_markup=MENU,
        )
        return

    lines = ["📋 <b>MY TASKS</b>\n"]
    for task_id, text, completed in rows:
        status = "✅" if completed else "⬜"
        lines.append(f"{status} <b>#{task_id}</b> — {text}")
    lines.append(
        "\n<b>Manage a task:</b>\n"
        "• <code>complete ID</code> — mark complete\n"
        "• <code>delete ID</code> — delete it\n\n"
        "Example: <code>complete 1</code>"
    )
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=MENU)


@dp.message(F.text.regexp(r"^complete\s+\d+$"))
async def complete_task(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    task_id = int(message.text.split()[1])
    conn = get_db()
    cur = conn.execute(
        "UPDATE tasks SET completed=1 WHERE id=? AND user_id=?",
        (task_id, message.from_user.id),
    )
    conn.commit()
    conn.close()
    if cur.rowcount:
        await message.answer(
            f"✅ <b>Task #{task_id} completed!</b>\n\n"
            "Tap 📋 My Tasks to view your updated list.",
            parse_mode="HTML",
            reply_markup=MENU,
        )
    else:
        await message.answer(
            "I couldn't find that task in your list. Tap 📋 My Tasks to check the task ID.",
            reply_markup=MENU,
        )


@dp.message(F.text.regexp(r"^delete\s+\d+$"))
async def delete_task(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    task_id = int(message.text.split()[1])
    conn = get_db()
    cur = conn.execute(
        "DELETE FROM tasks WHERE id=? AND user_id=?",
        (task_id, message.from_user.id),
    )
    conn.commit()
    conn.close()
    if cur.rowcount:
        await message.answer(
            f"🗑️ <b>Task #{task_id} deleted.</b>\n\n"
            "Your list has been updated.",
            parse_mode="HTML",
            reply_markup=MENU,
        )
    else:
        await message.answer(
            "I couldn't find that task in your list. Tap 📋 My Tasks to check the task ID.",
            reply_markup=MENU,
        )


@dp.message(F.text)
async def receive_task(message: Message):
    menu_text = {"📝 Add Task", "📋 My Tasks", "❓ How to Use"}
    if message.text in menu_text:
        return

    if message.from_user.id not in ADDING_USERS:
        await message.answer(
            "👋 Choose an option below to get started.\n\n"
            "For a quick test, tap 📝 Add Task and send <code>Buy groceries</code>.",
            parse_mode="HTML",
            reply_markup=MENU,
        )
        return

    text = message.text.strip()
    if not text:
        await message.answer("Please send a task with some text.", reply_markup=MENU)
        return

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO tasks (user_id, text) VALUES (?, ?)",
        (message.from_user.id, text),
    )
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    ADDING_USERS.discard(message.from_user.id)

    await message.answer(
        f"✅ <b>Task saved!</b>\n\n"
        f"⬜ <b>#{task_id}</b> — {text}\n\n"
        "Tap 📋 My Tasks to view and manage it.",
        parse_mode="HTML",
        reply_markup=MENU,
    )


async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")
    bot = Bot(TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
