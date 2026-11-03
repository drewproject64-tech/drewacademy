import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, BotCommand, BotCommandScopeChat, BotCommandScopeDefault, MenuButtonCommands
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError
from aiogram import BaseMiddleware
from uuid import uuid4
from storage import Storage, DEFAULT_MESSAGE, REVERSE_MESSAGE

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()
store = None
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
composer = {}
user_locks = {}


def delivery_lock(user_id):
    return user_locks.setdefault(user_id, asyncio.Lock())
REVERSE_IMAGE = Path(__file__).resolve().parent / 'assets' / 'drew_fx_bull.png'


async def dbcall(method, *args):
    def run():
        with store.transaction():
            return getattr(store, method)(*args)
    return await asyncio.to_thread(run)


class TrackUsers(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, 'from_user', None)
        chat = getattr(event, 'chat', None) or getattr(getattr(event, 'message', None), 'chat', None)
        if user and chat and chat.type == 'private':
            await dbcall('save_user', user)
        return await handler(event, data)


def confirmation(action, label='Confirm'):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data=action),
        InlineKeyboardButton(text='Cancel', callback_data='cancel')]])


def panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='REDIRECT', callback_data='redirect'), InlineKeyboardButton(text='REVERSE', callback_data='reverse')],
        [InlineKeyboardButton(text='Edit Redirect Message', callback_data='set_redirect')],
        [InlineKeyboardButton(text='Broadcast Message / Offer', callback_data='broadcast')],
        [InlineKeyboardButton(text='Users & Stats', callback_data='stats')],
        [InlineKeyboardButton(text='Cancel', callback_data='cancel')]])


def admin(message):
    return message.chat.type == 'private' and message.from_user and message.from_user.id == ADMIN_ID


@dp.message(CommandStart())
async def start(message: Message):
    if message.chat.type != 'private' or not message.from_user:
        return
    composer.pop(message.chat.id, None)
    async with delivery_lock(message.from_user.id):
        row = await dbcall('start_payload', message.from_user)
        if row:
            await send_payload(message.bot, row)
        else:
            await message.answer(DEFAULT_MESSAGE)


@dp.message(Command('admin', 'redirect', 'reverse', 'send', 'cancel', 'help', 'id'))
async def commands(message: Message):
    command = message.text.split()[0].split('@')[0].lower()
    if command == '/id':
        await message.answer(f'Your Telegram user ID: {message.from_user.id}')
        return
    if command == '/help':
        await message.answer('Use /start to open the bot. /stop opts out of broadcasts.' +
                             ('\n/admin — controls\n/redirect — enable and broadcast\n/reverse — normal mode\n/send MESSAGE — broadcast\n/cancel — close composer' if admin(message) else ''))
        return
    if not admin(message):
        await message.answer(f'Administrator only. Your Telegram user ID is {message.from_user.id}. If you own this bot, set ADMIN_ID to this number in Render, then redeploy.')
        return
    if command == '/send':
        text = message.text.partition(' ')[2].strip()
        if not text:
            await message.answer('Usage: /send MESSAGE')
            return
        await draft(message, text=text)
    else:
        await action(message, command[1:])


async def action(message, name):
    if name == 'redirect':
        composer.pop(message.chat.id, None)
        await message.answer('Enable redirect and send the saved community message to active users? Repeated activation while enabled will not resend.', reply_markup=confirmation('confirm_redirect', 'Enable redirect'))
    elif name == 'reverse':
        composer.pop(message.chat.id, None)
        await dbcall('reverse')
        await message.answer('Normal mode restored. New /start requests receive the original XAUUSD message. Pending redirect deliveries stopped.')
    elif name in ('broadcast', 'set_redirect'):
        composer[message.chat.id] = name
        await message.answer('Send the text, photo, video or other single message to use. /cancel to cancel.' +
                             (' It will be broadcast to saved users.' if name == 'broadcast' else ' It will be saved; click REDIRECT to send it.'))
    elif name == 'stats':
        await message.answer(await dbcall('stats'), reply_markup=panel())
    elif name == 'cancel':
        composer.pop(message.chat.id, None)
        await dbcall('set', 'draft', '')
        await message.answer('Composer cancelled.', reply_markup=panel())
    else:
        await message.answer('Administrator controls', reply_markup=panel())


