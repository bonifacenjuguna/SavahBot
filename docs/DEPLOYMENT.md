# Deployment guide

Backend on Railway, dashboard on Vercel. The Firebase, weather, security and backup steps are in their own guides (linked at the end).

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

### 4. YouTube (details: YOUTUBE.md) (one-time Google Cloud setup)

1. Go to <https://console.cloud.google.com/>, create a project, and enable **YouTube Data API v3**.
2. **OAuth consent screen**: choose External, add yourself as a **test user**, and add the scope `https://www.googleapis.com/auth/youtube.force-ssl`. Leaving the app in "Testing" is fine for one user, but Google expires test-mode refresh tokens after 7 days. To avoid reconnecting weekly, publish the app (Google only asks for verification when many people use it).
3. **Credentials** > Create credentials > **OAuth client ID** > Web application. Add the authorised redirect URI shown on the Setup page (it is `<PUBLIC_BASE_URL>/api/youtube/oauth/callback`).
4. Put the client ID and secret into Railway as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, redeploy, then press **Connect Google account** on the Setup page. Sign in with the Google account that owns the channel.
5. Switch to **Live** in the sidebar. When your stream starts, the bot finds it and attaches to the chat.


### 5. Optional: push notifications, Redis, passkeys
- Push: follow NOTIFICATIONS.md (Firebase console walkthrough). Seven values, all on Railway.
- Redis: REDIS.md. Needed only when running more than one backend instance.
- Passkeys: they need `FRONTEND_URL` set to your real https dashboard address (the passkey is bound to that hostname; changing the domain later invalidates passkeys, use the authenticator app or a recovery code to get in and add new ones).
- Weather: nothing to deploy, no key. See WEATHER.md for the licence note.
- Back up: make your first encrypted export (BACKUP_AND_RECOVERY.md) and store the key somewhere other than the backup file.

### Updating from 1.1.x
Deploy the new code. On first start the database upgrades itself (new tables only; nothing is dropped). **Everyone is signed out once** because sign-in tokens changed; sign in with your password. Then open Security to add a second method, Notifications to turn on push, and Weather to add a place. `NTFY_*`, `WEATHER_API_KEY` and `GIPHY_API_KEY` are no longer read; remove them.

### Rolling back
Redeploy the previous version. New tables are ignored by old code. Sessions from 1.2.0 will not be understood by 1.1.x (you sign in again). Restore from a backup if you changed data you want back.

### Related guides
SECURITY.md, NOTIFICATIONS.md, PWA_AND_PUSH_PLATFORMS.md, WEATHER.md, SETTINGS.md, BACKUP_AND_RECOVERY.md, ENVIRONMENT.md, TROUBLESHOOTING.md.
