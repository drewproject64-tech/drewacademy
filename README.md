# Drew Academy Bot

Build: `pip install -r requirements.txt`
Start: `python bot.py`
Required: BOT_TOKEN, ADMIN_ID. DATABASE_PATH must point to persistent storage to keep saved users across redeploys.

Normal /start sends exactly the original XAUUSD message and channel link.
/admin or admin /start shows the administrator controls.
REDIRECT immediately queues the personalized DREW FX message, assets/drew_fx_bull.png and Join DREW FX Community button for active saved users. New starters are queued too, once per activation. Repeating REDIRECT starts another broadcast.
REVERSE cancels pending mode campaigns and restores the original /start message; it does not broadcast. Delivered messages cannot be recalled.
Custom broadcasts and /send MESSAGE work in either mode. /cancel closes the composer; /stop opts out and /start opts in again. /id shows your Telegram user ID.

This update resets the earlier inverted mode once without deleting users. Modes and deliveries persist thereafter. A crash after Telegram accepts a message but before recording delivery can produce a duplicate. Missing image falls back to text and button. Earlier users were not saved by the original code and must interact again or be recovered from this bot's logs.

Verification: `python -m unittest -v test_storage.py test_bot.py`
