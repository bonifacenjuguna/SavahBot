# Environment variables

Generated from `backend/app/config.py` by `python scripts/gen_env_doc.py`, so it always matches the code. The same table, with defaults, is in `backend/.env.example` (paste it into Railway as is).

**Where to set them.** Every variable below goes on the **backend (Railway)**. The dashboard (Vercel) needs at most one: `VITE_API_URL`, the backend's address (optional; you can also type it on the sign-in screen). Firebase *web* values are public by design, but you still set them on the backend only: it hands them to the dashboard.

**The `edit-me` rule.** Lines in `.env.example` that say `edit-me` are the ones only you can fill in. The app treats `edit-me` as empty, so leaving them is harmless.

**Never commit** secrets (marked SECRET), and never put them on Vercel. Most options can also be changed later in the dashboard under Settings > All settings; secrets cannot, they stay in the environment.

Removed in 1.2.0: `NTFY_URL`, `NTFY_TOPIC` (push now uses Firebase), `WEATHER_API_KEY` (Open-Meteo needs no key), `GIPHY_API_KEY` (GIPHY was removed).


## App

| Variable | Default | What it does |
|---|---|---|
| `APP_NAME` | `SavahBot` | Display name used in the dashboard and Telegram messages. |
| `APP_ENV` | `production` | 'production' or 'development'. |
| `LOG_LEVEL` | `INFO` | Python log level: DEBUG, INFO, WARNING or ERROR. |
| `PUBLIC_BASE_URL` | `edit-me` | Public HTTPS URL of this backend, e.g. https://savahbot.up.railway.app. Needed for the Telegram webhook and the Google OAuth redirect. Falls back to RAILWAY_PUBLIC_DOMAIN. |
| `RAILWAY_PUBLIC_DOMAIN` | blank (Railway sets this itself) | Injected automatically by Railway. Leave empty. |
| `FRONTEND_URL` | `edit-me` | Public URL of the Vercel dashboard. Added to the CORS allow-list. |
| `CORS_ORIGINS` | blank (only needed for extra dashboard addresses; FRONTEND_URL is already allowed) | Extra allowed browser origins, comma separated. |
| `OWNER_TIMEZONE` | `Africa/Nairobi` | IANA timezone used to read reminder times such as 18:30 and to show local times. |
| `BOT_MODE` | `demo` | Active chat source: 'demo' (simulated chat) or 'live' (YouTube). Switchable at runtime from the dashboard or Telegram. |
| `API_DOCS_ENABLED` | `False` | Expose /docs and /openapi.json (interactive API docs). |
| `SSE_MAX_CLIENTS` | `10` | Maximum simultaneous dashboard live-feed connections. |
| `CHAT_BUFFER_SIZE` | `500` | How many recent chat messages are kept in memory for the live view. |
| `CHAT_RETENTION_DAYS` | `90` | Chat messages older than this are deleted automatically. Daily totals are kept forever, so charts still reach back further. |
| `ACTION_RETENTION_DAYS` | `365` | Moderation history older than this is deleted automatically. Daily totals are kept forever. |

## Security

| Variable | Default | What it does |
|---|---|---|
| `OWNER_PASSWORD` **SECRET** | `edit-me` | Dashboard login password. If empty, a random one is generated on first boot and printed ONCE in the server logs. |
| `JWT_SECRET` **SECRET** | blank (generated and stored automatically on first start) | Secret used to sign login tokens. If empty, a random one is generated and stored in the database. |
| `JWT_EXPIRE_HOURS` | `72` | How long a dashboard login stays valid. |
| `SESSION_IDLE_MINUTES` | `1440` | Sign a dashboard session out after this many minutes without use. 0 turns the idle limit off. |
| `SECURITY_STEP_UP_MINUTES` | `5` | After you re-confirm it is you, sensitive security actions stay unlocked for this many minutes. |
| `SECURITY_MAX_SESSIONS` | `10` | Most dashboard sessions open at once. The least recently used is closed when this is exceeded. |
| `SECURITY_LOG_RETENTION_DAYS` | `365` | How long sign-in activity and the security audit log are kept. |
| `WEBAUTHN_RP_ID` | blank | Passkey site id. Leave empty to use the host name of FRONTEND_URL (for example dash.example.app). Must be the dashboard's host, not the API's. |
| `WEBAUTHN_ORIGINS` | blank | Comma-separated dashboard origins allowed to use passkeys. Leave empty to use FRONTEND_URL. |
| `WEBAUTHN_REQUIRE_UV` | `False` | Require passkeys to verify you (fingerprint, face or PIN). Turn on if every passkey you use supports it. |
| `TRUSTED_PROXY_HOPS` | `1` | How many reverse proxies sit in front of this server and append to X-Forwarded-For (Railway: 1). Used to find the real client address for the sign-in lockout; addresses a client adds to the left of that are ignored. 0 means no proxy: the connection's own address is used. |
| `LOGIN_MAX_ATTEMPTS` | `5` | Failed logins allowed before the lockout starts. |
| `LOGIN_LOCKOUT_MINUTES` | `15` | How long a locked-out client must wait. |

