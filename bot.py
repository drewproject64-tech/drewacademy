import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError
from storage import Storage, DEFAULT_MESSAGE, REVERSE_MESSAGE

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()
store = None
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
composer = {}
REVERSE_IMAGE = Path(__file__).resolve().parent / 'assets' / 'drew_fx_bull.png'


def panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='REDIRECT', callback_data='redirect'), InlineKeyboardButton(text='REVERSE', callback_data='reverse')],
        [InlineKeyboardButton(text='Set Redirect Message', callback_data='set_redirect')],
        [InlineKeyboardButton(text='Broadcast Message / Offer', callback_data='broadcast')],
        [InlineKeyboardButton(text='Users & Stats', callback_data='stats')],
        [InlineKeyboardButton(text='Cancel', callback_data='cancel')]])


def admin(message):
    return message.chat.type == 'private' and message.from_user and message.from_user.id == ADMIN_ID


@dp.message(CommandStart())
async def start(message: Message):
    if message.chat.type != 'private' or not message.from_user:
        return
    store.started(message.from_user)
    if admin(message):
        await message.answer('Administrator controls', reply_markup=panel())
        return
    if store.get('mode') == 'redirect' or store.get('normal_campaign'):
        await message.answer('Welcome! Your channel message will arrive shortly.')
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
        campaign = store.campaign(text)
        await message.answer(f'Broadcast #{campaign} queued. Use Users & Stats to check deliveries.')
    else:
        await action(message, command[1:])


async def action(message, name):
    if name == 'redirect':
        composer.pop(message.chat.id, None)
        campaign = store.enable_redirect()
        await message.answer(f'Redirect enabled. Broadcast #{campaign} queued for saved users; new starters are included.')
    elif name == 'reverse':
        composer.pop(message.chat.id, None)
        campaign = store.reverse()
        await message.answer(f'Reverse enabled. Personalized DREW FX broadcast #{campaign} queued with the Join Community button. New starters are included.')
    elif name in ('broadcast', 'set_redirect'):
        composer[message.chat.id] = name
        await message.answer('Send the text, photo, video or other single message to use. /cancel to cancel.' +
                             (' It will be broadcast to saved users.' if name == 'broadcast' else ' It will be saved; click REDIRECT to send it.'))
    elif name == 'stats':
        await message.answer(store.stats())
    elif name == 'cancel':
        composer.pop(message.chat.id, None)
        await message.answer('Composer cancelled.')
    else:
        await message.answer('Administrator controls', reply_markup=panel())


@dp.callback_query()
async def callback(query: CallbackQuery):
    if query.from_user.id != ADMIN_ID or not query.message or query.message.chat.type != 'private':
        await query.answer('Administrator only.', show_alert=True)
        return
    await query.answer()
    await action(query.message, query.data)


@dp.message(Command('stop'))
async def stop(message: Message):
    if message.chat.type == 'private':
        with store.db:
            store.db.execute('UPDATE users SET active=0 WHERE id=?', (message.chat.id,))
        await message.answer('Broadcasts stopped. /start opts in again.')


@dp.message()
async def compose(message: Message):
    if message.chat.type != 'private' or not message.from_user:
        return
    if not admin(message):
        store.save_user(message.from_user)
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
        store.set('redirect_chat', message.chat.id)
        store.set('redirect_message', preview.message_id)
        await message.answer('Redirect message saved. Click REDIRECT to enable and broadcast it.', reply_markup=panel())
    else:
        campaign = store.campaign(source_chat=message.chat.id, source_message=preview.message_id)
        await message.answer(f'Broadcast #{campaign} queued.', reply_markup=panel())


async def worker(bot):
    while True:
        row = store.next_delivery()
        if not row:
            await asyncio.sleep(1)
            continue
        try:
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
            store.finish(row['id'], row['user_id'], 'blocked')
        except TelegramBadRequest:
            logging.exception('Delivery failed for campaign %s', row['id'])
            store.finish(row['id'], row['user_id'], 'failed')
        except (TelegramNetworkError, OSError):
            await asyncio.sleep(5)
            continue
        else:
            store.finish(row['id'], row['user_id'], 'sent')
        await asyncio.sleep(0.1)


async def main():
    global store
    token = os.getenv('BOT_TOKEN')
    if not token or ADMIN_ID <= 0:
        raise RuntimeError('Set BOT_TOKEN and ADMIN_ID (your numeric Telegram user ID)')
    store = Storage(os.getenv('DATABASE_PATH', 'data/drewacademy.db'))
    if not REVERSE_IMAGE.is_file():
        logging.warning('Upload assets/drew_fx_bull.png to include the reverse broadcast image; sending text until available.')
    bot = Bot(token=token)
    task = asyncio.create_task(worker(bot))
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        store.db.close()
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
