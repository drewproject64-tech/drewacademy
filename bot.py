import asyncio
import logging
import os
import sqlite3
from contextlib import closing

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "tasks.db")

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()
ADDING_USERS = set()

# Persistent reply keyboard: Telegram displays these buttons above the chat input.
MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Add Task"), KeyboardButton(text="📋 My Tasks")],
        [KeyboardButton(text="❓ How to Use"), KeyboardButton(text="🏠 Main Menu")],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Choose an option or type a command",
)

WELCOME = (
    "👋 <b>Welcome to Drew Bot!</b>\n\n"
    "📝 <b>Your simple Telegram to-do list.</b>\n\n"
    "Create tasks, view your saved list, mark tasks as completed, and delete tasks when you no longer need them.\n\n"
    "🚀 <b>Try it now:</b>\n"
    "1️⃣ Tap <b>📝 Add Task</b> below.\n"
    "2️⃣ Send: <code>Buy groceries</code>\n"
    "3️⃣ Tap <b>📋 My Tasks</b>.\n\n"
    "Your tasks are saved separately for your Telegram account.\n\n"
    "Choose an option below to get started 👇"
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


def get_user_tasks(user_id):
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT id, text, completed FROM tasks WHERE user_id=? ORDER BY completed ASC, id ASC",
            (user_id,),
        ).fetchall()


def main_menu_text():
    return (
        "🏠 <b>Drew Bot</b>\n\n"
        "What would you like to do?\n\n"
        "📝 Add a task\n"
        "📋 View your saved tasks\n"
        "❓ Learn how the bot works"
    )


async def start(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    await message.answer(WELCOME, parse_mode="HTML", reply_markup=MENU)


@dp.message(Command("help"))
@dp.message(F.text == "❓ How to Use")
async def help_message(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    await message.answer(
        "❓ <b>HOW TO USE DREW BOT</b>\n\n"
        "📝 <b>Add Task</b> — tap the button and send the task you want to save.\n\n"
        "📋 <b>My Tasks</b> — view all tasks saved to your account.\n\n"
        "✅ <b>Complete</b> — send <code>complete ID</code> after viewing your tasks.\n\n"
        "🗑️ <b>Delete</b> — send <code>delete ID</code> to remove a task.\n\n"
        "<b>Quick example:</b>\n"
        "📝 Add Task → <code>Buy groceries</code> → 📋 My Tasks → <code>complete 1</code>\n\n"
        "Use /start anytime to return to the welcome screen.",
        parse_mode="HTML",
        reply_markup=MENU,
    )


@dp.message(F.text == "🏠 Main Menu")
async def main_menu(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    await message.answer(main_menu_text(), parse_mode="HTML", reply_markup=MENU)


@dp.message(F.text == "📝 Add Task")
async def add_task(message: Message):
    ADDING_USERS.add(message.from_user.id)
    await message.answer(
        "📝 <b>ADD A TASK</b>\n\n"
        "Send the task you want to save.\n\n"
        "💡 <b>Example:</b> <code>Buy groceries</code>\n\n"
        "You can also type /cancel to stop.",
        parse_mode="HTML",
        reply_markup=MENU,
    )


@dp.message(Command("cancel"))
async def cancel(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    await message.answer("❌ Adding a task was cancelled.", reply_markup=MENU)


@dp.message(F.text == "📋 My Tasks")
async def my_tasks(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    rows = get_user_tasks(message.from_user.id)

    if not rows:
        await message.answer(
            "📋 <b>MY TASKS</b>\n\n"
            "Your task list is empty.\n\n"
            "Tap 📝 Add Task to create your first task.\n\n"
            "💡 Example: <code>Buy groceries</code>",
            parse_mode="HTML",
            reply_markup=MENU,
        )
        return

    lines = ["📋 <b>MY TASKS</b>\n"]
    open_count = 0
    completed_count = 0
    for task_id, text, completed in rows:
        if completed:
            status = "✅"
            completed_count += 1
        else:
            status = "⬜"
            open_count += 1
        lines.append(f"{status} <b>#{task_id}</b> — {text}")

    lines.append(
        f"\n📊 <b>{open_count}</b> open • <b>{completed_count}</b> completed\n\n"
        "Manage a task with:\n"
        "<code>complete ID</code> — mark complete\n"
        "<code>delete ID</code> — delete it\n\n"
        "Example: <code>complete 1</code>"
    )
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=MENU)


@dp.message(F.text.regexp(r"^(?i)complete\s+\d+$"))
async def complete_task(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    task_id = int(message.text.split()[1])
    with closing(get_db()) as conn:
        cur = conn.execute(
            "UPDATE tasks SET completed=1 WHERE id=? AND user_id=?",
            (task_id, message.from_user.id),
        )
        conn.commit()
        changed = cur.rowcount

    if changed:
        await message.answer(
            f"✅ <b>Task #{task_id} completed!</b>\n\n"
            "Your task list has been updated.\n\n"
            "Tap 📋 My Tasks to view it.",
            parse_mode="HTML",
            reply_markup=MENU,
        )
    else:
        await message.answer(
            "⚠️ I couldn't find that task in your list.\n\n"
            "Tap 📋 My Tasks to check the correct task ID.",
            reply_markup=MENU,
        )


@dp.message(F.text.regexp(r"^(?i)delete\s+\d+$"))
async def delete_task(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    task_id = int(message.text.split()[1])
    with closing(get_db()) as conn:
        cur = conn.execute(
            "DELETE FROM tasks WHERE id=? AND user_id=?",
            (task_id, message.from_user.id),
        )
        conn.commit()
        changed = cur.rowcount

    if changed:
        await message.answer(
            f"🗑️ <b>Task #{task_id} deleted.</b>\n\n"
            "Your task list has been updated.\n\n"
            "Tap 📋 My Tasks to check your remaining tasks.",
            parse_mode="HTML",
            reply_markup=MENU,
        )
    else:
        await message.answer(
            "⚠️ I couldn't find that task in your list.\n\n"
            "Tap 📋 My Tasks to check the correct task ID.",
            reply_markup=MENU,
        )


@dp.message(F.text)
async def receive_task(message: Message):
    menu_text = {"📝 Add Task", "📋 My Tasks", "❓ How to Use", "🏠 Main Menu"}
    if message.text in menu_text:
        return

    if message.from_user.id not in ADDING_USERS:
        await message.answer(
            "👋 <b>Ready to organize your tasks?</b>\n\n"
            "Tap 📝 Add Task first.\n\n"
            "💡 Quick example: tap 📝 Add Task and send <code>Buy groceries</code>.",
            parse_mode="HTML",
            reply_markup=MENU,
        )
        return

    text = message.text.strip()
    if not text:
        await message.answer("Please send a task with some text.", reply_markup=MENU)
        return

    if len(text) > 500:
        await message.answer("Please keep each task under 500 characters.", reply_markup=MENU)
        return

    with closing(get_db()) as conn:
        cur = conn.execute(
            "INSERT INTO tasks (user_id, text) VALUES (?, ?)",
            (message.from_user.id, text),
        )
        task_id = cur.lastrowid
        conn.commit()

    ADDING_USERS.discard(message.from_user.id)
    await message.answer(
        f"✅ <b>Task saved!</b>\n\n"
        f"⬜ <b>#{task_id}</b> — {text}\n\n"
        "Tap 📋 My Tasks to view, complete, or delete it.",
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