## Notifications (Firebase Cloud Messaging)

| Variable | Default | What it does |
|---|---|---|
| `FIREBASE_PROJECT_ID` _public by design_ | `edit-me` | Firebase project ID (Project settings > General). Needed to send push notifications. |
| `FIREBASE_CLIENT_EMAIL` **SECRET** | `edit-me` | Service account e-mail (the client_email in the service-account JSON). Backend only; never shown in the dashboard. |
| `FIREBASE_PRIVATE_KEY` **SECRET** | `edit-me` | Service account private key (the private_key in the JSON). Paste it with \n for line breaks. Backend only; never commit it. |
| `FIREBASE_SERVICE_ACCOUNT_JSON` **SECRET** | blank (optional: use it instead of FIREBASE_CLIENT_EMAIL and FIREBASE_PRIVATE_KEY) | Alternative to the two lines above: the whole service-account JSON, or the same JSON base64 encoded. Backend only. |
| `FIREBASE_WEB_API_KEY` _public by design_ | `edit-me` | Firebase web app apiKey (Project settings > Your apps). Public by design; the dashboard needs it to receive pushes. |
| `FIREBASE_WEB_APP_ID` _public by design_ | `edit-me` | Firebase web app appId. Public by design. |
| `FIREBASE_MESSAGING_SENDER_ID` _public by design_ | `edit-me` | Firebase messagingSenderId (Cloud Messaging tab). Public by design. |
| `FIREBASE_AUTH_DOMAIN` _public by design_ | blank (not needed for push notifications) | Optional Firebase authDomain. Not needed for push; leave blank. |
| `FIREBASE_VAPID_KEY` _public by design_ | `edit-me` | Web Push certificate public key (Cloud Messaging > Web configuration > Generate key pair). Public by design. |
| `ACTIVITY_RETENTION_DAYS` | `365` | How long the activity log is kept. 0 keeps it forever. |
| `ACTIVITY_NOTIFY_SENSITIVE` | `False` | Send a notification when a sensitive change is logged, such as a security or sign-in setting. |
| `VOICE_DIR` | `data/voices` | Folder where voice packs for the chat reader are stored. On Railway, attach a Volume at this path or uploads are lost on redeploy. |
| `VOICE_PACK_MAX_MB` | `300` | Most megabytes of voice files you can keep. Uploads that would pass this are refused. |
| `NOTIFY_RETENTION_DAYS` | `30` | Notification history older than this is deleted automatically. |
| `NOTIFY_MAX_PUSH_PER_HOUR` | `30` | Most push messages sent per hour. Extras are folded into one summary. |
| `NOTIFY_MAX_ATTEMPTS` | `5` | Times a failed push is retried (with growing delays) before it is marked failed. |

## Weather (Open-Meteo)

| Variable | Default | What it does |
|---|---|---|
| `WEATHER_COMMERCIAL_API_KEY` **SECRET** | blank (only for a paid Open-Meteo plan; the free service needs no key) | Only if you have bought an Open-Meteo commercial plan: its API key. Leave blank for the free, non-commercial service (no key needed). |
| `WEATHER_FORECAST_TTL_MINUTES` | `15` | How long a fetched forecast counts as fresh before the next request goes to Open-Meteo. |
| `WEATHER_STALE_MAX_HOURS` | `12` | If Open-Meteo is unreachable, a forecast up to this old can still be shown (clearly marked as old). Alerts never use it. |
| `WEATHER_GEOCODE_TTL_HOURS` | `168` | How long place-search results are remembered. |
| `WEATHER_TIMEOUT_SECONDS` | `8` | How long to wait for Open-Meteo before giving up on one try. |
| `WEATHER_RETRIES` | `2` | Extra tries after a temporary failure, with growing pauses. |

## Database

| Variable | Default | What it does |
|---|---|---|
| `DATABASE_URL` | blank (Railway sets this when you add PostgreSQL; blank means a local SQLite file) | PostgreSQL URL (Railway sets DATABASE_URL for you). Empty = local SQLite file, fine for local testing only. |
| `DB_POOL_SIZE` | `5` | Database connection pool size (PostgreSQL). |
| `DB_ECHO` | `False` | Log every SQL statement (debugging). |

## Telegram

