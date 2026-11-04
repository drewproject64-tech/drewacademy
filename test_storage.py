import tempfile
import unittest
from types import SimpleNamespace
from storage import Storage


def user(id):
    return SimpleNamespace(id=id, username='name', first_name='Test', last_name=None, language_code='en')


class StorageTests(unittest.TestCase):
    def test_redirect_new_existing_reverse_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = directory + '/bot.db'
            s = Storage(path)
            s.started(user(1))
            campaign = s.enable_redirect()
            self.assertEqual(s.next_rotation()['user_id'], 1)
            self.assertTrue(s.claim_rotation(campaign, 1, 0))
            s.finish_rotation(campaign, 1, 0, 'sent')
            s.started(user(1))
            self.assertIsNone(s.next_rotation())
            s.started(user(2))
            s.db.close()
            s = Storage(path)
            self.assertEqual(s.next_rotation()['user_id'], 2)
            s.reverse()
            self.assertIsNone(s.next_rotation())
            s.campaign('Special offer')
            self.assertEqual(s.next_delivery()['text'], 'Special offer')
            self.assertEqual(s.db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 2)
            s.db.close()

    def test_blocked_users_and_opt_out(self):
        with tempfile.TemporaryDirectory() as directory:
            s = Storage(directory + '/bot.db')
            s.started(user(1))
            campaign = s.campaign('hello')
            s.finish(campaign, 1, 'blocked')
            s.save_user(user(1))
            s.campaign('next')
            self.assertIsNone(s.next_delivery())
            s.started(user(1))
            s.campaign('back')
            self.assertIsNotNone(s.next_delivery())
            s.db.close()


if __name__ == '__main__':
    unittest.main()


class RefinedStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.s = Storage(self.directory.name + '/db')

    def tearDown(self):
        self.s.close()
        self.directory.cleanup()

    def test_redirect_is_idempotent_and_reverse_preserves_manual_broadcast(self):
        self.s.started(user(1))
        first = self.s.enable_redirect()
        self.assertEqual(first, self.s.enable_redirect())
        manual = self.s.campaign('custom')
        self.s.reverse()
        self.assertIsNone(self.s.next_rotation())
        self.assertTrue(self.s.deliverable(manual, 1))
        self.assertNotEqual(first, self.s.enable_redirect())

    def test_opt_out_not_reactivated_by_arbitrary_message(self):
        self.s.started(user(1))
        campaign = self.s.campaign('custom')
        self.s.deactivate(1)
        self.s.save_user(user(1))
        self.assertFalse(self.s.deliverable(campaign, 1))
        self.assertIn('Inactive users: 1', self.s.stats())
        self.s.started(user(1))
        self.assertIn('Active users: 1', self.s.stats())

    def test_broadcast_confirmation_consumed_once_and_excludes_admin(self):
        import json
        self.s.started(user(1))
        self.s.started(user(99))
        self.s.set('draft', json.dumps({'nonce':'test','text':'hi'}))
        self.assertIsNone(self.s.confirm_draft('wrong', 99))
        campaign = self.s.confirm_draft('test', 99)
        self.assertTrue(self.s.deliverable(campaign, 1))
        self.assertFalse(self.s.deliverable(campaign, 99))
        self.assertIsNone(self.s.confirm_draft('test', 99))

    def test_custom_redirect_persists(self):
        self.s.started(user(1))
        self.s.set('redirect_chat', 99)
        self.s.set('redirect_message', 123)
        self.s.enable_redirect()
        self.assertEqual(self.s.next_rotation()['step'], 0)
        self.assertEqual(self.s.get('redirect_message'), '123')

class DuplicateProtectionTests(unittest.TestCase):
    def test_replayed_updates_and_rapid_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            s = Storage(directory + '/db')
            self.assertTrue(s.claim_update(100))
            self.assertFalse(s.claim_update(100))
            self.assertTrue(s.claim_start(1, now=100))
            self.assertFalse(s.claim_start(1, now=100.5))
            self.assertTrue(s.claim_start(1, now=104))
            s.enable_redirect()
            self.assertTrue(s.claim_start(1, now=104.5))
            s.close()
            s = Storage(directory + '/db')
            self.assertFalse(s.claim_update(100))
            self.assertFalse(s.claim_start(1, now=105))
            s.close()
