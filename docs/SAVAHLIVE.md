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

## What the overlay shows (1.6.0)
The floating UI has two forms, both themed by the same colours and drawn with SVG-derived icons that take the theme's colours:

- **The panel** (the full window). A top bar with an **expand** button (cycles small, medium, large), a **three-dot handle** and a **✕**. Drag the top bar or the numbers row to move it. Drag a **bottom corner** to resize: the whole panel scales together, like a phone's own floating windows, with an outline while you do. Tap the three dots for the **tray**: panel opacity (a line you slide), tab fade (another line), theme, lock, text size and stop. It shows a live dot, viewers, likes and the chat, with a soft fade instead of half-cut lines.
- **The tab** (what ✕ gives you). A small box on any screen edge (left, right, top or bottom) and anywhere along it: drag it and let go, it snaps to the nearest edge. After a few seconds untouched it slides almost completely out of sight and fades to the opacity you chose. When new chat arrives it slides out with a card showing the latest line or two for the pop-out time, then tucks away again. Tap it to open the panel. Dragging the panel more than a third off any edge also tucks it into that edge.
- **Themes.** Midnight, Light, Savah red, Ocean, Forest, Violet, or Custom (a colour line and a light/dark line). Text, icons and cards pick colours that stay readable on whatever you choose. Panel opacity only affects the background: text and icons stay fully visible, with a soft shadow when it gets very see-through.
- **Lock** makes touches pass through the panel to the game; unlock from the notification (Lock touch / Unlock touch). **Stop** in the tray asks twice.
- Positions, size, theme, opacity and the tab's edge are remembered on each phone and survive rotating the phone. Chat from banned or deleted people disappears from the panel. Raids show "+37 more messages" instead of flooding the phone. Nothing is shown as live when it is not: while the connection is down the numbers become dashes after 30 seconds.

## Manage > SavahLive (settings that sync to every phone)
A status hero (phones paired, connected now, whether SavahBot is on air), phone cards (rename, change expiry, remove with a second tap), a **live preview** of how the panel reads with your settings, and these settings: hide bot messages, hide flagged messages, members and moderators only, track viewers and likes (the existing `YT_LIVE_ENABLED`; without it the overlay shows chat only), chat lines kept (10 to 100), text size (11 to 22), **pop-out time** (2 to 15 s) and **tab hides after** (0 to 30 s, 0 = never). Under Connection: the on/off switch, phones allowed, phones connected at once (separate from the dashboard's `SSE_MAX_CLIENTS`), key renewal, optional unpair-when-idle, an optional **app download link** (`SAVAHLIVE_DOWNLOAD_URL`, shown as a Download button) and Remove all phones. Changes are saved together with the Save bar. All are `SAVAHLIVE_*` settings, listed in `docs/ENVIRONMENT.md`.

## The feed (for developers)
`GET /api/live/feed?since=<last chat id>&app=<version>` with `Authorization: Bearer sld_...`. Server-Sent Events:

| Event | Data |
|---|---|
| `hello` | `v` (protocol, now 1), `state`, `stats`, `settings`, `chat` (recent lines newer than `since`), `rotate` (true = swap the key) |
| `stats` | `viewers`, `likes`, `likes_hidden`, `peak`, `updated`, `note`, `enabled` |
| `state` | `mode` (live/demo), `live`, `title` |
| `chat` | `lines` (`id`, `uid`, `name`, `text`, `level`, `ts`), `skipped` |
| `purge` | `uids`, `ids` to remove from the window |
| `settings` | the overlay settings: `chat_lines`, `peek_seconds`, `font_size`, `hide_seconds`, `hide_bots`, `hide_flagged`, `only_special` |
| `unpaired` | `code`: `revoked`, `expired`, `idle` (forget the pairing) or `disabled`, `lockdown`, `replaced` (keep it and wait) |

A comment line `: ping` arrives every 15 seconds. One connection per phone (a reconnect replaces the old one). Errors before the stream starts are JSON with a `code`: 401 `unpaired/revoked/expired/idle` (forget), 403 `disabled/lockdown` and 429 `busy` (retry later). Other routes: `POST /api/live/pair`, `POST /api/live/rotate`, `GET /api/live/pair/open` (the QR page); dashboard routes under `/api/savahlive` (see `docs/API.md`).

Battery and data: the phone closes the stream when the screen goes off and reopens it when the screen is on; stats are sent only when they change; chat is batched and trimmed to author, text and badge.

## Honest limits
- In-app QR scanning is not built (it needs a decoder library or Google Play services, against the "no dependencies" rule). The phone's own camera opens the pairing page instead.
- The app has been built and run on a real phone (debug build, Windows). Some design polish is still planned, and other phone brands (Xiaomi, Oppo, Samsung battery handling) have not been tried yet. Test the overlay on your own phone, especially drag, docking and the Keystore.
- Some phone makers stop background apps aggressively; the app offers a battery-settings shortcut.
- The backend tests in `backend/tests/test_savahlive.py` exercise pairing, keys, expiry, revoking, the feed, batching and cut-offs. Its HTTP test needs the usual test dependencies.
