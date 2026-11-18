# SavahLive (1.5.0)

SavahLive is a small native Android app that floats your livestream's **viewers, likes and chat** above any other app (PUBG Mobile, for example).
**SavahBot does the work, SavahLive displays the results.** The phone never talks to YouTube, never moderates and has no dashboard: it only shows what this backend already produced.

| Part | What it does | Where |
|---|---|---|
| SavahBot web app | The place you manage everything. **Manage > SavahLive** pairs phones and tunes the overlay. | `frontend/src/pages/savahlive.ts` |
| SavahBot backend | Pairing codes, device keys and the overlay feed. New tables and routes only; nothing existing changed. | `backend/app/savahlive.py`, `backend/app/api/savahlive_routes.py` |
| SavahLive app | The floating window and one connection. Plain Kotlin, no third-party libraries. | `android/` (build steps in `android/README.md`) |

## Pairing (once)
1. Manage > SavahLive > **Pair a phone**. Choose how long the phone stays paired: *Until I remove it* (default), 30 days, 7 days or 24 hours.
2. SavahBot shows a QR code and an 8-character code. The code works **once** and runs out in **5 minutes**.
3. On the phone: scan the QR code with the camera (it opens a page with an **Open SavahLive** button), or tap **Open in SavahLive** if you are on that phone, or paste the link / type the code in the app.
4. The phone gets its **own device key**. It is stored encrypted with a key held in the Android Keystore. Only a hash of it is stored on the server.

After that the phone stays paired. Opening the app, restarting the phone or updating the app never asks you to pair again. The phone only forgets its pairing when SavahBot clearly says so: you removed it, an expiry **you** chose passed, or (if you turned it on) it sat unused. A weak signal or an unreachable server never unpairs a phone.

Keys are renewed quietly in the background (every 30 days by default, Manage > SavahLive > Connection). The old key keeps working for a day after a swap, so a lost reply never locks a phone out.

### Removing a phone
Manage > SavahLive > the bin icon (tap twice), or **Remove all phones**. A connected phone is cut off within a moment and shows "unpaired". You can also rename a phone or change its expiry (an expired phone comes back by choosing a new time; no re-pairing). Changing your dashboard password has a tickbox **Also unpair all SavahLive phones** (off by default). **Lockdown** pauses every phone (they keep their pairing and reconnect when lockdown ends).

Security notes: a device key opens exactly one door, `GET /api/live/feed` (plus renewing itself). The dashboard refuses it, and the feed refuses a dashboard token. Pairing attempts are rate-limited per address and across all addresses. SavahBot sends a Telegram alert when a phone is paired, because a paired phone can read your live chat. Creating a code does not ask for your password again; the alert and the phone list are the safeguard.

## What the overlay shows
- **Viewers, likes, a LIVE dot** (red when on air, grey when not, amber while reconnecting), and a **Demo mode** / **Waiting for your stream** note. Likes the creator hides show a dash. Nothing is shown as live when it is not: while the connection is down the numbers turn into dashes after 30 seconds.
- **Compact pill.** New chat slides out under it for a few seconds (*peek time*), then tucks away. Drag it anywhere; drop it near the left, right or top edge and it docks flush there.
- **Tap the pill** for the bigger chat window; the minus button returns to the pill. The half-circle button, or a **long-press on the pill**, cycles **Solid, Glass, Ghost** (no background, text only).
- **X** closes the overlay completely and stops everything running. The notification has **Stop** and **Lock touch** (touches pass through to the game until you unlock).
- Chat from banned or deleted people disappears from the window. Raids show "+37 more messages" instead of flooding the phone.

## Manage > SavahLive (settings that sync to every phone)
Track viewers and likes (this is the existing "Live viewers and likes" setting, `YT_LIVE_ENABLED`; without it the overlay shows chat only), hide bot messages, hide flagged messages, members and moderators only, chat lines kept (10 to 100), peek time (2 to 15 s), text size (11 to 22), the on/off switch, phones allowed, phones connected at once (separate from the dashboard's `SSE_MAX_CLIENTS`), key renewal days and optional unpair-after-idle days. All are `SAVAHLIVE_*` settings, listed in `docs/ENVIRONMENT.md`.

## The feed (for developers)
`GET /api/live/feed?since=<last chat id>&app=<version>` with `Authorization: Bearer sld_...`. Server-Sent Events:

| Event | Data |
|---|---|
| `hello` | `v` (protocol, now 1), `state`, `stats`, `settings`, `chat` (recent lines newer than `since`), `rotate` (true = swap the key) |
| `stats` | `viewers`, `likes`, `likes_hidden`, `peak`, `updated`, `note`, `enabled` |
| `state` | `mode` (live/demo), `live`, `title` |
| `chat` | `lines` (`id`, `uid`, `name`, `text`, `level`, `ts`), `skipped` |
| `purge` | `uids`, `ids` to remove from the window |
| `settings` | the overlay settings above |
| `unpaired` | `code`: `revoked`, `expired`, `idle` (forget the pairing) or `disabled`, `lockdown`, `replaced` (keep it and wait) |

A comment line `: ping` arrives every 15 seconds. One connection per phone (a reconnect replaces the old one). Errors before the stream starts are JSON with a `code`: 401 `unpaired/revoked/expired/idle` (forget), 403 `disabled/lockdown` and 429 `busy` (retry later). Other routes: `POST /api/live/pair`, `POST /api/live/rotate`, `GET /api/live/pair/open` (the QR page); dashboard routes under `/api/savahlive` (see `docs/API.md`).

Battery and data: the phone closes the stream when the screen goes off and reopens it when the screen is on; stats are sent only when they change; chat is batched and trimmed to author, text and badge.

## Honest limits
- In-app QR scanning is not built (it needs a decoder library or Google Play services, against the "no dependencies" rule). The phone's own camera opens the pairing page instead.
- The Android code was written without being compiled or run here (no Android SDK in the build environment). Expect to fix small things on the first `./gradlew assembleDebug`, and test the overlay on a real phone, especially drag, docking and the Keystore on your phone brand.
- Some phone makers stop background apps aggressively; the app offers a battery-settings shortcut.
- The backend tests in `backend/tests/test_savahlive.py` exercise pairing, keys, expiry, revoking, the feed, batching and cut-offs. Its HTTP test needs the usual test dependencies.