| Variable | Default | What it does |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` **SECRET** | `edit-me` | Bot token from @BotFather. |
| `TELEGRAM_OWNER_ID` | `0` | Your numeric Telegram user id. If 0, send /claim <OWNER_PASSWORD> to the bot once to bind yourself. |
| `TELEGRAM_MODE` | `webhook` | 'webhook' (recommended on Railway) or 'polling'. Switchable at runtime with /tgmode. |
| `TELEGRAM_WEBHOOK_SECRET` **SECRET** | blank (generated and stored automatically) | Secret Telegram must send with every webhook call. If empty, one is generated and stored. |
| `TELEGRAM_WEBHOOK_MAX_CONNECTIONS` | `40` | Parallel webhook connections Telegram may open (1-100). |
| `TELEGRAM_ALLOWED_UPDATES` | `message,callback_query` | Update types requested from Telegram, comma separated. |
| `TELEGRAM_POLL_TIMEOUT` | `30` | Long-poll timeout in seconds (polling mode). |
| `TELEGRAM_API_BASE` | `https://api.telegram.org` | Telegram Bot API base URL (change only for a local Bot API server). |
| `TELEGRAM_DROP_PENDING_UPDATES` | `False` | Discard queued updates when switching modes. |
| `TELEGRAM_NOTIFY_PENDING` | `True` | Message you when moderation wants approval. |
| `TELEGRAM_NOTIFY_MAX_PER_MIN` | `6` | Cap on approval messages per minute; extras are summarised. |
| `TELEGRAM_NOTIFY_REMINDERS` | `True` | Deliver reminders to Telegram. |
| `TELEGRAM_NOTIFY_STREAM_EVENTS` | `True` | Message you when the stream goes live or ends, and on quota warnings. |

## Google / YouTube

| Variable | Default | What it does |
|---|---|---|
| `GOOGLE_CLIENT_ID` | `edit-me` | OAuth client id from Google Cloud Console (YouTube Data API v3 enabled). |
| `GOOGLE_CLIENT_SECRET` **SECRET** | `edit-me` | OAuth client secret. |
| `GOOGLE_REDIRECT_URI` | blank (built from PUBLIC_BASE_URL automatically) | OAuth redirect URI. Empty = PUBLIC_BASE_URL + /api/youtube/oauth/callback (add this exact URL in Google Cloud). |
| `YOUTUBE_REFRESH_TOKEN` **SECRET** | blank (filled in when you press Connect on the Setup page) | Optional: paste a refresh token here, or connect from the dashboard and it is stored for you. |
| `YOUTUBE_MODERATOR_ACCOUNT` | blank (optional safety check, not required) | Optional safety check: the Google account that should be signed in, as its channel ID (UC...) or @handle. If a different account is signed in, SavahBot reports it. It never grants any permission. |
| `YOUTUBE_TARGET_CHANNEL_ID` | `edit-me` | The channel whose live chat SavahBot moderates, as a channel ID (UC...) or @handle. Your own channel if you are the owner; the creator's channel if you were appointed their moderator. Not the same thing as the Google account you sign in with. |
| `YOUTUBE_CHANNEL_ID` | blank (deprecated, use YOUTUBE_TARGET_CHANNEL_ID) | Deprecated: use YOUTUBE_TARGET_CHANNEL_ID. If that is empty, this value is used as the target channel. |
| `YOUTUBE_VIDEO_ID` | blank (blank means find the live stream automatically) | Optional: monitor this specific live video (ID or full URL). It must belong to the target channel, otherwise SavahBot refuses to attach. |
| `GOOGLE_OAUTH_AUTH_URL` | `https://accounts.google.com/o/oauth2/v2/auth` | Google OAuth consent URL. |
| `GOOGLE_OAUTH_TOKEN_URL` **SECRET** | `https://oauth2.googleapis.com/token` | Google OAuth token URL. |
| `GOOGLE_OAUTH_SCOPE` | `https://www.googleapis.com/auth/youtube.force-ssl` | OAuth scope. force-ssl is required to read chat, delete messages and ban users. |
| `YOUTUBE_API_KEY` **SECRET** | `edit-me` | Reserved: API key for public (unauthenticated) reads. |
| `YOUTUBE_API_BASE` | `https://www.googleapis.com/youtube/v3` | YouTube Data API base URL. |
| `YOUTUBE_AUTO_DETECT_LIVE` | `True` | Automatically find the target channel's live stream when no video ID is set. |
| `YOUTUBE_DETECT_INTERVAL_SECONDS` | `180` | How often to check for a live broadcast while offline (costs 1 quota unit per check). |
| `YOUTUBE_EXPECTED_STREAM_HOURS` | `4.0` | Typical stream length. The quota governor paces chat polling so a stream this long fits the daily budget. |
| `YOUTUBE_MAX_RESULTS` | `200` | Chat messages requested per poll (200-2000). |
| `YOUTUBE_PERMISSION_RETRY_SECONDS` | `300` | After YouTube refuses an action because this account lacks permission, wait this long before trying that kind of action (or reading that chat) again. |
| `YOUTUBE_USE_STREAMING` | `False` | Reserved: use the streamList (gRPC) endpoint instead of polling. |
| `YOUTUBE_MESSAGE_MAX_LENGTH` | `200` | Longest message YouTube chat accepts; bot replies are trimmed to this. |
| `YOUTUBE_BACKFILL_ON_CONNECT` | `True` | Store the chat history found on connect (not moderated). |

## YouTube quota