@dp.callback_query()
async def callback(query: CallbackQuery):
    if query.from_user.id != ADMIN_ID or not query.message or query.message.chat.type != 'private':
        await query.answer('Administrator only.', show_alert=True)
        return
    await query.answer()
    if query.data == 'confirm_redirect':
        campaign = await dbcall('enable_redirect', ADMIN_ID)
        await query.message.answer(f'Redirect enabled. Campaign #{campaign}.', reply_markup=panel())
    elif query.data and query.data.startswith('send_draft:'):
        campaign = await dbcall('confirm_draft', query.data.split(':', 1)[1], ADMIN_ID)
        if campaign is None:
            await query.message.answer('This preview has expired. Compose a new message.')
            return
        await query.message.answer(f'Broadcast #{campaign} queued.', reply_markup=panel())
    else:
        await action(query.message, query.data)


@dp.message(Command('stop'))
async def stop(message: Message):
    if message.chat.type == 'private':
        await dbcall('save_user', message.from_user)
        await dbcall('deactivate', message.chat.id)
        await message.answer('Broadcasts stopped. /start opts in again.')


@dp.message()
async def compose(message: Message):
    if message.chat.type != 'private' or not message.from_user:
        return
    if not admin(message):
        await dbcall('save_user', message.from_user)
        return
    mode = composer.pop(message.chat.id, None)
    if not mode:
        if message.text and message.text.upper() in ('REDIRECT', 'REVERSE'):
            await action(message, message.text.lower())
        return
    if message.media_group_id:
        composer[message.chat.id] = mode
        await message.answer('Please send one message or one photo, rather than an album.')
        return
    # Preview verifies that Telegram can copy this content before queueing it.
    try:
        preview = await message.bot.copy_message(message.chat.id, message.chat.id, message.message_id)
    except TelegramBadRequest:
        composer[message.chat.id] = mode
        await message.answer('This message cannot be copied. Send text, a photo or a video.')
        return
    if mode == 'set_redirect':
        await dbcall('set', 'redirect_chat', message.chat.id)
        await dbcall('set', 'redirect_message', preview.message_id)
        await message.answer('Redirect message saved for the next activation. If redirect is already enabled, use REVERSE first, then REDIRECT.', reply_markup=panel())
    else:
        await draft(message, source_chat=message.chat.id, source_message=preview.message_id)


async def draft(message, text=None, source_chat=None, source_message=None):
    import json
    nonce = uuid4().hex[:16]
    await dbcall('set', 'draft', json.dumps({'nonce': nonce, 'text': text, 'chat': source_chat, 'message': source_message}))
    if text:
        await message.answer(text)
    await message.answer('Preview ready. Send this message to active saved users?',
                         reply_markup=confirmation('send_draft:' + nonce, 'Send broadcast'))


async def send_payload(bot, row):
    if row['source_chat'] is not None:
        await bot.copy_message(row['user_id'], row['source_chat'], row['source_message'])
    elif row['text'] == REVERSE_MESSAGE:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text='Join DREW FX Community', url='https://t.me/DrewFXHub')]])
        text = REVERSE_MESSAGE.format(name=row['first_name'] or 'Friend')
        if REVERSE_IMAGE.is_file():
            await bot.send_photo(row['user_id'], FSInputFile(REVERSE_IMAGE), caption=text, reply_markup=keyboard)
        else:
            await bot.send_message(row['user_id'], text, reply_markup=keyboard)
    else:
        await bot.send_message(row['user_id'], row['text'])


