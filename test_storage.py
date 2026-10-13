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
            self.assertEqual(s.next_delivery()['user_id'], 1)
            s.finish(campaign, 1, 'sent')
            s.started(user(1))
            self.assertIsNone(s.next_delivery())
            s.started(user(2))
            s.db.close()
            s = Storage(path)
            self.assertEqual(s.next_delivery()['user_id'], 2)
            s.reverse()
            reverse_campaign = s.next_delivery()['id']
            s.finish(reverse_campaign, 1, 'sent')
            s.finish(reverse_campaign, 2, 'sent')
            self.assertIsNone(s.next_delivery())
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
