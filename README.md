# SavahBot

A personal, owner-only moderation and utility bot for YouTube live chat, controlled from a web dashboard and from Telegram. It can moderate **your own** livestream, or **someone else's** livestream where your Google account has been appointed a moderator (see [YouTube: two identities](#4-youtube-one-time-google-cloud-setup)).

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
   | `YOUTUBE_TARGET_CHANNEL_ID` | The channel whose live chat you moderate (starts with `UC`). **Not** the account you sign in with, unless you are moderating your own channel. See step 4. |

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

SavahBot keeps two identities apart. Mixing them up is the most common cause of "it connects but does nothing".

| | What it is | Where it comes from |
|---|---|---|
| **Authenticated account** | The Google/YouTube account SavahBot acts as: it reads chat, deletes messages and bans users with *this* account's permissions. It is the channel **owner**, or a person the owner **appointed as a moderator**. | The Google sign-in you do on the Setup page. SavahBot asks Google who signed in and shows it; it is never taken from a setting. |
| **Target channel** | The channel whose livestream chat is monitored and moderated. | `YOUTUBE_TARGET_CHANNEL_ID` |

If you moderate your own channel the two are the same channel. If you moderate somebody else's, they are different, and you sign in with **your own** Google account, never with the owner's. SavahBot never asks for anyone's password and never needs the owner's Google login.

**Google Cloud (once)**

