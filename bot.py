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

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Add Task"), KeyboardButton(text="📋 My Tasks")],
        [KeyboardButton(text="❓ How to Use")],
    ],
    resize_keyboard=True,
)

WELCOME = (
    "👋 <b>Welcome to Drew Bot!</b>\n\n"
    "📝 A simple to-do list to help you stay organized.\n\n"
    "You can add tasks, view your saved tasks, mark them complete, or delete them.\n\n"
    "<b>Try it now:</b> tap <b>📝 Add Task</b> and send <code>Buy groceries</code>.\n\n"
    "Choose an option below 👇"
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
    return conn


def task_keyboard(task_id: int, completed: bool):
    buttons = []
    if not completed:
        buttons.append(KeyboardButton(text=f"✅ Complete {task_id}"))
    buttons.append(KeyboardButton(text=f"🗑️ Delete {task_id}"))
    return ReplyKeyboardMarkup(keyboard=[buttons, [KeyboardButton(text="📋 My Tasks")], [KeyboardButton(text="📝 Add Task")]], resize_keyboard=True)


async def start(message: Message):
    await message.answer(WELCOME, parse_mode="HTML", reply_markup=MENU)


@dp.message(Command("help"))
@dp.message(F.text == "❓ How to Use")
async def help_message(message: Message):
    await message.answer(
        "❓ <b>HOW TO USE</b>\n\n"
        "📝 <b>Add Task</b> — save a new task.\n"
        "📋 <b>My Tasks</b> — view your saved tasks.\n"
        "✅ <b>Complete</b> — mark a task as completed.\n"
        "🗑️ <b>Delete</b> — remove a task.\n\n"
        "Your tasks are stored separately for your Telegram account.\n\n"
        "Example: tap <b>📝 Add Task</b> and send <code>Buy groceries</code>.",
        parse_mode="HTML", reply_markup=MENU,
    )


@dp.message(F.text == "📝 Add Task")
async def add_task(message: Message):
    await message.answer(
        "📝 <b>ADD A TASK</b>\n\n"
        "Send the task you want to save.\n\n"
        "Example: <code>Buy groceries</code>",
        parse_mode="HTML", reply_markup=MENU,
    )
    # Next ordinary text is treated as a task unless it is a menu action.
    message.bot.session if False else None
    # Aiogram FSM is intentionally avoided for this small bot; use a per-user flag in dispatcher data.
    dp.workflow_data.setdefault("adding_users", set()).add(message.from_user.id)


@dp.message(F.text == "📋 My Tasks")
async def my_tasks(message: Message):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, text, completed FROM tasks WHERE user_id=? ORDER BY completed, id",
        (message.from_user.id,),
    ).fetchall()
    conn.close()
    if not rows:
        await message.answer("📋 <b>MY TASKS</b>\n\nYou don't have any tasks yet.\n\nTap 📝 Add Task to create one.", parse_mode="HTML", reply_markup=MENU)
        return
    lines = ["📋 <b>MY TASKS</b>\n"]
    for task_id, text, completed in rows:
        status = "✅" if completed else "⬜"
        lines.append(f"{status} <b>#{task_id}</b> — {text}")
    lines.append("\nTo manage a task, send <code>complete ID</code> or <code>delete ID</code>.\nExample: <code>complete 1</code>")
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=MENU)


@dp.message(F.text.regexp(r"^complete\s+\d+$"))
async def complete_task(message: Message):
    task_id = int(message.text.split()[1])
    conn = get_db()
    cur = conn.execute("UPDATE tasks SET completed=1 WHERE id=? AND user_id=?", (task_id, message.from_user.id))
    conn.commit(); conn.close()
    if cur.rowcount:
        await message.answer(f"✅ Task #{task_id} marked as completed.", reply_markup=MENU)
    else:
        await message.answer("I couldn't find that task in your list.", reply_markup=MENU)


@dp.message(F.text.regexp(r"^delete\s+\d+$"))
async def delete_task(message: Message):
    task_id = int(message.text.split()[1])
    conn = get_db()
    cur = conn.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, message.from_user.id))
    conn.commit(); conn.close()
    if cur.rowcount:
        await message.answer(f"🗑️ Task #{task_id} deleted.", reply_markup=MENU)
    else:
        await message.answer("I couldn't find that task in your list.", reply_markup=MENU)


@dp.message(F.text)
async def receive_task(message: Message):
    menu_text = {"📝 Add Task", "📋 My Tasks", "❓ How to Use"}
    if message.text in menu_text:
        return
    adding_users = dp.workflow_data.setdefault("adding_users", set())
    if message.from_user.id not in adding_users:
        await message.answer("Choose an option below to get started 👇", reply_markup=MENU)
        return
    text = message.text.strip()
    if not text:
        await message.answer("Please send a task with some text.", reply_markup=MENU)
        return
    conn = get_db()
    cur = conn.execute("INSERT INTO tasks (user_id, text) VALUES (?, ?)", (message.from_user.id, text))
    task_id = cur.lastrowid
    conn.commit(); conn.close()
    adding_users.discard(message.from_user.id)
    await message.answer(f"✅ <b>Task saved!</b>\n\n#{task_id} — {text}\n\nTap 📋 My Tasks to manage it.", parse_mode="HTML", reply_markup=MENU)


async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")
    bot = Bot(TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
