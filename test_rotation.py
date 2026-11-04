import tempfile
import time
import unittest

from storage import Storage
from rotation import MESSAGES, ROTATION_COUNT, ROTATION_INTERVAL_SECONDS, ADMIN_URL
from test_storage import user


class RotationStorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.s = Storage(self.folder.name + '/db')

    def tearDown(self):
        self.s.close()
        self.folder.cleanup()

    def test_five_stage_cycle_every_two_hours(self):
        self.s.started(user(1))
        campaign = self.s.enable_redirect(exclude_id=99)
        now = int(time.time()) + 5
        for step in range(ROTATION_COUNT):
            row = self.s.next_rotation(now=now)
            self.assertIsNotNone(row)
            self.assertEqual(row['campaign'], campaign)
            self.assertEqual(row['step'], step)
            self.assertTrue(self.s.claim_rotation(campaign, 1, step, now=now))
            self.assertFalse(self.s.claim_rotation(campaign, 1, step, now=now))
            self.s.finish_rotation(campaign, 1, step, 'sent', now=now)
            self.assertIsNone(self.s.next_rotation(now=now))
            now += ROTATION_INTERVAL_SECONDS
        self.assertEqual(self.s.next_rotation(now=now)['step'], 0)
        self.assertEqual(self.s.enable_redirect(99), campaign)

    def test_reverse_stops_rotation_but_preserves_custom_broadcast(self):
        self.s.started(user(1))
        campaign = self.s.enable_redirect(99)
        manual = self.s.campaign('Admin update')
        self.assertIsNotNone(self.s.next_rotation())
        self.s.reverse()
        self.assertIsNone(self.s.next_rotation())
        self.assertFalse(self.s.claim_rotation(campaign, 1, 0))
        self.assertTrue(self.s.deliverable(manual, 1))

    def test_opt_out_and_rejoin(self):
        self.s.started(user(1))
        self.s.enable_redirect(99)
        self.s.deactivate(1)
        self.assertIsNone(self.s.next_rotation())
        self.s.save_user(user(1))
        self.assertIsNone(self.s.next_rotation())
        self.s.started(user(1))
        self.assertEqual(self.s.next_rotation()['step'], 0)

    def test_excludes_admin_and_keeps_progress_after_start(self):
        self.s.started(user(1))
        self.s.started(user(99))
        campaign = self.s.enable_redirect(99)
        self.assertEqual(self.s.next_rotation()['user_id'], 1)
        now = int(time.time()) + 3
        self.assertTrue(self.s.claim_rotation(campaign, 1, 0, now=now))
        self.s.finish_rotation(campaign, 1, 0, 'sent', now=now)
        self.s.started(user(1), 99)
        self.s.started(user(99), 99)
        self.assertIsNone(self.s.next_rotation(now=now))

    def test_uncertain_send_not_replayed_on_restart(self):
        self.s.started(user(1))
        campaign = self.s.enable_redirect(99)
        self.assertTrue(self.s.claim_rotation(campaign, 1, 0))
        self.s.recover_deliveries()
        self.assertIsNone(self.s.next_rotation())
        later = int(time.time()) + ROTATION_INTERVAL_SECONDS + 3
        self.assertEqual(self.s.next_rotation(now=later)['step'], 1)

    def test_postgres_recovery_query_uses_two_unambiguous_parameters(self):
        from contextlib import contextmanager

        class FakePostgres:
            def __init__(self):
                self.calls = []

            def execute(self, sql, args=()):
                self.calls.append((sql, args))
                return self

            def fetchone(self):
                return None

            @contextmanager
            def transaction(self):
                yield

        original_db, original_postgres = self.s.db, self.s.postgres
        fake = FakePostgres()
        try:
            self.s.db = fake
            self.s.postgres = True
            self.s.recover_deliveries()
        finally:
            self.s.db = original_db
            self.s.postgres = original_postgres

        recovery = [call for call in fake.calls if 'UPDATE rotations' in call[0]]
        self.assertEqual(len(recovery), 1)
        sql, params = recovery[0]
        self.assertIn('MOD(step+1, %s)', sql)
        self.assertIn('due_at=%s', sql)
        self.assertEqual(len(params), 2)
        self.assertNotIn('(step+1)%s', sql)

    def test_english_translations_and_prefilled_admin_cta(self):
        self.assertEqual(len(MESSAGES), 5)
        self.assertIn('withdrew $60', MESSAGES[1][0])
        self.assertIn('withdrew $30 today', MESSAGES[2][0])
        self.assertIn('started with $15', MESSAGES[3][0])
        self.assertIn('SIGNALS', MESSAGES[-1][0])
        self.assertEqual(MESSAGES[-1][2], ADMIN_URL)
        self.assertIn('?text=SIGNALS', ADMIN_URL)
        for index in (1, 2, 3):
            self.assertIn('verif', MESSAGES[index][0].lower())
        self.assertIn('No profits are guaranteed', MESSAGES[-1][0])


if __name__ == '__main__':
    unittest.main()
