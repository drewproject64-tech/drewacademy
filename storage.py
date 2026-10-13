import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DEFAULT_MESSAGE = 'Get XAUUSD Daily 5-8 Free Signals Free Available Join Now 👊👇👇👇👇https://t.me/Drewcommunity'


class Storage:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
          language_code TEXT, first_seen TEXT, last_seen TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS deliveries (
          campaign INTEGER, user_id INTEGER, status TEXT DEFAULT 'pending',
          PRIMARY KEY(campaign,user_id));
        CREATE TABLE IF NOT EXISTS campaigns (
          id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, source_chat INTEGER,
          source_message INTEGER, cancelled INTEGER DEFAULT 0);
        ''')
        self.db.commit()

    def get(self, key, default=''):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def set(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, str(value)))

    def save_user(self, user):
        now = datetime.now(timezone.utc).isoformat()
        with self.db:
            self.db.execute('''INSERT INTO users VALUES (?,?,?,?,?,?,?,1)
            ON CONFLICT(id) DO UPDATE SET username=excluded.username,
            first_name=excluded.first_name,last_name=excluded.last_name,
            language_code=excluded.language_code,last_seen=excluded.last_seen''',
            (user.id, user.username, user.first_name, user.last_name, user.language_code, now, now))

    def campaign(self, text=None, source_chat=None, source_message=None):
        with self.db:
            cursor = self.db.execute('INSERT INTO campaigns(text,source_chat,source_message) VALUES (?,?,?)',
                                     (text, source_chat, source_message))
            campaign = cursor.lastrowid
            self.db.execute('INSERT INTO deliveries(campaign,user_id) SELECT ?,id FROM users WHERE active=1', (campaign,))
        return campaign

    def enable_redirect(self):
        # One transaction persists both the mode and the recipient queue.
        with self.db:
            previous = self.get('redirect_campaign')
            if previous:
                self.db.execute('UPDATE campaigns SET cancelled=1 WHERE id=?', (previous,))
            cursor = self.db.execute('INSERT INTO campaigns(text,source_chat,source_message) VALUES (?,?,?)',
                (self.get('redirect_text', DEFAULT_MESSAGE),
                 int(self.get('redirect_chat')) if self.get('redirect_chat') else None,
                 int(self.get('redirect_message')) if self.get('redirect_message') else None))
            campaign = cursor.lastrowid
            self.db.execute('INSERT INTO deliveries(campaign,user_id) SELECT ?,id FROM users WHERE active=1', (campaign,))
            self.db.executemany('INSERT OR REPLACE INTO settings VALUES (?,?)',
                                [('mode', 'redirect'), ('redirect_campaign', str(campaign))])
        return campaign

    def reverse(self):
        with self.db:
            campaign = self.get('redirect_campaign')
            if campaign:
                self.db.execute('UPDATE campaigns SET cancelled=1 WHERE id=?', (campaign,))
            self.set('mode', 'normal')

    def started(self, user):
        self.save_user(user)
        with self.db:
            self.db.execute('UPDATE users SET active=1 WHERE id=?', (user.id,))
        if self.get('mode') == 'redirect':
            with self.db:
                self.db.execute('INSERT OR IGNORE INTO deliveries(campaign,user_id) VALUES (?,?)',
                                (int(self.get('redirect_campaign')), user.id))

    def next_delivery(self):
        return self.db.execute('''SELECT c.*,d.user_id FROM deliveries d JOIN campaigns c ON c.id=d.campaign
        JOIN users u ON u.id=d.user_id WHERE d.status='pending' AND c.cancelled=0 AND u.active=1
        ORDER BY c.id,d.user_id LIMIT 1''').fetchone()

    def finish(self, campaign, user, status):
        with self.db:
            self.db.execute('UPDATE deliveries SET status=? WHERE campaign=? AND user_id=?', (status,campaign,user))
            if status == 'blocked':
                self.db.execute('UPDATE users SET active=0 WHERE id=?', (user,))

    def stats(self):
        total, active = self.db.execute('SELECT COUNT(*),COALESCE(SUM(active),0) FROM users').fetchone()
        counts = dict(self.db.execute('SELECT status,COUNT(*) FROM deliveries GROUP BY status').fetchall())
        return f'Users: {total}\nActive: {active}\nMode: {self.get("mode", "normal")}\nDeliveries: {counts}'
