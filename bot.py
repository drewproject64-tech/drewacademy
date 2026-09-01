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
USER_STATE = {}

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
    "📝 Drew Bot is a simple Telegram to-do list for creating, saving, viewing, completing, and deleting your tasks.\n\n"
    "🚀 <b>Try it:</b> tap 📝 Add Task, send <code>Buy groceries</code>, then tap 📋 My Tasks.\n\n"
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


def get_task(user_id, task_id):
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT id, text, completed FROM tasks WHERE id=? AND user_id=?",
            (task_id, user_id),
        ).fetchone()


async def start(message: Message):
    USER_STATE.pop(message.from_user.id, None)
    await message.answer(WELCOME, parse_mode="HTML", reply_markup=MENU)


@dp.message(CommandStart())
async def start_command(message: Message):
    await start(message)


@dp.message(Command("help"))
@dp.message(F.text == "❓ How to Use")
async def help_message(message: Message):
    USER_STATE.pop(message.from_user.id, None)
    await message.answer(
        "❓ <b>HOW TO USE DREW BOT</b>\n\n"
        "📝 <b>Add Task</b> — create and save a task.\n"
        "📋 <b>My Tasks</b> — view your saved tasks and IDs.\n"
        "✅ <b>Complete Task</b> — choose a task ID and mark it complete.\n"
        "🗑️ <b>Delete Task</b> — choose a task ID and remove it.\n\n"
        "💡 <b>Quick example:</b> Add Task → <code>Buy groceries</code> → My Tasks → Complete Task → <code>1</code>.",
        parse_mode="HTML", reply_markup=MENU,
    )


@dp.message(F.text == "🏠 Main Menu")
async def main_menu(message: Message):
    USER_STATE.pop(message.from_user.id, None)
    await message.answer(WELCOME, parse_mode="HTML", reply_markup=MENU)


@dp.message(F.text == "📝 Add Task")
async def add_task(message: Message):
    USER_STATE[message.from_user.id] = "add"
    await message.answer(
        "📝 <b>ADD A TASK</b>\n\n"
        "Send the task you want to save.\n\n"
        "💡 Example: <code>Buy groceries</code>\n\n"
        "Type /cancel to stop.",
        parse_mode="HTML", reply_markup=MENU,
    )


@dp.message(F.text == "📋 My Tasks")
async def my_tasks(message: Message):
    USER_STATE.pop(message.from_user.id, None)
    rows = get_tasks(message.from_user.id)
    if not rows:
        await message.answer(
            "📋 <b>MY TASKS</b>\n\nYour list is empty.\n\n"
            "Tap 📝 Add Task and send <code>Buy groceries</code> to create your first task.",
            parse_mode="HTML", reply_markup=MENU,
        )
        return

    lines = ["📋 <b>MY TASKS</b>\n"]
    for task_id, text, completed in rows:
        lines.append(f"{'✅' if completed else '⬜'} <b>#{task_id}</b> — {text}")
    lines.append("\nTap ✅ Complete Task or 🗑️ Delete Task, then enter the task ID.")
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=MENU)


@dp.message(F.text == "✅ Complete Task")
async def complete_prompt(message: Message):
    rows = get_tasks(message.from_user.id)
    if not rows:
        USER_STATE.pop(message.from_user.id, None)
        await message.answer("📋 You have no tasks yet. Tap 📝 Add Task first.", reply_markup=MENU)
        return
    USER_STATE[message.from_user.id] = "complete"
    await message.answer(
        "✅ <b>COMPLETE A TASK</b>\n\n"
        "Enter the task ID to mark as completed.\n\n"
        "Example: <code>1</code>",
        parse_mode="HTML", reply_markup=MENU,
    )


@dp.message(F.text == "🗑️ Delete Task")
async def delete_prompt(message: Message):
    rows = get_tasks(message.from_user.id)
    if not rows:
        USER_STATE.pop(message.from_user.id, None)
        await message.answer("📋 You have no tasks to delete.", reply_markup=MENU)
        return
    USER_STATE[message.from_user.id] = "delete"
    await message.answer(
        "🗑️ <b>DELETE A TASK</b>\n\n"
        "Enter the task ID to delete.\n\n"
        "Example: <code>1</code>",
        parse_mode="HTML", reply_markup=MENU,
    )


@dp.message(Command("cancel"))
async def cancel(message: Message):
    USER_STATE.pop(message.from_user.id, None)
    await message.answer("❌ Action cancelled. Choose another option below.", reply_markup=MENU)


async def receive_text(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    state = USER_STATE.get(user_id)

    if state in {"complete", "delete"}:
        if not text.isdigit():
            await message.answer("Please enter a numeric task ID, for example <code>1</code>.", parse_mode="HTML", reply_markup=MENU)
            return
        task_id = int(text)
        action = state
        USER_STATE.pop(user_id, None)
        task = get_task(user_id, task_id)
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
        return

    if state == "add":
        if len(text) > 500:
            await message.answer("Please keep each task under 500 characters.", reply_markup=MENU)
            return
        with closing(get_db()) as conn:
            cur = conn.execute("INSERT INTO tasks (user_id, text) VALUES (?, ?)", (user_id, text))
            task_id = cur.lastrowid
            conn.commit()
        USER_STATE.pop(user_id, None)
        await message.answer(
            f"✅ <b>Task saved!</b>\n\n⬜ <b>#{task_id}</b> — {text}\n\n"
            "Tap 📋 My Tasks to view it.", parse_mode="HTML", reply_markup=MENU,
        )
        return

    await message.answer(
        "👋 <b>Ready to organize your tasks?</b>\n\n"
        "Tap 📝 Add Task and send <code>Buy groceries</code> to try the bot.",
        parse_mode="HTML", reply_markup=MENU,
    )


@dp.message(F.text)
async def text_handler(message: Message):
    menu_items = {"📝 Add Task", "📋 My Tasks", "✅ Complete Task", "🗑️ Delete Task", "❓ How to Use", "🏠 Main Menu"}
    if message.text in menu_items:
        return
    await receive_text(message)


async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")
    bot = Bot(TOKEN)
    get_db().close()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
