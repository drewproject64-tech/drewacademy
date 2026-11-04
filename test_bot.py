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
    async def test_start_normal_redirect_then_reverse(self):
        telegram = SimpleNamespace(send_message=AsyncMock(), copy_message=AsyncMock())
        message = SimpleNamespace(chat=SimpleNamespace(type='private', id=1),
                                  from_user=user(1), answer=AsyncMock(), bot=telegram)
        await bot.start(message)
        message.answer.assert_awaited_once_with(bot.DEFAULT_MESSAGE, reply_markup=bot.community_keyboard())
        bot.store.enable_redirect(99)
        message.answer.reset_mock()
        await bot.start(message)
        await bot.start(message)
        self.assertEqual(message.answer.await_count, 1)
        self.assertIn('updates are active', message.answer.await_args.args[0])
        self.assertEqual(telegram.send_message.await_count, 0)
        self.assertEqual(bot.store.next_rotation()['step'], 0)
        bot.store.reverse()
        await bot.start(message)
        self.assertEqual(message.answer.await_args.args[0], bot.DEFAULT_MESSAGE)

    async def test_two_workers_send_one_queued_post(self):
        bot.store.started(user(1))
        bot.store.campaign('one post')
        telegram = SimpleNamespace(send_message=AsyncMock())
        tasks = [asyncio.create_task(bot.worker(telegram)) for _ in range(2)]
        await asyncio.sleep(0.15)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        telegram.send_message.assert_awaited_once_with(1, 'one post')

    async def test_custom_intro_is_copied_once_by_worker(self):
        bot.store.set('redirect_chat', 99)
        bot.store.set('redirect_message', 123)
        bot.store.enable_redirect(99)
        telegram = SimpleNamespace(copy_message=AsyncMock(), send_message=AsyncMock())
        message = SimpleNamespace(chat=SimpleNamespace(type='private', id=1),
                                  from_user=user(1), answer=AsyncMock(), bot=telegram)
        await bot.start(message)
        task = asyncio.create_task(bot.rotation_worker(telegram))
        await asyncio.sleep(0.12)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        telegram.copy_message.assert_awaited_once_with(1, 99, 123)
        self.assertIsNone(bot.store.next_rotation())
        self.assertEqual(message.answer.await_count, 1)

    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        bot.store = Storage(self.directory.name + '/db')
        bot.ADMIN_ID = 99
        bot.composer.clear()
        bot.user_locks.clear()

    async def asyncTearDown(self):
        bot.store.db.close()
        self.directory.cleanup()

    async def test_unauthorized_redirect_does_not_change_mode(self):
        message = SimpleNamespace(text='/redirect', chat=SimpleNamespace(type='private', id=1),
                                  from_user=user(1), answer=AsyncMock())
        await bot.commands(message)
        self.assertEqual(bot.store.get('mode', 'normal'), 'normal')
        self.assertIn('Administrator only.', message.answer.await_args.args[0])

    async def test_admin_start_uses_normal_bot_response(self):
        message = SimpleNamespace(chat=SimpleNamespace(type='private', id=99),
                                  from_user=user(99), answer=AsyncMock())
        await bot.start(message)
        message.answer.assert_awaited_once()
        self.assertIn('admin controls', message.answer.await_args.args[0])
        self.assertIsInstance(message.answer.await_args.kwargs['reply_markup'],
                              bot.ReplyKeyboardMarkup)

    async def test_admin_command_still_opens_panel(self):
        message = SimpleNamespace(text='/admin', chat=SimpleNamespace(type='private', id=99),
                                  from_user=user(99), answer=AsyncMock())
        await bot.commands(message)
        self.assertIn('admin controls', message.answer.await_args.args[0])
        keyboard = message.answer.await_args.kwargs['reply_markup']
        self.assertIsInstance(keyboard, bot.ReplyKeyboardMarkup)
        self.assertEqual(
            [[b.text for b in row] for row in keyboard.keyboard],
            [['REDIRECT', 'REVERSE'],
             ['Preview All 5 Messages'],
             ['Users & Stats']])
        self.assertTrue(keyboard.is_persistent)
        self.assertTrue(keyboard.resize_keyboard)
        self.assertFalse(keyboard.one_time_keyboard)

    async def test_nonadmin_cannot_use_stats_or_send_buttons(self):
        for button in ('stats', 'confirm_redirect', 'send_draft:fake'):
            query = SimpleNamespace(from_user=user(1), data=button,
                message=SimpleNamespace(chat=SimpleNamespace(type='private', id=1), answer=AsyncMock()), answer=AsyncMock())
            await bot.callback(query)
            query.answer.assert_awaited_once_with('Administrator only.', show_alert=True)
            query.message.answer.assert_not_awaited()
        self.assertEqual(bot.store.get('mode', 'normal'), 'normal')

    async def test_custom_send_requires_confirmation(self):
        message = SimpleNamespace(text='/send Hello subscribers', chat=SimpleNamespace(type='private', id=99),
                                  from_user=user(99), answer=AsyncMock())
        await bot.commands(message)
        self.assertIsNone(bot.store.next_delivery())
        self.assertIn('Send broadcast', str(message.answer.await_args.kwargs['reply_markup']))
        self.assertIn('Hello subscribers', bot.store.get('draft'))

    async def test_worker_sends_saved_campaign(self):
        bot.store.started(user(1))
        bot.store.campaign('Offer')
        telegram = SimpleNamespace(send_message=AsyncMock(), copy_message=AsyncMock())
        task = asyncio.create_task(bot.worker(telegram))
        await asyncio.sleep(0.12)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        telegram.send_message.assert_awaited_once_with(1, 'Offer')
        self.assertIsNone(bot.store.next_delivery())

    async def test_ordinary_admin_message_does_not_broadcast(self):
        message = SimpleNamespace(text='hello', chat=SimpleNamespace(type='private', id=99), from_user=user(99))
        await bot.compose(message)
        self.assertEqual(bot.store.db.execute('SELECT COUNT(*) FROM campaigns').fetchone()[0], 0)

    async def test_rotation_first_post_has_community_button(self):
        bot.store.started(user(1))
        campaign = bot.store.enable_redirect(99)
        telegram = SimpleNamespace(send_message=AsyncMock(), copy_message=AsyncMock())
        task = asyncio.create_task(bot.rotation_worker(telegram))
        await asyncio.sleep(0.12)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        call = telegram.send_message.await_args
        self.assertIn('DREW FX | FOREX COMMUNITY', call.args[1])
        self.assertEqual(call.kwargs['reply_markup'].inline_keyboard[0][0].url, 'https://t.me/DrewFXHub')
        bot.store.started(user(2))
        self.assertEqual(bot.store.next_rotation()['campaign'], campaign)
        self.assertEqual(bot.store.next_rotation()['user_id'], 2)

    async def test_photo_rotation_uses_uploaded_images_and_english_captions(self):
        from pathlib import Path
        from rotation import TESTIMONIAL_IMAGES, MESSAGES, ADMIN_URL
        telegram = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock())
        for step in (1, 2, 3):
            with self.subTest(step=step):
                telegram.send_photo.reset_mock()
                telegram.send_message.reset_mock()
                await bot.send_rotation_payload(telegram, {'user_id': 123, 'step': step})
                telegram.send_photo.assert_awaited_once()
                telegram.send_message.assert_not_awaited()
                kwargs = telegram.send_photo.await_args.kwargs
                self.assertEqual(kwargs['chat_id'], 123)
                self.assertEqual(Path(kwargs['photo'].path).name, TESTIMONIAL_IMAGES[step])
                self.assertEqual(kwargs['caption'], MESSAGES[step][0])
                self.assertNotIn('independently verified', kwargs['caption'].lower())
                self.assertNotIn('trading involves risk', kwargs['caption'].lower())
                self.assertIn('English translation', kwargs['caption'])
                self.assertEqual(kwargs['reply_markup'].inline_keyboard[0][0].url, ADMIN_URL)

    async def test_missing_testimonial_photo_uses_english_caption_fallback(self):
        from rotation import MESSAGES
        telegram = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock())
        with patch.object(bot.Path, 'is_file', return_value=False):
            await bot.send_rotation_payload(telegram, {'user_id': 123, 'step': 2})
        telegram.send_photo.assert_not_awaited()
        telegram.send_message.assert_awaited_once()
        self.assertEqual(telegram.send_message.await_args.args[1], MESSAGES[2][0])

    async def test_final_offer_is_text_with_admin_button(self):
        from rotation import ADMIN_URL, MESSAGES
        telegram = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock())
        await bot.send_rotation_payload(telegram, {'user_id': 123, 'step': 4})
        telegram.send_photo.assert_not_awaited()
        telegram.send_message.assert_awaited_once()
        self.assertEqual(telegram.send_message.await_args.args[1], MESSAGES[4][0])
        self.assertEqual(telegram.send_message.await_args.kwargs['reply_markup'].inline_keyboard[0][0].url, ADMIN_URL)

    async def test_admin_receives_first_message_immediately_on_redirect_and_on_restart(self):
        bot.store.started(user(99))
        bot.store.started(user(1))
        api = SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock(),
                              copy_message=AsyncMock())
        message = SimpleNamespace(chat=SimpleNamespace(type='private', id=99),
                                  bot=api, edit_text=AsyncMock(), answer=AsyncMock())
        await bot.action(message, 'redirect', edit=True)
        self.assertEqual(api.send_message.await_count, 1)
        first = api.send_message.await_args
        self.assertEqual(first.args[0], 99)
        self.assertIn('DREW FX | FOREX COMMUNITY', first.args[1])
        self.assertEqual(first.kwargs['reply_markup'].inline_keyboard[0][0].url,
                         'https://t.me/DrewFXHub')
        self.assertEqual(bot.store.next_rotation()['user_id'], 1)
        self.assertEqual(bot.store.rotation_for_user(99), None)
        await bot.action(message, 'redirect', edit=True)
        self.assertEqual(api.send_message.await_count, 2)
        self.assertEqual(api.send_message.await_args.args[0], 99)
        self.assertEqual(bot.store.next_rotation()['step'], 0)

    async def test_admin_preview_five_messages_does_not_change_schedules(self):
        from rotation import MESSAGES
        bot.store.started(user(99))
        bot.store.started(user(1))
        campaign = bot.store.enable_redirect(99)
        api = SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock(),
                              copy_message=AsyncMock())
        message = SimpleNamespace(chat=SimpleNamespace(type='private', id=99),
                                  bot=api, answer=AsyncMock(), edit_text=AsyncMock())
        await bot.action(message, 'preview', edit=False)
        self.assertEqual(api.send_message.await_count, 2)
        self.assertEqual(api.send_photo.await_count, 3)
        self.assertEqual(message.answer.await_count, 2)
        self.assertEqual(bot.store.rotation_for_user(99)['step'], 0)
        self.assertEqual(bot.store.next_rotation()['campaign'], campaign)
        self.assertIn('DREW FX', MESSAGES[0][0])

    async def test_custom_redirect_intro_is_used_instead_of_default_intro(self):
        bot.store.started(user(1))
        bot.store.set('redirect_chat', 99)
        bot.store.set('redirect_message', 456)
        bot.store.enable_redirect(99)
        telegram = SimpleNamespace(copy_message=AsyncMock(), send_message=AsyncMock())
        task = asyncio.create_task(bot.rotation_worker(telegram))
        await asyncio.sleep(0.12)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        telegram.copy_message.assert_awaited_once_with(1, 99, 456)
        telegram.send_message.assert_not_awaited()