| Variable | Default | What it does |
|---|---|---|
| `YT_DAILY_QUOTA` | `10000` | Daily quota units available to your Google Cloud project. |
| `YT_QUOTA_RESET_TZ` | `America/Los_Angeles` | Timezone where YouTube resets quota (midnight Pacific). |
| `YT_COST_CHAT_LIST` | `5` | Quota cost: read chat messages. Verify against the current YouTube docs. |
| `YT_COST_CHAT_INSERT` | `20` | Quota cost: send a chat message. |
| `YT_COST_CHAT_DELETE` | `20` | Quota cost: delete a chat message. |
| `YT_COST_BAN` | `200` | Quota cost: ban / time out a user. |
| `YT_COST_BROADCAST_LIST` | `1` | Quota cost: look up your live broadcast. |
| `YT_COST_VIDEO_LIST` | `1` | Quota cost: look up a video. |
| `YT_COST_CHANNEL_LIST` | `1` | Quota cost: look up a channel (the signed-in account, or a @handle). |
| `YT_COST_SEARCH` | `100` | Quota cost: search for a channel's live stream. Verify against the current YouTube docs. |
| `YT_DETECT_BUDGET_FRACTION` | `0.1` | Share of the daily quota that searching for another channel's live stream may use. |
| `YOUTUBE_TARGET_DETECT_INTERVAL_SECONDS` | `900` | How often to search for a live stream on a channel you do not own while it is offline. Searching is expensive, so it is also capped by YT_DETECT_BUDGET_FRACTION. Set YOUTUBE_VIDEO_ID to avoid searching. |
| `YT_COST_SUBSCRIPTION_LIST` | `1` | Quota cost: check recent subscribers. Verify against the current YouTube docs. |
| `YT_EVENTS_NOTIFY` | `True` | Tell me (bell, push, Telegram per the category settings) about new members, Super Chats, Super Stickers and membership gifts. |
| `YT_EVENTS_THANK` | `False` | Post a thank-you in chat for members, Super Chats and gifts. Off by default: it costs YouTube quota for every message. |
| `YT_EVENTS_MSG_MEMBER` | `Welcome to the members, $(user)! 💚` | Thank-you for a new member. $(user) and $(count) are filled in; your own variables work too. |
| `YT_EVENTS_MSG_SUPERCHAT` | `Thank you $(user) for the $(amount)!` | Thank-you for a Super Chat or Super Sticker. $(user) and $(amount) are filled in. |
| `YT_EVENTS_MSG_GIFT` | `Thank you $(user) for gifting $(count) memberships!` | Thank-you for membership gifts. $(user) and $(count) are filled in. |
| `YT_SUBS_ENABLED` | `True` | Look for new subscribers while you are live. Best effort: YouTube only lists subscribers who made their subscription public. |
| `YT_SUBS_MINUTES` | `10` | How often to check for new subscribers, in minutes (5 to 120). Each check costs about 1 quota unit. |
| `YT_SUBS_THANK` | `False` | Post a thank-you in chat for a new subscriber you can see by name. |
| `YT_SUBS_MSG` | `Thanks for subscribing, $(user)! 🎉` | Thank-you for a new subscriber. $(user) is filled in. |
| `YT_SUBS_MILESTONE_STEP` | `100` | Alert me each time the subscriber count passes a multiple of this. 0 turns milestones off. |
| `YT_LIVE_ENABLED` | `True` | Track likes and people watching while you are live. |
| `YT_LIVE_SECONDS` | `60` | How often to refresh likes and viewers, in seconds (30 to 600). Each refresh costs about 1 quota unit. |
| `YT_LIVE_LIKES_STEP` | `100` | Alert me each time likes pass a multiple of this. 0 turns it off. |
| `YT_LIVE_VIEWERS_STEP` | `50` | Alert me each time viewers pass a multiple of this for the first time in a stream. 0 turns it off. |
| `YT_COST_MODERATOR_LIST` | `50` | Quota cost: list moderators. |
| `YT_READ_BUDGET_FRACTION` | `0.6` | Share of the daily quota the bot may spend reading chat (the rest is kept for actions). |
| `YT_MIN_POLL_SECONDS` | `5.0` | Never poll chat faster than this. |
| `YT_MAX_POLL_SECONDS` | `60.0` | Never wait longer than this between polls. |
| `YT_QUOTA_WARN_FRACTION` | `0.8` | Warn on Telegram when this share of the daily quota is used. |

## Moderation

