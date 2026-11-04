# Drew Academy Bot

Build: `pip install -r requirements.txt`. Start: `python bot.py`.
Set `BOT_TOKEN`, `ADMIN_ID` (numeric Telegram ID), and `DATABASE_URL` in Render's environment settings. Use the Neon connection string with TLS. Never commit credentials. This service is configured through Render environment variables, not a Blueprint. Run one worker per bot token.

## Administrator menu

Only `ADMIN_ID` in a private chat can open `/admin` or operate buttons. Telegram's command menu beside the chat box includes `/admin` only for that chat. The inline panel offers:

- **Users & Stats**: total users, active/inactive users, new today (UTC), mode, and pending/sent/blocked/failed/cancelled delivery counts. Totals include the administrator if they have interacted.
- **Broadcast Message / Offer**: compose one text, photo, video or other copyable message. A preview and **Send broadcast** button appear; nothing is queued until confirmed. `/send MESSAGE` uses the same confirmation. Ordinary admin messages never broadcast. Confirmation is consumed once.
- **Edit Redirect Message**: saves a custom source message for the next activation. Keep the preview in the admin chat available for copying. If redirect is enabled, choose REVERSE then REDIRECT to apply an edited message.
- **REDIRECT**: confirm activation to launch the five-stage forex message rotation for active saved subscribers (excluding the admin). The first message is queued immediately. Each following message arrives **two hours after the preceding successful send** for that subscriber. After the fifth message, the sequence loops from the first until REVERSE. Repeated activation while already active is idempotent. New /start users join at stage one. If you saved a custom redirect message, it is copied as stage one; otherwise the built-in introduction and community button are used.
- **REVERSE**: stops the rotation, cancels remaining queued posts, and restores the original normal /start response. Custom broadcasts continue. Already delivered messages cannot be recalled; a currently in-flight send may complete.
- **Cancel**: closes the composer and invalidates its current broadcast preview.

## Five-stage redirect rotation (two-hour spacing)

1. DREW FX community introduction, with community button (or your optional custom first message).
2. **Photo:** `assets/testimonial_1_ramiro.jpg` — Ramiro Vela screenshot, with English caption ($30 / $60 / $40) clearly flagged as unverified.
3. **Photo:** `assets/testimonial_2_joaquin.jpg` — Joaquín Mora screenshot, with English-translated caption ($40 / $30 / $35) clearly flagged as unverified.
4. **Photo:** `assets/testimonial_3_rubin.jpg` — Rubin screenshot, with English-translated caption ($15 / $75) clearly flagged as unverified.
5. The full DREW FX VIP community announcement, **last** in each cycle, with an inline **MESSAGE ADMIN — SIGNALS** button that links to `https://t.me/drewFxx?text=SIGNALS`. This pre-fills SIGNALS but the subscriber must manually send it.

Every two hours are measured **per user** from the last message's recorded delivery. The fifth stage wraps to the first stage after another two hours, repeating until REVERSE or subscriber /stop. No second immediate copy is sent by /start. Delivery progress is saved in Neon and survives redeployment. The rotation queue is separate from custom one-off broadcasts. Blocked users and /stop users are excluded; /start opts back in.

Each testimonial is now delivered as one Telegram **photo with an English caption**, rather than a separate text-only message. The original JPG screenshots are kept unchanged (the Joaquín and Rubin pixels are in Spanish; their captions supply the English translation). If an image is absent at deployment, the bot falls back to text and logs an error. Neither the screenshots nor their earnings claims were independently verified. Do not claim guaranteed or typical returns. If the image claims are not authorized for sharing, replace them with original educational market content.

**Important:** An interrupted or timed-out send may have reached Telegram. To prioritize avoiding duplicate rotation posts, the scheduler moves forward after an ambiguous network failure or an interrupted in-flight send rather than retrying that same step. Consequently, one message can occasionally be skipped. Rate-limited sends are retried later.

## Deployment and verification

After the GitHub commit, redeploy the existing Render service from `main` if automatic deployment is disabled. Keep its current BOT_TOKEN, ADMIN_ID, DATABASE_URL, and the existing Neon database. The new rotation table is created automatically; do not reset the database. Use a single worker for the token, and check `/admin` and the new REDIRECT confirmation to enable the sequence. A new code deployment by itself does **not** start a campaign.

Test locally: `python -m unittest -v test_storage.py test_bot.py test_rotation.py`. GitHub Actions also runs syntax and unit checks on commits.

## User storage

Neon stores Telegram ID, username, first/last names, language code, first/last interaction timestamps and active status for every private-chat user who interacts. No phone numbers or full message histories are collected. Settings, campaign content, scheduled rotation progress and delivery status also persist across redeploys. /stop stops pending/future broadcasts; /start opts in again. Other messages do not undo opt-out. Blocked recipients become inactive. Users who never interacted cannot be discovered by the bot.

The new Neon database starts empty. An old SQLite file is not automatically imported or deleted; preserve it separately if historical users must be migrated. A redeploy may erase an old SQLite file on ephemeral storage. Existing records need a migration before redeploy if they are the only copy.

DB operations run off the Telegram event loop; temporary connection failures reconnect before the next transaction. Telegram throttling/network failures retry. Manual campaign delivery remains at-least-once; scheduled rotation uses at-most-once attempts for uncertain in-flight sends, which favors avoiding duplicate marketing messages over guaranteed delivery. Keep one running worker. Switching modes is a business control, not a way to conceal content during advertising review; normal and redirect content should accurately describe the same service.

## Verification

`python -m unittest -v test_storage.py test_bot.py`