1. Go to <https://console.cloud.google.com/>, create a project, and enable **YouTube Data API v3**.
2. **OAuth consent screen**: choose External, add yourself as a **test user**, and add the scope `https://www.googleapis.com/auth/youtube.force-ssl`. Leaving the app in "Testing" is fine for one user, but Google expires test-mode refresh tokens after 7 days. To avoid reconnecting weekly, publish the app (Google only asks for verification when many people use it).
3. **Credentials** > Create credentials > **OAuth client ID** > Web application. Add the authorised redirect URI shown on the Setup page (it is `<PUBLIC_BASE_URL>/api/youtube/oauth/callback`).
4. Put the client ID and secret into Railway as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` and redeploy.

**Tell SavahBot which channel to moderate**

5. Find the **target channel ID**: open the channel on YouTube > **About** > **Share channel** > **Copy channel ID**. It is 24 characters and starts with `UC`. A `@handle` does not work. (For your own channel you can also use <https://www.youtube.com/account_advanced>.) Set it in Railway as `YOUTUBE_TARGET_CHANNEL_ID`.
6. Press **Connect Google account** on the Setup page and sign in with **the account that will do the moderating**. The Setup page then shows `Signed in as: <name> (<channel id>)` and `Moderating channel: <channel id>`.
7. Switch to **Live** in the sidebar. When the stream starts, the bot finds it and attaches to the chat. Press **Verify access** on the Setup page at any time to see what YouTube really allows.

Optional: `YOUTUBE_MODERATOR_ACCOUNT` (a channel ID, `@handle` or name) makes SavahBot refuse to run if somebody connects a different Google account than you expect. It is a safety check only; it grants nothing.

#### Example: Creator A's stream, moderated by Creator B

- **Creator A** owns the channel `UCaaaaaaaaaaaaaaaaaaaaaa` and goes live.
- **Creator B** runs SavahBot and has their own channel `UCbbbbbbbbbbbbbbbbbbbbbb`.

1. Creator A appoints Creator B as a moderator: YouTube Studio > **Settings** > **Community moderation** > **User management**, paste Creator B's channel URL into **Standard moderators** (or **Managing moderators**) and save. Or, in the live chat, open the menu next to Creator B's name and choose **Add as moderator**. YouTube does not notify the moderator, so tell them. (Menu labels change from time to time; the YouTube Help page "Moderate live chat" has the current ones.)
2. Creator B sets, in Railway:

   ```
   YOUTUBE_TARGET_CHANNEL_ID=UCaaaaaaaaaaaaaaaaaaaaaa     # Creator A's channel: the stream to moderate
   YOUTUBE_MODERATOR_ACCOUNT=@creatorb                     # optional: Creator B's own account, as a safety check
   ```

3. Creator B presses **Connect Google account** and signs in with **Creator B's own Google account**. SavahBot now acts as Creator B on Creator A's chat. Creator A's password and Google login are never involved.
4. When Creator A goes live, SavahBot attaches to that chat. Deleting messages and banning use Creator B's moderator permissions.

#### How SavahBot finds the stream

| Situation | What SavahBot does |
|---|---|
| `YOUTUBE_VIDEO_ID` is set | Looks the video up (`videos.list`, 1 unit). It **must belong to the target channel**; otherwise SavahBot refuses to attach and says why. |
| The account **owns** the target channel | Asks for its own active broadcasts (`liveBroadcasts.list`, 1 unit). Works for public, unlisted and private streams. |
| The account is only a **moderator** | `liveBroadcasts.list` is owner-only, so SavahBot reads the target channel's public data instead: its recent uploads, then `videos.list`, about 2 units per check (1 when nothing changed). The live video's `activeLiveChatId` is then used for chat. |
| Moderator mode and the stream is **unlisted** or otherwise not public | Cannot be discovered. Pin it with `YOUTUBE_VIDEO_ID`. |
| `YOUTUBE_DISCOVERY_USE_SEARCH=true` | Also tries YouTube search for a live video. This costs 100 units per check, so it is off by default. |

SavahBot **never** falls back to the connected account's own channel. If `YOUTUBE_TARGET_CHANNEL_ID` is missing or malformed, the state is `config_error` and the message says what to set.

#### What happens when the account lacks permission

SavahBot reports what YouTube actually answered and never claims success it did not receive.

| You see | Meaning | What to do |
|---|---|---|
| `config_error` | Target channel missing or not a `UC…` ID. | Set `YOUTUBE_TARGET_CHANNEL_ID`. |
| `wrong_account` | The signed-in account is not the one in `YOUTUBE_MODERATOR_ACCOUNT`. | Reconnect with the right account, or fix/clear that setting. |
| `target_mismatch` | The pinned video belongs to a different channel. | Fix `YOUTUBE_VIDEO_ID` or `YOUTUBE_TARGET_CHANNEL_ID`. Nothing is attached. |
| `auth_error` | Google revoked or expired the login. | Press **Reconnect Google account** and sign in with the moderator account. |
| `no_permission` | YouTube refused to let the account **read** the chat. | Check the account can see that chat. SavahBot stops, then looks again after `YOUTUBE_PERMISSION_RETRY_SECONDS` (default 5 minutes). Nothing is moderated meanwhile. |
| "YouTube refused: … is not allowed to delete / ban …" | The account is not an appointed moderator of that channel. | Ask the owner to appoint it. The request is marked **failed**, and SavahBot does not retry that kind of action until the retry interval has passed. |
| "does not allow banning the chat owner or another moderator" | YouTube's own rule. | Nothing to fix. |

Not everything can be tested up front: YouTube has no dry run for deleting or banning, so **Verify access** shows those as *Unverified* until a real action has been answered by YouTube.

#### Upgrading an existing install (migration)

Existing installs keep their Google credentials, refresh token and database. **Your bot will not need a new sign-in.** One variable is new and required for live moderation:

1. Open the Setup page (or `GET /api/youtube/status`). It shows `Signed in as: <your channel> (UC…)`.
2. Set `YOUTUBE_TARGET_CHANNEL_ID` in Railway to that same `UC…` ID, if you moderate your own channel (or to the other channel's ID if you moderate someone else's), then redeploy.
3. Until it is set, live mode stays in `config_error` with a message that names the missing variable. Demo mode, Telegram and the dashboard are unaffected. This is deliberate: SavahBot will not quietly pick a channel for you.
4. `YOUTUBE_CHANNEL_ID` (previously informational) is still read as a deprecated alias of `YOUTUBE_TARGET_CHANNEL_ID`, so installs that already set it keep working. `YOUTUBE_VIDEO_ID` and `YOUTUBE_AUTO_DETECT_LIVE` keep their meaning, now applied to the target channel.

**Quota.** The default YouTube quota is 10,000 units a day. Reading chat is the expensive part, so the bot spreads a configurable share of the quota over the expected stream length (`YT_READ_BUDGET_FRACTION`, `YOUTUBE_EXPECTED_STREAM_HOURS`) and keeps a reserve for deletes, timeouts and bans. The sidebar shows how much is used. Sending or deleting a chat message costs 20 units and a ban or timeout 200 (all adjustable), and the bot checks it can afford a whole action before starting one. Looking for a stream while offline costs about 1 unit per check in owner mode and about 2 in moderator mode (`YOUTUBE_DETECT_INTERVAL_SECONDS`, default 90 s).

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
python -m pytest                  # 161 tests

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
  app/services/          youtube (account vs target channel, discovery, polling, moderation), telegram, demo, scheduler
  app/api/               REST + live feed (Server-Sent Events)
  scripts/               gen_env_example.py, check_db.py
frontend/src/            main.ts (shell, login, router), pages/, events.ts (live feed)
```