| Variable | Default | What it does |
|---|---|---|
| `MOD_MODE` | `suggest` | 'off' (no checks), 'suggest' (ask you to approve actions) or 'auto' (act by itself). Switchable at runtime. |
| `MOD_AUTO_ACTIONS` | `delete,timeout` | Actions allowed to run without approval in auto mode. Bans always wait for you unless 'ban' is listed. |
| `MOD_EXEMPT_LEVELS` | `owner,mod,bot` | Chat levels that are never moderated. |
| `MOD_EXEMPT_REGULARS` | `True` | Regulars are never moderated. |
| `MOD_EXEMPT_MEMBERS` | `False` | Paying members are never moderated. |
| `MOD_SCORE_FLAG` | `30` | Score at which a message is flagged (logged only). |
| `MOD_SCORE_DELETE` | `55` | Score at which a message is deleted. |
| `MOD_SCORE_TIMEOUT` | `90` | Score at which the author is timed out. |
| `MOD_SCORE_BAN` | `100` | Score at which the author is banned. |
| `MOD_TIMEOUT_LADDER` | `60,300,900,3600` | Timeout seconds for the first, second, third... timeout. Each extra strike climbs one rung. |
| `MOD_STRIKE_DECAY_MINUTES` | `60` | Strikes expire after this many minutes. |
| `MOD_STRIKES_TO_TIMEOUT` | `2` | Strikes before a delete escalates to a timeout. |
| `MOD_STRIKES_TO_BAN` | `4` | Strikes before a timeout escalates to a ban. |
| `MOD_ALLOW_BAN_ESCALATION` | `True` | Allow escalation to bans (bans cost the most YouTube quota). |
| `MOD_MAX_PUNISHMENT` | `ban` | The harshest action the bot may ever take: 'delete' (messages only, nobody is timed out or banned), 'timeout' or 'ban'. Lower actions are unaffected. |
| `MOD_NEVER_PUNISH` | blank | Comma-separated names or channel ids that are never timed out or banned. Their bad messages are still deleted. |
| `MOD_REASON_CAPS` | blank | Cap the harshest action for one kind of trigger, as name:action pairs, e.g. 'link:delete,caps:delete,raid:ban'. Names are the signal names shown on each moderation card. |
| `MOD_AUTO_PUNISH_DAILY_CAP` | `0` | Most automatic timeouts and bans per day. After that the bot only deletes. 0 means no limit. |
| `MOD_SECOND_CHANCE_HOURS` | `0` | Automatically lift permanent bans the bot made by itself after this many hours (each lift costs YouTube quota). 0 means never. |
| `MOD_PENDING_TTL_MINUTES` | `30` | Unanswered approval requests expire after this long, so stale bans are never approved by accident. |
| `MOD_MAX_DELETES_PER_ACTION` | `10` | Messages deleted when one grouped action is approved (protects quota). |
| `MOD_ACTION_COOLDOWN_SECONDS` | `60` | Do not repeat a timeout/ban on the same user within this window. |
| `MOD_NOTIFY_ON_FLAG` | `False` | Also message you for flag-level events. |
| `MOD_NEW_CHATTER_SECONDS` | `120` | A chatter is 'new' for this long after their first message. |
| `MOD_NEW_CHATTER_WEIGHT` | `15` | Extra score for a new chatter who already triggered another signal. |
| `MOD_CAPS_ENABLED` | `True` | Detect shouting (mostly capital letters). |
| `MOD_CAPS_MIN_LENGTH` | `20` | Messages shorter than this are never caps-checked. |
| `MOD_CAPS_RATIO` | `0.7` | Share of letters that must be capitals to trigger. |
| `MOD_CAPS_WEIGHT` | `30` | Score added by the caps signal. |
| `MOD_SYMBOLS_ENABLED` | `True` | Detect symbol spam. |
| `MOD_SYMBOLS_MIN_LENGTH` | `10` | Messages shorter than this are never symbol-checked. |
| `MOD_SYMBOLS_RATIO` | `0.5` | Share of non-alphanumeric characters that triggers. |
| `MOD_SYMBOLS_WEIGHT` | `25` | Score added by the symbol signal. |
| `MOD_EMOTES_ENABLED` | `True` | Detect emote/emoji floods. |
| `MOD_EMOTES_MAX` | `8` | Emotes allowed in one message. |
| `MOD_EMOTES_WEIGHT` | `20` | Score added by the emote signal. |
| `MOD_LINKS_ENABLED` | `True` | Detect links (including 'site dot com' disguises). |
| `MOD_LINKS_WEIGHT` | `45` | Score added by the link signal. |
| `MOD_ALLOWED_DOMAINS` | `youtube.com,youtu.be` | Domains that are always allowed, comma separated. |
| `MOD_PERMIT_SECONDS` | `60` | How long !permit lets someone post links. |
| `MOD_REPEAT_ENABLED` | `True` | Detect repeated characters and words. |
| `MOD_REPEAT_CHAR_RUN` | `10` | Same character in a row that triggers. |
| `MOD_REPEAT_WORD_RATIO` | `0.6` | Share of repeated words (in messages of 6+ words) that triggers. |
| `MOD_REPEAT_WEIGHT` | `25` | Score added by the repetition signal. |
| `MOD_LENGTH_ENABLED` | `True` | Detect overly long messages. |
| `MOD_MAX_LENGTH` | `300` | Longest normal message. |
| `MOD_LENGTH_WEIGHT` | `15` | Score added by the length signal. |
| `MOD_BLACKLIST_ENABLED` | `True` | Match the banned-phrase list (handles leetspeak, look-alike letters, spacing). |
| `MOD_BLACKLIST_WEIGHT` | `70` | Default score for a banned phrase (each phrase can override it). |
| `MOD_RATE_ENABLED` | `True` | Limit how fast one user may post. |
| `MOD_RATE_MAX_MESSAGES` | `5` | Messages allowed per window. |
| `MOD_RATE_WINDOW_SECONDS` | `10` | Rate-limit window length. |
| `MOD_RATE_NEW_CHATTER_MAX` | `3` | Messages allowed per window for new chatters. |
| `MOD_RATE_WEIGHT` | `40` | Score added by the rate signal. |
| `MOD_DUP_ENABLED` | `True` | Detect the same user repeating a message. |
| `MOD_DUP_WINDOW_SECONDS` | `60` | Window in which a repeat counts. |
| `MOD_DUP_WEIGHT` | `35` | Score added by the duplicate signal (60% for the first repeat). |
| `MOD_SIM_ENABLED` | `True` | Detect copy-paste raids: near-identical messages from several accounts. |
| `MOD_SIM_WINDOW_SECONDS` | `120` | Window for cross-account similarity. |
| `MOD_SIM_MAX_DISTANCE` | `8` | Max SimHash bit distance (of 64) to call two messages similar. Lower = stricter. |
| `MOD_SIM_MIN_ACCOUNTS` | `4` | Distinct accounts posting similar text before it counts as a raid. |
| `MOD_SIM_MIN_LENGTH` | `12` | Shortest message considered for similarity. |
| `MOD_SIM_WEIGHT` | `45` | Score added by the raid signal. |
| `MOD_INTERVAL_ENABLED` | `True` | Detect bots posting at machine-regular intervals. |
| `MOD_INTERVAL_MIN_MESSAGES` | `5` | Messages needed before timing is judged. |
| `MOD_INTERVAL_MAX_CV` | `0.15` | Timing variation (std/mean) below this looks automated. |
| `MOD_INTERVAL_MAX_MEAN_GAP` | `120.0` | Only judge users whose average gap is under this many seconds. |
| `MOD_INTERVAL_WEIGHT` | `30` | Score added by the timing signal. |

