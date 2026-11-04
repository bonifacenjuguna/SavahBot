# SavahBot

A personal, owner-only moderation and utility bot for YouTube live chat, controlled from a web dashboard and from Telegram.

- **Backend** (`backend/`): Python 3.13, Starlette + uvicorn, PostgreSQL (SQLite for local use). Runs on Railway.
- **Dashboard** (`frontend/`): Vite + TypeScript, no framework. Runs on Vercel.
- **Telegram**: webhook or polling, switchable at any time from the dashboard or with `/tgmode`.
- **Demo mode**: simulated chat and nine scenarios (raid, link spammer, caps flood, bot timing, disguised words, ...). Nothing is sent to YouTube or Telegram and no quota is used. Switch between Demo and Live in the sidebar; the lamp at the top shows which one you are in (amber = demo, red = on air, grey = standby).

There is no AI in this version. Moderation is a set of explainable algorithms, each of which shows up as a named signal with a weight, so you can always see why a message scored what it did.

---

## Deploy in about ten minutes

### 1. Backend on Railway

1. Create a Railway project from this repository and set the service **Root Directory** to `backend`. `railway.json` already holds the start command and the `/api/health` health check.
2. Add a **PostgreSQL** plugin. Railway sets `DATABASE_URL` for you.
3. Under **Variables**, set the ones you have. Every variable is optional. `backend/.env.example` (about 200, grouped) already holds the default for each one, so you can paste it into Railway as it is; the few lines that say `edit-me` are the ones only you can fill in (the app ignores `edit-me`, so leaving it is harmless). The ones worth setting first:

   | Variable | Why |
   |---|---|
   | `OWNER_PASSWORD` | Dashboard password. If empty, a random one is generated and printed **once** in the deploy logs. |
   | `PUBLIC_BASE_URL` | Your Railway URL, for example `https://savahbot.up.railway.app`. Needed for the Telegram webhook and Google sign-in. Railway's own domain is used if you leave it empty. |
   | `FRONTEND_URL` | Your Vercel URL. Added to the CORS allow-list. |
   | `TELEGRAM_BOT_TOKEN` | From @BotFather (step 3 below). |
   | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | From Google Cloud (step 4 below). |

4. Generate a public domain for the service, then open `https://<your-domain>/api/health`. You should see `{"ok": true, ...}`.
5. **Check the database once** (it is the one part that could not be tested against a real PostgreSQL here):

   ```bash
   railway run python scripts/check_db.py
   ```

   It prints `Database is ready.` or the exact step that failed.

### 2. Dashboard on Vercel

1. Import the repository, set **Root Directory** to `frontend`. Vite is detected automatically; `vercel.json` adds basic security headers.
2. Optionally set `VITE_API_URL` to your Railway URL. If you skip it, type the address on the sign-in screen (it is remembered in your browser).
3. Open the site and sign in with `OWNER_PASSWORD`. Then go to **Setup**: it lists which variables are missing and gives you the exact URLs to paste into Telegram and Google.

### 3. Telegram

1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token into `TELEGRAM_BOT_TOKEN`.
2. Redeploy. Open your bot in Telegram and send `/claim <your dashboard password>`. From then on only your account can use it; everyone else gets silence. Group chats are ignored.
3. Webhook is the default and needs `PUBLIC_BASE_URL`. To use polling instead, switch it on the Setup page (no public URL needed, handy for local work).

Commands: `/status /stats /quota /mode /mod /tgmode /pending /approve /reject /permit /say /demo /note /notes /delnote /remind /reminders /delremind /help`. Approval requests arrive with Approve and Reject buttons.

### 4. YouTube (one-time Google Cloud setup)

1. Go to <https://console.cloud.google.com/>, create a project, and enable **YouTube Data API v3**.
2. **OAuth consent screen**: choose External, add yourself as a **test user**, and add the scope `https://www.googleapis.com/auth/youtube.force-ssl`. Leaving the app in "Testing" is fine for one user, but Google expires test-mode refresh tokens after 7 days. To avoid reconnecting weekly, publish the app (Google only asks for verification when many people use it).
3. **Credentials** > Create credentials > **OAuth client ID** > Web application. Add the authorised redirect URI shown on the Setup page (it is `<PUBLIC_BASE_URL>/api/youtube/oauth/callback`).
4. Put the client ID and secret into Railway as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, redeploy, then press **Connect Google account** on the Setup page. Sign in with the Google account that owns the channel.
5. Switch to **Live** in the sidebar. When your stream starts, the bot finds it and attaches to the chat.