## What was and was not verified

**API behaviour checked against Google's documentation** (not against a live Google account; see below):

- `videos.list` returns `liveStreamingDetails.activeLiveChatId` for a live video, and Google's own live-chat guide says an API key or an OAuth token may be used. This is what lets a moderator find another channel's `liveChatId`.
- `liveBroadcasts.list` is a "your broadcasts" endpoint (`mine` / `broadcastStatus`); SavahBot uses it only when the signed-in account owns the target channel.
- `liveChatMessages.list` (5 units), `liveChatMessages.delete` (20 units) and `liveChatBans.insert` are documented as allowed for the channel owner **or a moderator of that live chat**. The documented refusals are `forbidden` / `insufficientPermissions` (not permitted), `liveChatBanInsertionNotAllowed` (owner or another moderator cannot be banned) and `modificationNotAllowed`.
- `search.list` costs 100 units, which is why it is opt-in.

**Tested automatically** (161 tests; the YouTube ones use a scripted fake of Google and YouTube, no real credentials): owner mode; appointed moderator on another channel (discovery, chat, delete, ban, all with the moderator's token and none through the owner-only endpoint); moderator who was never appointed (honest refusal, request marked failed, no retries); a pinned video from the wrong channel (rejected); missing or malformed target (clear error, no fallback); revoked or rejected login; a chat that refuses reading; the stream ending; wrong Google account; the deprecated `YOUTUBE_CHANNEL_ID` alias; secrets never appearing in status or errors.

**Not verified**, because no real Google account, YouTube stream or network was available to the build:

- That a **real appointed moderator's token** is accepted by YouTube for `liveChatMessages.delete` and `liveChatBans.insert` on a **channel it does not own**. The documentation says yes; the first real action is the proof, and the Setup page shows these as *Unverified* until then.
- Whether a stream's video **always appears among the channel's recent uploads** while it is live. This is the cheap moderator-mode discovery path. If your stream is not found, pin it with `YOUTUBE_VIDEO_ID` or turn on `YOUTUBE_DISCOVERY_USE_SEARCH`.
- Whether **members-only** chats can be read by a moderator through the API.
- The OAuth callback and the new `/api/youtube/verify` route over real HTTP, the PostgreSQL adapter (use `scripts/check_db.py`), a production `vite build`, and the Railway and Vercel deploys. (The route logic they call is covered by the YouTube tests, and the dashboard code type-checks with `tsc`.)

Expect to fix small things on the first real run; the Setup page and the logs are designed to make them easy to find.