## Intelligence

| Variable | Default | What it does |
|---|---|---|
| `INTEL_ENABLED` | `True` | Master switch for the intelligence layer (phrase packs, typo matching, link intelligence, scam intent, statistics). Off = the bot behaves exactly as in 1.1.5. |
| `INTEL_MAX_WEIGHT` | `60` | The most score the intelligence layer can add to one message on its own. Keeps it from banning anyone by itself. |
| `INTEL_SCAM_MODE` | `live` | Scam phrases and scam-intent scoring: off, shadow (logged, never scored) or live. |
| `INTEL_SPAM_MODE` | `live` | Spam and promotion phrases: off, shadow or live. |
| `INTEL_ABUSE_MODE` | `shadow` | Profanity and insults: off, shadow or live. Shadow by default so you can review what it would catch first. |
| `INTEL_HARASSMENT_MODE` | `live` | Threats and harassment (death wishes, doxxing, swatting): off, shadow or live. |
| `INTEL_TYPO_MODE` | `live` | Typo and disguise matching of blocked and known-bad phrases: off, shadow or live. |
| `INTEL_LINK_RISK_MODE` | `live` | Link intelligence (look-alike domains, shorteners, threat lists): off, shadow or live. |
| `INTEL_IMPERSONATION_MODE` | `live` | Impersonation guard (copied or staff-like account names, 'I am the admin'): off, shadow or live. |
| `INTEL_OBFUSCATION_MODE` | `live` | Text tricks (zalgo, hidden characters, mixed alphabets, symbol art): off, shadow or live. |
| `INTEL_BOT_LIKE_MODE` | `shadow` | Bot-like account names: off, shadow or live. |
| `INTEL_INTENT_MODE` | `shadow` | Naive Bayes spam-likeness: off, shadow or live. |
| `INTEL_KNOWN_SPAM_MODE` | `shadow` | Similarity to known spam messages (BM25): off, shadow or live. |
| `INTEL_RAID_WAVE_MODE` | `live` | Raid wave tracker: off, shadow or live. |
| `INTEL_SCAM_SCALE` | `1.0` | Strength multiplier for the scam detector (0.5 = half as strong, 2 = twice). |
| `INTEL_SPAM_SCALE` | `1.0` | Strength multiplier for the spam detector. |
| `INTEL_ABUSE_SCALE` | `1.0` | Strength multiplier for the abuse detector. |
| `INTEL_HARASSMENT_SCALE` | `1.0` | Strength multiplier for the threats and harassment detector. |
| `INTEL_TYPO_SCALE` | `1.0` | Strength multiplier for typo matching. |
| `INTEL_LINK_RISK_SCALE` | `1.0` | Strength multiplier for link intelligence. |
| `INTEL_IMPERSONATION_SCALE` | `1.0` | Strength multiplier for the impersonation guard. |
| `INTEL_OBFUSCATION_SCALE` | `1.0` | Strength multiplier for text-trick detection. |
| `INTEL_BOT_LIKE_SCALE` | `1.0` | Strength multiplier for bot-like accounts. |
| `INTEL_INTENT_SCALE` | `1.0` | Strength multiplier for the Naive Bayes detector. |
| `INTEL_KNOWN_SPAM_SCALE` | `1.0` | Strength multiplier for known-spam similarity. |
| `INTEL_RAID_WAVE_SCALE` | `1.0` | Strength multiplier for the raid wave bonus. |
| `INTEL_CONTEXT_ENABLED` | `True` | Understand context: a question about a scam, or a warning to others, scores lower than the scam itself. |
| `INTEL_SAFE_ENABLED` | `True` | Use the safe phrases (gaming talk such as 'kill streak') to stop rules firing on normal chat. |
| `INTEL_LANGUAGES` | `en,sw,sheng` | Which language packs are active, comma separated: en, sw (Swahili), sheng. |
| `INTEL_PROTECTED_NAMES` | blank | Names the impersonation guard protects, comma separated (your channel name, your moderators). The demo channel name is added automatically. |
| `INTEL_PROTECTED_DOMAINS` | blank | Your own websites, comma separated. Links that look almost like them are flagged as look-alikes, and links to them are never treated as risky. |
| `INTEL_INTENT_MIN_TOKENS` **SECRET** | `4` | Messages shorter than this many words are not scored by the statistical detectors. |
| `INTEL_WAVE_ACCOUNTS` | `6` | A raid wave starts when this many brand-new accounts speak within the window below. |
| `INTEL_WAVE_WINDOW_SECONDS` | `30` | Window for counting new accounts toward a raid wave. |
| `INTEL_WAVE_DURATION_SECONDS` | `180` | How long a raid wave stays active once detected. |
| `INTEL_WAVE_WEIGHT` | `15` | Score added to suspicious messages from new accounts during a raid wave. |
| `INTEL_LEARNING_MODE` | `suggest` | What the bot does with what it learns from your approve and reject decisions: off, suggest (you decide) or auto (applies the confident ones, every change is logged and reversible). |
| `INTEL_LEARN_MIN_LESSONS` | `10` | The learned model only influences scoring once it has at least this many lessons (spam and fine together). Stops a few early decisions from swinging the bot. |
| `INTEL_LEARN_FROM_DEMO` | `False` | Also learn from simulated (demo) decisions. Off by default so test data never teaches the bot. |
| `INTEL_LEARN_TRUSTED_HAM` | `True` | Learn that ordinary messages from regulars, members and mods are fine (a few per minute at most). |
| `INTEL_EXAMPLE_CAP` | `5000` | Most lessons kept. When there are more, the oldest are forgotten first. |
| `INTEL_LESSON_RETENTION_DAYS` | `0` | Delete lessons older than this many days. 0 keeps them until you forget them or the limit above is reached. |
| `INTEL_FEEDS_ENABLED` | `True` | Refresh the live data feeds (public phishing and malware domain lists) in the background. |
| `INTEL_FEED_INTERVAL_HOURS` | `24` | Minimum hours between refreshes of the same feed. Never lower than 1. |
| `INTEL_FEED_MAX_ENTRIES` | `15000` | Most domains kept from any one feed. |
| `INTEL_FEED_MAX_BYTES` | `6000000` | Largest download accepted from a feed. |
| `INTEL_FEED_STARTUP_DELAY_SECONDS` | `120` | Wait this long after boot before the first feed refresh, so start-up stays fast. |

