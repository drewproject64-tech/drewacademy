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

    def enable_redirect(self, exclude_id=0):
        with self.transaction():
            # Repeated button presses must not resend the same campaign.
            if self.get('mode') == 'redirect':
                return int(self.get('redirect_campaign'))
            source_chat = self.get('redirect_chat')
            source_message = self.get('redirect_message')
            campaign = self.campaign(REVERSE_MESSAGE, int(source_chat) if source_chat else None,
                                     int(source_message) if source_message else None, exclude_id)
            self.set('mode', 'redirect')
            self.set('redirect_campaign', campaign)
        return campaign

    def reverse(self):
        with self.transaction():
            for key in ('redirect_campaign', 'normal_campaign'):
                previous = self.get(key)
                if previous:
                    self.execute('UPDATE campaigns SET cancelled=1 WHERE id=?', (int(previous),))
            self.set('mode', 'normal')
            self.execute("DELETE FROM settings WHERE key='normal_campaign'")

    def started(self, user):
        with self.transaction():
            self.save_user(user)
            self.execute('UPDATE users SET active=1 WHERE id=?', (user.id,))
            if self.get('mode') == 'redirect' and self.get('redirect_campaign'):
                self.execute('INSERT INTO deliveries(campaign,user_id) VALUES (?,?) ON CONFLICT(campaign,user_id) DO NOTHING', (int(self.get('redirect_campaign')), user.id))

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
        # Only run after obtaining the process lease, with no other worker live.
        with self.transaction():
            self.execute("UPDATE deliveries SET status='pending' WHERE status='sending'")

    def deactivate(self, user_id):
        with self.transaction():
            self.execute('UPDATE users SET active=0 WHERE id=?', (user_id,))
            self.execute("UPDATE deliveries SET status='cancelled' WHERE user_id=? AND status='pending'", (user_id,))

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
            return (f"Total users: {row['total']}\nActive users: {row['active']}\nInactive users: {row['total']-row['active']}"
                    f"\nNew today (UTC): {today}\nMode: {self.get('mode','normal')}\n"
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