### Moderating someone else's channel (appointed moderator)

SavahBot keeps two identities apart:

| | What it is | Where it is set |
|---|---|---|
| **Signed-in account** (the moderator) | The Google account you press *Connect Google account* with. Every YouTube request, including deletes and bans, is made as this account. | The sign-in itself. `YOUTUBE_MODERATOR_ACCOUNT` is only an optional safety check. |
| **Target channel** | The channel whose live chat is read and moderated. | `YOUTUBE_TARGET_CHANNEL_ID` |

Example: Creator A owns the channel and streams. Creator B is appointed as A's moderator.
1. Creator A opens YouTube Studio > Settings > Community and adds Creator B's channel as a **moderator**. (Creator A never gives B a password.)
2. Creator B deploys SavahBot and presses **Connect Google account**, signing in as **B**.
3. Creator B sets `YOUTUBE_TARGET_CHANNEL_ID` to **A's** channel ID (starts with `UC`; in YouTube Studio it is under Settings > Channel > Advanced settings, or paste A's `@handle`).
4. SavahBot now reads and moderates **A's** live chat. The Setup page shows *Signed in as B* and *Moderating A*.

Finding the stream: if `YOUTUBE_VIDEO_ID` is set (an ID or a full video link), SavahBot uses that video and refuses it if it belongs to a different channel. If it is empty, SavahBot searches for the target channel's live stream. For someone else's channel, that search costs about 100 quota units, so it runs every `YOUTUBE_TARGET_DETECT_INTERVAL_SECONDS` (default 600) and may use at most `YT_DETECT_BUDGET_FRACTION` (25%) of the day's quota. **Pasting the live video link into `YOUTUBE_VIDEO_ID` (or the Settings page) is cheaper and attaches instantly.** If you own the target channel, SavahBot uses the cheap lookup of your own active broadcast instead and never searches.

What is documented, and what is not. YouTube's documentation says a channel **owner or a chat moderator** may ban users (`liveChatBans.insert`). For deleting messages (`liveChatMessages.delete`) the page's wording is unclear, and the documentation does not say whether a moderator-only account may look up another channel's live stream or read its chat. SavahBot therefore tries each operation with the moderator's credentials and reports YouTube's real answer. It never shows a success that YouTube did not confirm, and it does not retry a refused permission over and over. If YouTube refuses:
- reading the chat: state `no_permission`, with the instruction to ask the owner to appoint the signed-in account as a moderator;
- delete, ban or timeout: that approval is marked failed, with the reason (not a moderator, or the target is a moderator or the owner);
- an invalid or revoked login: a *Reconnect Google account* message.

If no target channel is set, SavahBot stops with a configuration error instead of guessing. If you own the channel, press **Moderate my own channel** on the Setup page, or set `YOUTUBE_TARGET_CHANNEL_ID` to your own channel ID.

**Safety checks you can rely on.**
- Signing in checks who signed in **before** the new login is saved. If `YOUTUBE_MODERATOR_ACCOUNT` is set and the account is wrong, or Google cannot say who it is, the sign-in is rejected and your previous connection stays exactly as it was. A sign-in that comes back without a refresh token is refused too, so two Google accounts are never mixed.
- With `YOUTUBE_MODERATOR_ACCOUNT` set, SavahBot will not read chat or take any action until Google has confirmed the signed-in account.
- If YouTube refuses an action because the account lacks permission, a delete batch stops at once and SavahBot does not ask again for `YOUTUBE_PERMISSION_RETRY_SECONDS` (default 300, five minutes).
- When a stream ends (`chatEndedEvent`), monitoring stops straight away. Repeated errors back off from 30 seconds up to five minutes.
- **Setup > Verify access** shows what the signed-in account has really been allowed to do. Reading is tested for real. Deleting and banning cannot be tested (YouTube has no dry run), so they show *Unverified* until a real action has been answered.

**Upgrading an existing installation.** Nothing is lost: your saved Google login, settings and data are kept. After upgrading, set `YOUTUBE_TARGET_CHANNEL_ID` (or press **Moderate my own channel** once). The old `YOUTUBE_CHANNEL_ID` still works as the target if you had set it, but is deprecated. `YOUTUBE_VIDEO_ID` works as before, and is now also checked against the target channel.

