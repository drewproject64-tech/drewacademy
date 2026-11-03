# Drew Academy Bot

Build: `pip install -r requirements.txt`. Start: `python bot.py`.
Set `BOT_TOKEN`, `ADMIN_ID` (numeric Telegram ID), and `DATABASE_URL` in Render's environment settings. Use the Neon connection string with TLS. Never commit credentials. This service is configured through Render environment variables, not a Blueprint. Run one worker per bot token.

## Administrator menu

Only `ADMIN_ID` in a private chat can open `/admin` or operate buttons. Telegram's command menu beside the chat box includes `/admin` only for that chat. The inline panel offers:

- **Users & Stats**: total users, active/inactive users, new today (UTC), mode, and pending/sent/blocked/failed/cancelled delivery counts. Totals include the administrator if they have interacted.
- **Broadcast Message / Offer**: compose one text, photo, video or other copyable message. A preview and **Send broadcast** button appear; nothing is queued until confirmed. `/send MESSAGE` uses the same confirmation. Ordinary admin messages never broadcast. Confirmation is consumed once.
- **Edit Redirect Message**: saves a custom source message for the next activation. Keep the preview in the admin chat available for copying. If redirect is enabled, choose REVERSE then REDIRECT to apply an edited message.
- **REDIRECT**: confirm activation to queue the saved message for active users, excluding the administrator. New /start users are included. Pressing again while enabled does not resend. Without custom content, the existing personalized community text/photo/button is used.
- **REVERSE**: cancels pending redirect deliveries and restores the original normal /start message. Custom broadcasts continue. Already delivered messages cannot be recalled; an in-flight send may complete.
- **Cancel**: closes the composer and invalidates its current broadcast preview.

## User storage

Neon stores Telegram ID, username, first/last names, language code, first/last interaction timestamps and active status for every private-chat user who interacts. No phone numbers or full message histories are collected. Settings, campaign content and delivery status also persist across redeploys. /stop stops pending/future broadcasts; /start opts in again. Other messages do not undo opt-out. Blocked recipients become inactive. Users who never interacted cannot be discovered by the bot.

The new Neon database starts empty. An old SQLite file is not automatically imported or deleted; preserve it separately if historical users must be migrated. A redeploy may erase an old SQLite file on ephemeral storage. Existing records need a migration before redeploy if they are the only copy.

DB operations run off the Telegram event loop; temporary connection failures reconnect before the next transaction. Telegram throttling/network failures retry. Queue delivery is at-least-once: interruption between sending and recording success can cause a duplicate. Keep one running worker. Switching modes is a business control, not a way to conceal content during advertising review; normal and redirect content should accurately describe the same service.

## Verification

`python -m unittest -v test_storage.py test_bot.py`