## Commands

| Variable | Default | What it does |
|---|---|---|
| `COMMAND_PREFIX` | `!` | Character(s) that start a chat command. |
| `COMMAND_DEFAULT_COOLDOWN` | `5` | Default global cooldown (seconds) for new commands. |
| `COMMAND_USER_COOLDOWN` | `10` | Default per-user cooldown (seconds) for new commands. |
| `COMMAND_MAX_RESPONSE_LENGTH` | `200` | Replies are trimmed to this many characters. |
| `COMMAND_MAX_RENDER_DEPTH` | `6` | Maximum nesting of $(variables). |
| `COMMAND_MAX_EXPANSIONS` | `25` | Maximum $(variables) evaluated per reply. |
| `TRIGGERS_ENABLED` | `True` | Run auto-replies: the bot answers when a viewer sends a configured phrase or word. |
| `TRIGGER_DEFAULT_COOLDOWN` | `30` | Default global cooldown (seconds) for new auto-replies. |
| `TRIGGER_USER_COOLDOWN` | `60` | Default per-user cooldown (seconds) for new auto-replies. |
| `COMMAND_SEED_DEFAULTS` | `True` | Create starter commands, timers, quotes and banned phrases on first boot. |
| `URLFETCH_ENABLED` | `True` | Allow $(urlfetch ...) in commands (owner-created commands only). |
| `URLFETCH_TIMEOUT_SECONDS` | `4.0` | Timeout for $(urlfetch ...). |
| `URLFETCH_MAX_BYTES` | `2000` | Maximum bytes read by $(urlfetch ...). |
| `URLFETCH_ALLOWED_HOSTS` | blank (blank means any public host is allowed (private networks are always blocked)) | If set, urlfetch may only call these hosts (comma separated). |
| `URLFETCH_BLOCK_PRIVATE` | `True` | Block urlfetch calls to private/internal addresses (SSRF protection). |