**Quota.** The default YouTube quota is 10,000 units a day. Reading chat is the expensive part, so the bot spreads a configurable share of the quota over the expected stream length (`YT_READ_BUDGET_FRACTION`, `YOUTUBE_EXPECTED_STREAM_HOURS`) and keeps a reserve for deletes, timeouts and bans. The sidebar shows how much is used. Sending or deleting a chat message costs 20 units and a ban or timeout 200 (all adjustable), and the bot checks it can afford a whole action before starting one.

---

## Moderation

Every chat message is normalised (Unicode folding, look-alike letters, leetspeak, zero-width characters, stretched letters) and scored from 0 to 100 by independent signals:

| Signal | What it catches |
|---|---|
| blacklist | Banned words and phrases, including spaced-out or disguised ones (Aho-Corasick), plus regex entries |
| link | Links from people who have not been permitted (`!permit <name>`) |
| caps, symbols, emotes, repetition, length | Shouting, noise, emote walls, stretched characters, walls of text |
| rate, duplicate | Flooding and repeating yourself |
| raid | Several accounts posting near-identical text (SimHash) |
| interval | Accounts posting at machine-regular intervals (timing variation) |
| new_chatter | Extra weight for accounts seen for the first time |

Score maps to flag, delete, timeout or ban, and repeat offenders climb a timeout ladder. Mods, the owner and regulars are exempt or softened by level.

**Modes** (Moderation page or `/mod`): *off* only logs; *suggest* (default) queues the action for your approval in the dashboard and Telegram; *auto* acts immediately and tells you. Messages loaded when the bot first attaches to a chat are stored but never moderated.

## Commands, timers and more

- Custom commands with variables: `$(user) $(touser) $(args) $(1) $(count) $(countdown ...) $(uptime) $(time) $(date) $(random 1 100) $(choose a|b) $(math 2+2) $(quote) $(urlfetch https://...)`. `$(math)` is parsed safely (never `eval`) and `$(urlfetch)` blocks private networks and redirects.
- Per-command user level and cooldowns, aliases, a live preview, and built-ins (`!commands !addcom !editcom !delcom !permit !quote !addquote !uptime`).
- Timers post only while the stream is live and after enough chat lines since the last post.
- Notes and reminders (`30m`, `2h30m`, `18:30`, `tomorrow 09:00`, `daily 08:00`, `every 2h`), delivered to Telegram and the Desk.
- Insights: activity timeline, top chatters, which signals fire most, and action outcomes.

## Run it locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env              # optional; everything has a default
uvicorn app.main:create_app --factory --reload --port 8000
python -m pytest                  # 190 tests

cd ../frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev
```

With no `DATABASE_URL` the backend uses a local SQLite file. On first start it prints a generated owner password in the log unless you set `OWNER_PASSWORD`. Add `CORS_ORIGINS=http://localhost:5173` for the dev server.

`backend/.env.example` is generated from `backend/app/config.py`. After adding a setting there, run `python scripts/gen_env_example.py` (a test fails if the file is stale). Settings marked editable can also be changed from the dashboard and then override the environment until you reset them.

## Layout

```
backend/
  app/config.py          every variable, default and description (single source of truth)
  app/moderation/        normalisation, Aho-Corasick, trackers, scoring engine
  app/commands/          command engine, safe variables, safe math
  app/hub.py             message pipeline and approval workflow
  app/services/          youtube, telegram, demo, scheduler
  app/api/               REST + live feed (Server-Sent Events)
  scripts/               gen_env_example.py, check_db.py
frontend/src/            main.ts (shell, login, router), pages/, events.ts (live feed)
```

## What was and was not verified

Verified here: 190 automated tests (moderation, commands, data layer, Telegram, YouTube including the moderator-vs-target scenarios, API) pass; the API was exercised over real HTTP; the dashboard was driven in a real browser (sign-in, live feed, approvals, command preview, mobile width, type-check).

Not verified, because this build environment could not reach them: the PostgreSQL adapter against a real server (use `scripts/check_db.py`), the real Google and Telegram APIs (the integrations are tested against local fakes written from the API documentation), a production `vite build` (package installs were blocked, so the dashboard was type-checked with `tsc` and run as compiled modules), and the Railway and Vercel deploys themselves. Expect to fix small things on the first real run; the Setup page and the logs are designed to make them easy to find.
