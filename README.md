# Drew Academy Telegram Bot

Python and aiogram 3.x, running with Telegram polling.

## Setup

Build: `pip install -r requirements.txt`
Start: `python bot.py`

Set `BOT_TOKEN` and `ADMIN_ID` (your numeric Telegram user ID) in your hosting environment.
Set `DATABASE_PATH` to a persistent location, e.g. `/data/drewacademy.db` on a mounted disk.
The default `data/drewacademy.db` requires persistent storage to survive redeployment.
Run only one instance per bot token. No admin ID is assumed or hardcoded.

## Admin controls

- `/admin`: REDIRECT, REVERSE, Set Redirect Message, Broadcast Message / Offer, Users & Stats.
- REDIRECT or `/redirect`: enables redirect mode and immediately queues the configured message for all active saved users. New users pressing `/start` receive it too. Each user receives it once per activation; clicking REDIRECT again starts a fresh campaign.
- REVERSE or `/reverse`: cancels pending redirect deliveries and broadcasts the personalized DREW FX community message to active saved users. New starters also receive it once per activation. Uses `assets/drew_fx_bull.png` with a caption and Join DREW FX Community button pointing to https://t.me/Drewcommunity. Upload that image to include the photo; until then it sends text with the button. Messages already delivered cannot be recalled. Custom broadcasts continue. Switching back to REDIRECT cancels pending reverse deliveries.
- Set Redirect Message: send one text, photo, video or other copyable message. The bot saves a preview copy as its source. Click REDIRECT to send it. Keep that preview message available.
- Broadcast Message / Offer: opens a composer; the next single message is previewed and queued for saved users in either mode. Albums are not supported.
- `/send MESSAGE`: queues a text broadcast in either mode.
- `/cancel`: closes the composer. Ordinary admin chat does not broadcast.
- Users & Stats: user totals, active users, mode and delivery counts.

Only ADMIN_ID in a private chat can operate admin controls. The default redirect content is the original channel message linking to https://t.me/Drewcommunity.

## User saving and delivery

Private-chat users are saved with Telegram ID, username, names, language and first/last interaction dates. `/start` opts in; `/stop` opts out. No phone numbers are collected.
SQLite keeps users, settings and queued deliveries across restarts when its file is on persistent storage. Blocked users are marked inactive; Telegram rate limits and temporary network failures are retried. Permanent delivery errors are counted as failed.
Delivery is at-least-once: a crash after Telegram accepts a message but before the database records success can cause a duplicate after restart.

The previous version did not save users. Earlier users become available when they interact again; historical IDs must be recovered from this bot's existing logs or database. User IDs from a different bot are not imported.

## Verification

`python -m unittest -v test_storage.py test_bot.py`

Tests cover saved users, redirect recipients, duplicate starts, reverse cancellation, restart persistence, manual campaigns and inactive users. Live Telegram delivery requires the deployed bot token.