## Scheduler

| Variable | Default | What it does |
|---|---|---|
| `TIMERS_ENABLED` | `True` | Run chat timers. |
| `REMINDERS_ENABLED` | `True` | Run reminders. |
| `SCHEDULER_TICK_SECONDS` | `3` | How often timers and reminders are checked. |

## Demo

| Variable | Default | What it does |
|---|---|---|
| `DEMO_ENABLED` | `True` | Allow demo mode. |
| `DEMO_AUTOSTART` | `True` | Start the ambient demo chat when the bot is in demo mode. |
| `DEMO_MESSAGES_PER_MINUTE` | `30` | Ambient demo chat speed. |
| `DEMO_CHANNEL_NAME` | `SavahDemo` | Channel name shown in demo mode. |
| `DEMO_CHATTER_COUNT` | `20` | Number of simulated viewers. |
| `DEMO_SPAM_PROBABILITY` | `0.06` | Chance (0-1) that an ambient demo message is spam. |
| `DEMO_SEED` | `0` | Random seed (0 = different every run). |

## Redis (optional)

| Variable | Default | What it does |
|---|---|---|
| `REDIS_URL` | `edit-me` | Redis address (redis:// or rediss://). Blank = everything stays in memory. Turns on: moderation memory that survives restarts, shared login lockouts, live events across instances, one leader instance, a short dashboard cache, and restart-proof cooldowns. |
| `REDIS_PREFIX` | `savahbot` | Prefix for every key this bot writes, so one Redis can be shared with other apps. |
| `REDIS_TIMEOUT_SECONDS` | `3` | How long to wait for Redis before carrying on in memory. |
| `REDIS_SNAPSHOT_SECONDS` | `10` | How often the moderation memory is saved to Redis (0 = never). It is also saved when the bot shuts down. |
| `REDIS_LEADER_TTL_SECONDS` | `30` | If the leader instance disappears, another one takes over after about this many seconds. |
| `SHARED_CACHE_SECONDS` | `15` | With Redis on, how long heavy dashboard queries (such as Insights) are reused. 0 = no caching. |

## Reserved (future features, unused today)

| Variable | Default | What it does |
|---|---|---|
| `TWITCH_CLIENT_ID` | `edit-me` | Reserved: Twitch application client id. |
| `TWITCH_CLIENT_SECRET` **SECRET** | `edit-me` | Reserved: Twitch application client secret. |
| `TWITCH_CHANNEL` | `edit-me` | Reserved: Twitch channel name. |
| `TWITCH_BOT_TOKEN` **SECRET** | `edit-me` | Reserved: Twitch chat OAuth token. |
| `KICK_CLIENT_ID` | `edit-me` | Reserved: Kick application client id. |
| `KICK_CLIENT_SECRET` **SECRET** | `edit-me` | Reserved: Kick application client secret. |
| `DISCORD_BOT_TOKEN` **SECRET** | `edit-me` | Reserved: Discord bot token. |
| `DISCORD_WEBHOOK_URL` **SECRET** | `edit-me` | Reserved: Discord webhook for alerts. |
| `SENTRY_DSN` **SECRET** | `edit-me` | Reserved: Sentry error reporting DSN. |
| `SMTP_HOST` | `edit-me` | Reserved: SMTP host for email alerts. |
| `SMTP_PORT` | `587` | Reserved: SMTP port. |
| `SMTP_USER` | `edit-me` | Reserved: SMTP username. |
| `SMTP_PASSWORD` **SECRET** | `edit-me` | Reserved: SMTP password. |
| `SMTP_FROM` | `edit-me` | Reserved: sender address for email alerts. |
| `OUTBOUND_WEBHOOK_URL` **SECRET** | `edit-me` | Reserved: POST moderation events to this URL. |
| `OUTBOUND_WEBHOOK_SECRET` **SECRET** | `edit-me` | Reserved: HMAC secret for outbound webhooks. |
| `AI_ENABLED` | `False` | Reserved: AI features (off by design for now). |
| `AI_PROVIDER` | blank (AI is not used in this version) | Reserved: AI provider name. |
| `AI_API_KEY` **SECRET** | `edit-me` | Reserved: AI provider API key. |
| `AI_MODEL` | blank (AI is not used in this version) | Reserved: AI model name. |
