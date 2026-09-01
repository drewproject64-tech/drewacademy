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

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Add Task"), KeyboardButton(text="📋 My Tasks")],
        [KeyboardButton(text="✅ Complete Task"), KeyboardButton(text="🗑️ Delete Task")],
        [KeyboardButton(text="❓ How to Use"), KeyboardButton(text="🏠 Main Menu")],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Choose an option below",
)

WELCOME = (
    "👋 <b>Welcome to Drew Bot!</b>\n\n"
    "📝 Drew Bot is a simple Telegram to-do list that helps you create, save, view, complete, and delete tasks directly in your chat.\n\n"
    "🚀 <b>Try the example:</b> tap 📝 Add Task and send <code>Buy groceries</code>. "
    "Then tap 📋 My Tasks to see your saved task.\n\n"
    "Use the buttons below to get started 👇"
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


def get_tasks(user_id):
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT id, text, completed FROM tasks WHERE user_id=? ORDER BY completed ASC, id ASC",
            (user_id,),
        ).fetchall()


def task_by_id(user_id, task_id):
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT id, text, completed FROM tasks WHERE id=? AND user_id=?",
            (task_id, user_id),
        ).fetchone()


async def start(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    await message.answer(WELCOME, parse_mode="HTML", reply_markup=MENU)


@dp.message(Command("help"))
@dp.message(F.text == "❓ How to Use")
async def help_message(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    await message.answer(
        "❓ <b>HOW TO USE DREW BOT</b>\n\n"
        "📝 Add Task — tap it, then send your task.\n"
        "📋 My Tasks — view your saved tasks and their IDs.\n"
        "✅ Complete Task — enter the ID of a task to mark it complete.\n"
        "🗑️ Delete Task — enter the ID of a task to remove it.\n\n"
        "💡 <b>Example:</b> Add Task → <code>Buy groceries</code> → My Tasks → Complete Task → <code>1</code>.\n\n"
        "Use /start anytime to return to the main screen.",
        parse_mode="HTML", reply_markup=MENU,
    )


@dp.message(F.text == "🏠 Main Menu")
async def main_menu(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    await message.answer(WELCOME, parse_mode="HTML", reply_markup=MENU)


@dp.message(F.text == "📝 Add Task")
async def add_task(message: Message):
    ADDING_USERS.add(message.from_user.id)
    await message.answer(
        "📝 <b>ADD A TASK</b>\n\nSend the task you want to save.\n\n"
        "💡 Example: <code>Buy groceries</code>\n\nType /cancel to stop.",
        parse_mode="HTML", reply_markup=MENU,
    )


@dp.message(Command("cancel"))
async def cancel(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    await message.answer("❌ Adding a task was cancelled.", reply_markup=MENU)


@dp.message(F.text == "📋 My Tasks")
async def my_tasks(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    rows = get_tasks(message.from_user.id)
    if not rows:
        await message.answer(
            "📋 <b>MY TASKS</b>\n\nYour list is empty.\n\n"
            "Tap 📝 Add Task and try <code>Buy groceries</code>.",
            parse_mode="HTML", reply_markup=MENU,
        )
        return

    lines = ["📋 <b>MY TASKS</b>\n"]
    for task_id, text, completed in rows:
        status = "✅" if completed else "⬜"
        lines.append(f"{status} <b>#{task_id}</b> — {text}")
    lines.append("\nUse ✅ Complete Task or 🗑️ Delete Task and enter the task ID.")
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=MENU)


@dp.message(F.text == "✅ Complete Task")
async def complete_prompt(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    rows = get_tasks(message.from_user.id)
    if not rows:
        await message.answer("📋 You have no tasks yet. Tap 📝 Add Task first.", reply_markup=MENU)
        return
    await message.answer(
        "✅ <b>COMPLETE A TASK</b>\n\n"
        "Enter the task ID you want to mark as completed.\n\n"
        "Example: <code>1</code>",
        parse_mode="HTML", reply_markup=MENU,
    )
    ADDING_USERS.add(f"complete:{message.from_user.id}")


@dp.message(F.text == "🗑️ Delete Task")
async def delete_prompt(message: Message):
    ADDING_USERS.discard(message.from_user.id)
    rows = get_tasks(message.from_user.id)
    if not rows:
        await message.answer("📋 You have no tasks to delete.", reply_markup=MENU)
        return
    await message.answer(
        "🗑️ <b>DELETE A TASK</b>\n\n"
        "Enter the task ID you want to delete.\n\n"
        "Example: <code>1</code>",
        parse_mode="HTML", reply_markup=MENU,
    )
    ADDING_USERS.add(f"delete:{message.from_user.id}")


async def handle_id_action(message: Message, action: str, task_id: int):
    user_id = message.from_user.id
    task = task_by_id(user_id, task_id)
    if not task:
        await message.answer("⚠️ Task not found. Tap 📋 My Tasks to check the correct ID.", reply_markup=MENU)
        return

    with closing(get_db()) as conn:
        if action == "complete":
            conn.execute("UPDATE tasks SET completed=1 WHERE id=? AND user_id=?", (task_id, user_id))
        else:
            conn.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
        conn.commit()

    if action == "complete":
        await message.answer(f"✅ <b>Task #{task_id} completed!</b>\n\n{task[1]}", parse_mode="HTML", reply_markup=MENU)
    else:
        await message.answer(f"🗑️ <b>Task #{task_id} deleted.</b>\n\n{task[1]}", parse_mode="HTML", reply_markup=MENU)


@dp.message(F.text)
async def receive_text(message: Message):
    text = message.text.strip()
    user_id = message.from_user.id
    if text in {"📝 Add Task", "📋 My Tasks", "✅ Complete Task", "🗑️ Delete Task", "❓ How to Use", "🏠 Main Menu"}:
        return

    state_complete = f"complete:{user_id}"
    state_delete = f"delete:{user_id}"

    if state_complete in ADDING_USERS or state_delete in ADDING_USERS:
        if not text.isdigit():
            await message.answer("Please enter a numeric task ID, for example <code>1</code>.", parse_mode="HTML", reply_markup=MENU)
            return
        ADDING_USERS.discard(state_complete)
        ADDING_USERS.discard(state_delete)
        await handle_id_action(message, "complete" if state_complete in ADDING_USERS or state_delete not in ADDING_USERS else "delete", int(text))
        return

    if user_id not in ADDING_USERS:
        await message.answer(
            "👋 Ready to organize your tasks?\n\nTap 📝 Add Task and send <code>Buy groceries</code> to try the bot.",
            parse_mode="HTML", reply_markup=MENU,
        )
        return

    if len(text) > 500:
        await message.answer("Please keep each task under 500 characters.", reply_markup=MENU)
        return

    with closing(get_db()) as conn:
        cur = conn.execute("INSERT INTO tasks (user_id, text) VALUES (?, ?)", (user_id, text))
        task_id = cur.lastrowid
        conn.commit()

    ADDING_USERS.discard(user_id)
    await message.answer(
        f"✅ <b>Task saved!</b>\n\n⬜ <b>#{task_id}</b> — {text}\n\n"
        "Tap 📋 My Tasks to view it.", parse_mode="HTML", reply_markup=MENU,
    )


async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")
    bot = Bot(TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
