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
    if admin(message):
        await dbcall('save_user', message.from_user)
        await message.answer('Administrator controls', reply_markup=panel())
        return
    await dbcall('started', message.from_user)
    if await dbcall('get', 'mode') == 'redirect':
        await message.answer('Welcome to Drew FX. The community message is queued. /stop stops broadcasts.')
        return  # The persistent queue sends the image and caption.
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


async def worker(bot):
    while True:
        try:
            row = await dbcall('next_delivery')
        except Exception:
            logging.warning('Database temporarily unavailable; delivery queue will retry.')
            await asyncio.sleep(5)
            continue
        if not row:
            await asyncio.sleep(1)
            continue
        try:
            if not await dbcall('deliverable', row['id'], row['user_id']):
                continue
            if row['source_chat'] is not None:
                await bot.copy_message(row['user_id'], row['source_chat'], row['source_message'])
            elif row['text'] == REVERSE_MESSAGE:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                    text='Join DREW FX Community', url='https://t.me/Drewcommunity')]])
                text = REVERSE_MESSAGE.format(name=row['first_name'] or 'Friend')
                if REVERSE_IMAGE.is_file():
                    await bot.send_photo(row['user_id'], FSInputFile(REVERSE_IMAGE), caption=text,
                                         reply_markup=keyboard)
                else:
                    await bot.send_message(row['user_id'], text, reply_markup=keyboard)
            else:
                await bot.send_message(row['user_id'], row['text'])
        except TelegramRetryAfter as error:
            await asyncio.sleep(error.retry_after + 1)
            continue
        except TelegramForbiddenError:
            await dbcall('finish', row['id'], row['user_id'], 'blocked')
        except TelegramBadRequest:
            logging.warning('Permanent delivery failure for campaign %s', row['id'])
            await dbcall('finish', row['id'], row['user_id'], 'failed')
        except (TelegramNetworkError, OSError):
            await asyncio.sleep(5)
            continue
        except Exception:
            logging.warning('Delivery failed temporarily; retrying queue after a delay.')
            await asyncio.sleep(5)
        else:
            try:
                await dbcall('finish', row['id'], row['user_id'], 'sent')
            except Exception:
                logging.warning('Delivery not recorded; queue will retry.')
                await asyncio.sleep(5)
        await asyncio.sleep(0.1)


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
    task = asyncio.create_task(worker(bot))
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(store.close)
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())