async def worker(bot):
    while True:
        try:
            row = await dbcall('next_delivery')
            if not row:
                await asyncio.sleep(1)
                continue
            async with delivery_lock(row['user_id']):
                if not await dbcall('claim_delivery', row['id'], row['user_id']):
                    continue
                try:
                    await send_payload(bot, row)
                except TelegramRetryAfter as error:
                    await dbcall('finish', row['id'], row['user_id'], 'pending')
                    await asyncio.sleep(error.retry_after + 1)
                except TelegramForbiddenError:
                    await dbcall('finish', row['id'], row['user_id'], 'blocked')
                except TelegramBadRequest:
                    logging.warning('Permanent delivery failure for campaign %s', row['id'])
                    await dbcall('finish', row['id'], row['user_id'], 'failed')
                except (TelegramNetworkError, OSError):
                    await dbcall('finish', row['id'], row['user_id'], 'pending')
                    await asyncio.sleep(5)
                else:
                    await dbcall('finish', row['id'], row['user_id'], 'sent')
            await asyncio.sleep(0.1)
        except Exception:
            # An uncertain send/commit remains 'sending' for restart recovery,
            # rather than repeatedly sending the same post in a tight loop.
            logging.exception('Delivery worker error')
            await asyncio.sleep(5)


async def acquire_worker_lease(database_url, stop_event):
    """Use a separate PostgreSQL session to serialize Render rollouts."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    connection = conninfo_to_dict(database_url)
    # Neon transaction pooling cannot retain session advisory locks.
    connection['host'] = connection.get('host', '').replace('-pooler.', '.')
    connection.update(sslmode='require', connect_timeout='15')
    conn = await psycopg.AsyncConnection.connect(**connection, autocommit=True)
    try:
        while not stop_event.is_set():
            cursor = await conn.execute('SELECT pg_try_advisory_lock(8860598557)')
            if (await cursor.fetchone())[0]:
                logging.info('Exclusive bot worker lease acquired.')
                return conn
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass
        raise asyncio.CancelledError
    except BaseException:
        await conn.close()
        raise


async def watch_lease(conn):
    # Exit on a lost lease instead of allowing two independent pollers.
    while True:
        await asyncio.sleep(5)
        await conn.execute('SELECT 1')


async def main():
    global store
    token = os.getenv('BOT_TOKEN')
    if not token or ADMIN_ID <= 0:
        raise RuntimeError('Set BOT_TOKEN and ADMIN_ID (your numeric Telegram user ID)')
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise RuntimeError('Set DATABASE_URL to the Neon PostgreSQL connection string')
    store = await asyncio.to_thread(Storage, database_url)
    logging.info('Neon database initialized; user registry and queue ready.')
    dp.message.outer_middleware(TrackUsers())
    dp.callback_query.outer_middleware(TrackUsers())
    if not REVERSE_IMAGE.is_file():
        logging.warning('Upload assets/drew_fx_bull.png to include the reverse broadcast image; sending text until available.')
    bot = Bot(token=token)
    await bot.set_my_commands([BotCommand(command='start', description='Open Drew FX'),
                               BotCommand(command='help', description='Help'),
                               BotCommand(command='stop', description='Stop broadcasts')], scope=BotCommandScopeDefault())
    await bot.set_my_commands([BotCommand(command='admin', description='Admin panel'),
                               BotCommand(command='start', description='Open bot'),
                               BotCommand(command='cancel', description='Cancel composer')], scope=BotCommandScopeChat(chat_id=ADMIN_ID))
    await bot.set_chat_menu_button(chat_id=ADMIN_ID, menu_button=MenuButtonCommands())
    logging.info('Admin-only command menu configured.')
    import signal
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)
    lease = await acquire_worker_lease(database_url, stop_event)
    await dbcall('recover_deliveries')
    task = asyncio.create_task(worker(bot))
    polling = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    shutdown = asyncio.create_task(stop_event.wait())
    heartbeat = asyncio.create_task(watch_lease(lease))
    try:
        done, _ = await asyncio.wait([polling, shutdown, heartbeat], return_when=asyncio.FIRST_COMPLETED)
        for finished in done:
            if finished is not shutdown:
                finished.result()
    finally:
        for running in (task, polling, shutdown, heartbeat):
            running.cancel()
        await asyncio.gather(task, polling, shutdown, heartbeat, return_exceptions=True)
        await lease.close()
        await asyncio.to_thread(store.close)
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())