class AdminPanelReuseTests(BotTests):
    async def test_admin_removes_old_inline_panel_and_shows_bottom_keyboard(self):
        bot.store.set('admin_panel_message', '456')
        message = SimpleNamespace(text='/admin', chat=SimpleNamespace(type='private', id=99),
            from_user=user(99), answer=AsyncMock(),
            bot=SimpleNamespace(edit_message_reply_markup=AsyncMock()))
        await bot.commands(message)
        message.bot.edit_message_reply_markup.assert_awaited_once_with(
            chat_id=99, message_id=456, reply_markup=None)
        self.assertEqual(bot.store.get('admin_panel_message'), '')
        self.assertIsInstance(
            message.answer.await_args.kwargs['reply_markup'], bot.ReplyKeyboardMarkup)
        await bot.commands(message)
        message.bot.edit_message_reply_markup.assert_awaited_once()
        self.assertEqual(message.answer.await_count, 2)

    async def test_admin_keyboard_buttons_dispatch_without_inline_panel(self):
        bot.store.started(user(99))
        bot.store.started(user(1))
        api = SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock(),
                              copy_message=AsyncMock())
        for label in ('Users & Stats', 'Preview All 5 Messages', 'REDIRECT', 'REVERSE'):
            with self.subTest(label=label):
                message = SimpleNamespace(text=label, from_user=user(99),
                    chat=SimpleNamespace(type='private', id=99),
                    bot=api, answer=AsyncMock())
                await bot.compose(message)
                self.assertTrue(message.answer.await_count >= 1)
                self.assertIsNone(bot.composer.get(99))
        self.assertEqual(bot.store.get('mode'), 'normal')
        self.assertEqual(api.send_photo.await_count, 3)
        self.assertEqual(api.send_message.await_count, 3)
        self.assertEqual(bot.store.db.execute('SELECT COUNT(*) FROM campaigns').fetchone()[0], 1)

    async def test_compose_mode_does_not_intercept_admin_keyboard_buttons(self):
        bot.store.started(user(99))
        bot.composer[99] = 'broadcast'
        message = SimpleNamespace(text='Users & Stats', from_user=user(99),
            chat=SimpleNamespace(type='private', id=99), answer=AsyncMock())
        await bot.compose(message)
        self.assertEqual(bot.composer.get(99), 'broadcast')
        self.assertIn('Total users', message.answer.await_args.args[0])
        self.assertEqual(bot.store.db.execute('SELECT COUNT(*) FROM campaigns').fetchone()[0], 0)

    async def test_nonadmin_text_cannot_control_admin_keyboard_actions(self):
        bot.store.started(user(1))
        api = SimpleNamespace(send_message=AsyncMock())
        message = SimpleNamespace(text='REDIRECT', from_user=user(1),
            chat=SimpleNamespace(type='private', id=1), bot=api,
            answer=AsyncMock())
        await bot.compose(message)
        self.assertEqual(bot.store.get('mode'), 'normal')
        message.answer.assert_not_awaited()

    async def test_legacy_callback_removes_its_own_inline_panel(self):
        message = SimpleNamespace(chat=SimpleNamespace(type='private', id=99),
            edit_text=AsyncMock(), answer=AsyncMock(),
            bot=SimpleNamespace(send_message=AsyncMock()))
        await bot.action(message, 'redirect', edit=True)
        message.edit_text.assert_awaited_once()
        self.assertIsNone(message.edit_text.await_args.kwargs['reply_markup'])
        message.answer.assert_not_awaited()
