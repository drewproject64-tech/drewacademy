import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch
import bot
from storage import Storage
from test_storage import user


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        bot.store = Storage(self.directory.name + '/db')
        bot.ADMIN_ID = 99
        bot.composer.clear()

    async def asyncTearDown(self):
        bot.store.db.close()
        self.directory.cleanup()

    async def test_unauthorized_redirect_does_not_change_mode(self):
        message = SimpleNamespace(text='/redirect', chat=SimpleNamespace(type='private', id=1),
                                  from_user=user(1), answer=AsyncMock())
        await bot.commands(message)
        self.assertEqual(bot.store.get('mode', 'normal'), 'normal')
        message.answer.assert_awaited_once_with('Administrator only.')

    async def test_worker_sends_saved_campaign(self):
        bot.store.started(user(1))
        bot.store.campaign('Offer')
        telegram = SimpleNamespace(send_message=AsyncMock(), copy_message=AsyncMock())
        task = asyncio.create_task(bot.worker(telegram))
        await asyncio.sleep(0.02)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        telegram.send_message.assert_awaited_once_with(1, 'Offer')
        self.assertIsNone(bot.store.next_delivery())

    async def test_ordinary_admin_message_does_not_broadcast(self):
        message = SimpleNamespace(text='hello', chat=SimpleNamespace(type='private', id=99), from_user=user(99))
        await bot.compose(message)
        self.assertEqual(bot.store.db.execute('SELECT COUNT(*) FROM campaigns').fetchone()[0], 0)

    async def test_reverse_personalizes_and_adds_join_button(self):
        bot.store.started(user(1))
        campaign = bot.store.reverse()
        telegram = SimpleNamespace(send_message=AsyncMock(), copy_message=AsyncMock())
        task = asyncio.create_task(bot.worker(telegram))
        await asyncio.sleep(0.02)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        call = telegram.send_message.await_args
        self.assertTrue(call.args[1].startswith('Test, DON’T MISS OUT AGAIN! 🔥'))
        self.assertEqual(call.kwargs['reply_markup'].inline_keyboard[0][0].url, 'https://t.me/Drewcommunity')
        bot.store.started(user(2))
        self.assertEqual(bot.store.next_delivery()['id'], campaign)
        self.assertEqual(bot.store.next_delivery()['user_id'], 2)

    async def test_reverse_attaches_uploaded_image(self):
        bot.store.started(user(1))
        bot.store.reverse()
        telegram = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock())
        with patch.object(bot.Path, 'is_file', return_value=True):
            task = asyncio.create_task(bot.worker(telegram))
            await asyncio.sleep(0.02)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        call = telegram.send_photo.await_args
        self.assertTrue(call.kwargs['caption'].startswith('Test, DON’T MISS OUT AGAIN!'))
        self.assertEqual(call.kwargs['reply_markup'].inline_keyboard[0][0].url, 'https://t.me/Drewcommunity')
        telegram.send_message.assert_not_awaited()
