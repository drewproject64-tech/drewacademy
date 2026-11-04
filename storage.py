"""Durable user registry and delivery queue (Neon Postgres in production)."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
from threading import RLock

DEFAULT_MESSAGE = 'Get XAUUSD Daily 5-8 Free Signals Free Available Join Now 👊👇👇👇👇'
REVERSE_MESSAGE = '{name}, DON’T MISS OUT AGAIN! 🔥\n\nThe DREW FX community is active with exclusive signals, and the session is still ongoing. Join now and stay up to date with everything!'


def schema(postgres=False):
    identity = 'BIGSERIAL PRIMARY KEY' if postgres else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    return [
        '''CREATE TABLE IF NOT EXISTS users (
        id BIGINT PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
        language_code TEXT, first_seen TEXT, last_seen TEXT, active INTEGER DEFAULT 1)''',
        'CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)',
        'CREATE TABLE IF NOT EXISTS handled_updates (id BIGINT PRIMARY KEY, seen_at BIGINT)',
        f'''CREATE TABLE IF NOT EXISTS campaigns (id {identity}, text TEXT,
        source_chat BIGINT, source_message BIGINT, cancelled INTEGER DEFAULT 0)''',
        '''CREATE TABLE IF NOT EXISTS deliveries (campaign BIGINT, user_id BIGINT,
        status TEXT DEFAULT 'pending', PRIMARY KEY(campaign,user_id))''',
        'CREATE INDEX IF NOT EXISTS deliveries_pending_idx ON deliveries(status,campaign,user_id)',
        '''CREATE TABLE IF NOT EXISTS rotations (
        user_id BIGINT PRIMARY KEY, campaign BIGINT NOT NULL,
        step INTEGER NOT NULL DEFAULT 0, due_at BIGINT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending')''',
        'CREATE INDEX IF NOT EXISTS rotations_due_idx ON rotations(status,due_at)',
    ]


class Storage:
    def __init__(self, path):
        self.postgres = path.startswith(('postgres://', 'postgresql://'))
        self.lock = RLock()
        self.depth = 0
        self.path = path
        if self.postgres:
            self.db = self.connect()
        else:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
        with self.transaction():
            for sql in schema(self.postgres):
                self.execute(sql)
            if self.get('mode_version') != '2':
                self.reverse()
                self.set('mode_version', '2')

    def connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.path, autocommit=True, row_factory=dict_row,
                               connect_timeout=15, sslmode='require')

    @contextmanager
    def transaction(self):
        # All calls run on a worker thread; serialize connection use and reconnect
        # only before a transaction, never replay an uncertain committed operation.
        with self.lock:
            outer = self.depth == 0
            if outer and self.postgres:
                try:
                    self.db.execute('SELECT 1')
                except Exception:
                    self.db.close()
                    self.db = self.connect()
            self.depth += 1
            try:
                if outer:
                    with (self.db.transaction() if self.postgres else self.db):
                        yield
                else:
                    yield
            finally:
                self.depth -= 1

    def execute(self, sql, args=()):
        return self.db.execute(sql.replace('?', '%s') if self.postgres else sql, args)

    def get(self, key, default=''):
        row = self.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default

    def set(self, key, value):
        with self.transaction():
            self.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))

    def save_user(self, user):
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction():
            self.execute('''INSERT INTO users(id,username,first_name,last_name,language_code,first_seen,last_seen,active)
            VALUES (?,?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET username=excluded.username,
            first_name=excluded.first_name,last_name=excluded.last_name,
            language_code=excluded.language_code,last_seen=excluded.last_seen''',
            (user.id, user.username, user.first_name, user.last_name, user.language_code, now, now))

    def campaign(self, text=None, source_chat=None, source_message=None, exclude_id=0):
        with self.transaction():
            row = self.execute('INSERT INTO campaigns(text,source_chat,source_message) VALUES (?,?,?) RETURNING id', (text, source_chat, source_message)).fetchone()
            campaign = row['id']
            self.execute('INSERT INTO deliveries(campaign,user_id) SELECT ?,id FROM users WHERE active=1 AND id<>?', (campaign, exclude_id))
        return campaign

    def enable_redirect(self, admin_id=0, restart=False):
        """Queue step 0 immediately for all active users, including the admin.

        REDIRECT is an intentional restart when restart=True. A background
        rollout or repeated internal call with restart=False is idempotent.
        """
        import time
        with self.transaction():
            existing = self.get('rotation_campaign')
            if (not restart and self.get('mode') == 'redirect' and existing
                    and self.get('redirect_campaign') == existing):
                return int(existing)
            old = self.get('redirect_campaign')
            if old:
                self.execute('UPDATE campaigns SET cancelled=1 WHERE id=?', (int(old),))
            # The admin explicitly opted into the preview/rotation by clicking REDIRECT.
            if admin_id:
                self.execute('UPDATE users SET active=1 WHERE id=?', (admin_id,))
            row = self.execute('INSERT INTO campaigns(text) VALUES (?) RETURNING id',
                               ('DREW FX ROTATION',)).fetchone()
            campaign = int(row['id'])
            now = int(time.time())
            self.execute("UPDATE rotations SET status='cancelled' WHERE status IN ('pending','sending')")
            self.execute("""INSERT INTO rotations(user_id,campaign,step,due_at,status)
                SELECT id,?,0,?,'pending' FROM users WHERE active=1
                ON CONFLICT(user_id) DO UPDATE SET campaign=excluded.campaign,
                  step=0,due_at=excluded.due_at,status='pending'""", (campaign, now))
            self.set('mode', 'redirect')
            self.set('redirect_campaign', campaign)
            self.set('rotation_campaign', campaign)
            return campaign

    def rotation_for_user(self, user_id, now=None):
        """Get a due rotation row for the admin fast path without changing state."""
        import time
        now = int(time.time() if now is None else now)
        with self.transaction():
            campaign = self.get('rotation_campaign')
            if self.get('mode') != 'redirect' or not campaign:
                return None
            row = self.execute("""SELECT r.user_id,r.campaign,r.step,r.due_at,u.first_name
                FROM rotations r JOIN users u ON u.id=r.user_id
                WHERE r.user_id=? AND r.status='pending' AND r.campaign=?
                  AND r.due_at<=? AND u.active=1""",
                (user_id, int(campaign), now)).fetchone()
            return dict(row) if row else None

    def reverse(self):
        with self.transaction():
            for key in ('redirect_campaign', 'normal_campaign'):
                previous = self.get(key)
                if previous:
                    self.execute('UPDATE campaigns SET cancelled=1 WHERE id=?', (int(previous),))
            self.execute("UPDATE rotations SET status='cancelled' WHERE status IN ('pending','sending')")
            self.set('mode', 'normal')
            self.set('rotation_campaign', '')
            self.execute("DELETE FROM settings WHERE key='normal_campaign'")

    def started(self, user, exclude_id=0):
        import time
        with self.transaction():
            self.save_user(user)
            self.execute('UPDATE users SET active=1 WHERE id=?', (user.id,))
            campaign = self.get('rotation_campaign')
            if self.get('mode') == 'redirect' and campaign:
                self.execute("""INSERT INTO rotations(user_id,campaign,step,due_at,status)
                    VALUES (?,?,0,?,'pending')
                    ON CONFLICT(user_id) DO UPDATE SET
                        campaign=excluded.campaign,
                        step=CASE WHEN rotations.status IN ('cancelled','blocked','failed')
                                   OR rotations.campaign<>excluded.campaign THEN 0 ELSE rotations.step END,
                        due_at=CASE WHEN rotations.status IN ('cancelled','blocked','failed')
                                      OR rotations.campaign<>excluded.campaign
                                    THEN excluded.due_at ELSE rotations.due_at END,
                        status=CASE WHEN rotations.status IN ('cancelled','blocked','failed')
                                      OR rotations.campaign<>excluded.campaign
                                    THEN 'pending' ELSE rotations.status END""",
                    (user.id, int(campaign), int(time.time())))

    def claim_update(self, update_id):
        import time
        with self.transaction():
            row = self.execute('INSERT INTO handled_updates(id,seen_at) VALUES (?,?) ON CONFLICT(id) DO NOTHING RETURNING id', (update_id, int(time.time()))).fetchone()
            return row is not None

    def release_update(self, update_id):
        with self.transaction():
            self.execute('DELETE FROM handled_updates WHERE id=?', (update_id,))

    def claim_start(self, user_id, now=None):
        import time
        now = time.time() if now is None else now
        with self.transaction():
            # A real mode change remains immediately testable by the admin.
            signature = self.get('mode', 'normal') + ':' + self.get('redirect_campaign')
            key = f'last_start:{user_id}:{signature}'
            previous = self.get(key)
            if previous and now - float(previous) < 3:
                return False
            self.set(key, now)
            return True

    def start_payload(self, user):
        """A /start response owns its delivery; never enqueue another copy."""
        with self.transaction():
            self.save_user(user)
            self.execute('UPDATE users SET active=1 WHERE id=?', (user.id,))
            if self.get('mode') != 'redirect':
                return None
            campaign = self.get('redirect_campaign')
            row = self.execute('SELECT * FROM campaigns WHERE id=? AND cancelled=0', (int(campaign),)).fetchone() if campaign else None
            if not row:
                return None
            self.execute("UPDATE deliveries SET status='superseded' WHERE campaign=? AND user_id=? AND status='pending'", (int(campaign), user.id))
            payload = dict(row)
            payload.update(user_id=user.id, first_name=user.first_name)
            return payload

    def claim_delivery(self, campaign, user):
        with self.transaction():
            row = self.execute("""UPDATE deliveries SET status='sending'
                WHERE campaign=? AND user_id=? AND status='pending'
                AND EXISTS (SELECT 1 FROM campaigns WHERE id=? AND cancelled=0)
                AND EXISTS (SELECT 1 FROM users WHERE id=? AND active=1)
                RETURNING user_id""", (campaign,user,campaign,user)).fetchone()
            return row is not None

    def recover_deliveries(self):
        # On restart, an uncertain rotation send is skipped instead of repeated.
        # This provides at-most-once attempts for a rotation step across rollouts.
        import time
        from rotation import ROTATION_COUNT, ROTATION_INTERVAL_SECONDS
        with self.transaction():
            self.execute("UPDATE deliveries SET status='pending' WHERE status='sending'")
            self.execute("""UPDATE rotations SET step=MOD(step+1, ?),
                due_at=?,status='pending' WHERE status='sending'""",
                (ROTATION_COUNT, int(time.time()) + ROTATION_INTERVAL_SECONDS))

    def next_rotation(self, now=None):
        import time
        now = int(time.time() if now is None else now)
        with self.transaction():
            campaign = self.get('rotation_campaign')
            if self.get('mode') != 'redirect' or not campaign:
                return None
            row = self.execute("""SELECT r.user_id,r.campaign,r.step,r.due_at,u.first_name
                FROM rotations r JOIN users u ON u.id=r.user_id
                WHERE r.status='pending' AND r.campaign=? AND r.due_at<=?
                  AND u.active=1 ORDER BY r.due_at,r.user_id LIMIT 1""",
                (int(campaign), now)).fetchone()
            return dict(row) if row else None

    def claim_rotation(self, campaign, user_id, step, now=None):
        import time
        now = int(time.time() if now is None else now)
        with self.transaction():
            if self.get('mode') != 'redirect' or self.get('rotation_campaign') != str(campaign):
                return False
            row = self.execute("""UPDATE rotations SET status='sending'
                WHERE campaign=? AND user_id=? AND step=? AND status='pending' AND due_at<=?
                AND EXISTS (SELECT 1 FROM users WHERE id=? AND active=1)
                RETURNING user_id""", (campaign,user_id,step,now,user_id)).fetchone()
            return row is not None

    def finish_rotation(self, campaign, user_id, step, status, delay=0, now=None):
        import time
        from rotation import ROTATION_COUNT, ROTATION_INTERVAL_SECONDS
        now = int(time.time() if now is None else now)
        with self.transaction():
            if status == 'sent':
                self.execute("""UPDATE rotations SET step=?,due_at=?,status='pending'
                    WHERE user_id=? AND campaign=? AND step=? AND status='sending'""",
                    ((step+1)%ROTATION_COUNT, now+ROTATION_INTERVAL_SECONDS, user_id, campaign, step))
            elif status == 'pending':
                self.execute("""UPDATE rotations SET due_at=?,status='pending'
                    WHERE user_id=? AND campaign=? AND step=? AND status='sending'""",
                    (now+max(5,int(delay)), user_id, campaign, step))
            else:
                self.execute("""UPDATE rotations SET status=?
                    WHERE user_id=? AND campaign=? AND step=? AND status='sending'""",
                    (status, user_id, campaign, step))
                if status == 'blocked':
                    self.deactivate(user_id)

    def deactivate(self, user_id):
        with self.transaction():
            self.execute('UPDATE users SET active=0 WHERE id=?', (user_id,))
            self.execute("UPDATE deliveries SET status='cancelled' WHERE user_id=? AND status='pending'", (user_id,))
            self.execute("UPDATE rotations SET status='cancelled' WHERE user_id=? AND status IN ('pending','sending')", (user_id,))

    def next_delivery(self):
        with self.transaction():
            row = self.execute('''SELECT c.*,d.user_id,u.first_name FROM deliveries d JOIN campaigns c ON c.id=d.campaign
            JOIN users u ON u.id=d.user_id WHERE d.status='pending' AND c.cancelled=0 AND u.active=1
            ORDER BY c.id,d.user_id LIMIT 1''').fetchone()
            return dict(row) if row else None

    def deliverable(self, campaign, user):
        with self.transaction():
            return self.execute('''SELECT d.user_id FROM deliveries d JOIN campaigns c ON c.id=d.campaign
            JOIN users u ON u.id=d.user_id WHERE d.campaign=? AND d.user_id=?
            AND d.status='pending' AND c.cancelled=0 AND u.active=1''', (campaign,user)).fetchone() is not None

    def finish(self, campaign, user, status):
        with self.transaction():
            self.execute('UPDATE deliveries SET status=? WHERE campaign=? AND user_id=?', (status,campaign,user))
            if status == 'blocked':
                self.deactivate(user)

    def stats(self):
        with self.transaction():
            row = self.execute('SELECT COUNT(*) AS total,COALESCE(SUM(active),0) AS active FROM users').fetchone()
            counts = {r['status']:r['n'] for r in self.execute('''SELECT CASE WHEN c.cancelled=1 AND d.status='pending'
                THEN 'cancelled' ELSE d.status END AS status,COUNT(*) AS n FROM deliveries d
                JOIN campaigns c ON c.id=d.campaign GROUP BY 1''').fetchall()}
            today = self.execute('SELECT COUNT(*) AS n FROM users WHERE first_seen>=?', (datetime.now(timezone.utc).date().isoformat(),)).fetchone()['n']
            rotation_id = self.get('rotation_campaign')
            rotation_counts = {'pending': 0, 'sending': 0, 'failed': 0, 'blocked': 0}
            stage_counts = {}
            if self.get('mode') == 'redirect' and rotation_id:
                for rec in self.execute("""SELECT status,step,COUNT(*) AS n FROM rotations
                    WHERE campaign=? GROUP BY status,step""", (int(rotation_id),)).fetchall():
                    rotation_counts[rec['status']] = rotation_counts.get(rec['status'], 0) + rec['n']
                    if rec['status'] in ('pending', 'sending'):
                        stage_counts[rec['step'] + 1] = stage_counts.get(rec['step'] + 1, 0) + rec['n']
            rotations = rotation_counts['pending'] + rotation_counts['sending']
            stage_text = ', '.join(f'{stage}: {count}' for stage, count in sorted(stage_counts.items())) or 'none'
            return (f"Total users: {row['total']}\nActive users: {row['active']}\nInactive users: {row['total']-row['active']}"
                    f"\nNew today (UTC): {today}\nMode: {self.get('mode','normal')}"
                    f"\nRotation subscribers: {rotations}\nRotation interval: 2 hours"
                    f"\nNext stage counts: {stage_text}"
                    f"\nRotation failed: {rotation_counts['failed']}"
                    f"\nRotation blocked: {rotation_counts['blocked']}\n"
                    + '\n'.join(f'{k.title()}: {counts.get(k,0)}' for k in ('pending','sent','blocked','failed','cancelled')))

    def confirm_draft(self, nonce, exclude_id):
        import json
        with self.transaction():
            raw = self.get('draft')
            data = json.loads(raw) if raw else {}
            if data.get('nonce') != nonce:
                return None
            campaign = self.campaign(data.get('text'), data.get('chat'), data.get('message'), exclude_id)
            self.set('draft', '')
            return campaign

    def close(self):
        self.db.close()


