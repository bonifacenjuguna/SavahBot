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

## What the overlay shows (1.6.1)
The floating UI has two forms inside ONE overlay window, both themed by the same colours and drawn with SVG icons that take the theme's colours (no emojis anywhere):

- **The panel.** A rounded header with a live dot, a **user icon** with the viewer count, a **heart** with the likes, a round **expand / collapse** button and a **tuck** button. Drag the header to move it. Drag **any edge or corner** to resize (no grip lines). Expand opens a bigger window and the icon turns into collapse; tap again for the smaller one. The chat scrolls, and an optional **message box** at the bottom sends to the live chat.
- **The tab.** Tuck puts the panel into a small tab on any screen edge. Drag it anywhere along an edge or to another edge; it snaps to the nearest edge. It never hides by default and never goes below 40% opacity, so you can always find it. New chat slides out a pop-out card with its own size and opacity. Tap the tab to open the panel.
- **Settings live in the app** (SavahLive home screen): panel opacity, text size, theme (Midnight, Light, Savah red, Ocean, Forest, Violet, Custom), tab opacity, **Slide away** (Never, 3, 5, 10, 20 s), pop-out size and opacity, Send messages, and Reset size and position. The window itself keeps only the essentials.
- **Lock** makes touches pass through the panel; unlock from the notification.
- Positions, size, theme and the tab's edge are remembered and survive rotating the phone. Banned or deleted people's chat disappears. Raids show "+37 more messages". While the connection is down the numbers become dashes after 30 seconds.
- **Safety net:** every touch callback is guarded; if anything throws, the overlay falls back to the tab instead of dying.

## Sending chat from the phone (1.6.1)
Off by default. Two switches must both be on: **Let phones send chat** (`SAVAHLIVE_SEND_ENABLED`, Manage > SavahLive > Overlay) and **Can send chat** on that phone's card. Messages go out as SavahBot's own YouTube account, one line, up to 200 characters, at most one per 2 seconds and 12 per minute per phone. The sender sees their line as "You" on their own feed. The audit log stores only the message length. Route: `POST /api/live/send` with the device key, body `{"text": "..."}`; errors `send_off`, `send_denied` (403), `empty` (422), `slow` (429), `send_failed` (502).

## Extras (1.6.2), each with a switch in the SavahLive app
- **Pin a message:** tap a chat line to pin it at the top of the panel; tap the pin to let go.
- **Milestones:** the panel and tab pulse when viewers or likes pass a multiple of the step you chose.
- **Hide or time out from the phone:** hold a line. Needs `SAVAHLIVE_MOD_ENABLED` (Manage > SavahLive > Let phones moderate chat) **and** that phone's own **Can moderate chat** switch. A phone can hide a message or time someone out for 5 minutes (one tap per second, 20 per minute); bans stay on the dashboard. The audit log records the action, not the message. Route: `POST /api/live/mod` with `{"id": <chat line id>, "action": "delete" | "timeout"}`; errors `mod_off`, `mod_denied` (403), `bad_action` (422), `slow` (429), `mod_failed`.
- **Saved looks:** save the current theme, opacities, sizes and positions under a name; apply one from the app or cycle to the next from the notification.
- **Automatic:** start when the app opens; stop N minutes after the stream ends; keep a stream summary on the phone (it is never sent to SavahBot). SavahBot cannot start the overlay by itself, because the phone only connects while the overlay runs (that keeps the battery use low).
- **Connection status** and **update check:** the `hello` event now carries `update` (`version`, `url`: SavahBot's own version and the download link), which the app compares with its own version.

## Manage > SavahLive (settings that sync to every phone)
A status hero (phones paired, connected now, whether SavahBot is on air), phone cards (rename, change expiry, remove with a second tap), a **live preview** of how the panel reads with your settings, and these settings: hide bot messages, hide flagged messages, members and moderators only, track viewers and likes (the existing `YT_LIVE_ENABLED`; without it the overlay shows chat only), chat lines kept (10 to 100), text size (11 to 22), **pop-out time** (2 to 15 s) and **Let phones send chat**. The tab slide-away delay is now set in the phone app. Under Connection: the on/off switch, phones allowed, phones connected at once (separate from the dashboard's `SSE_MAX_CLIENTS`), key renewal, optional unpair-when-idle, an optional **app download link** (`SAVAHLIVE_DOWNLOAD_URL`, shown as a Download button) and Remove all phones. Changes are saved together with the Save bar. All are `SAVAHLIVE_*` settings, listed in `docs/ENVIRONMENT.md`.

## The feed (for developers)
`GET /api/live/feed?since=<last chat id>&app=<version>` with `Authorization: Bearer sld_...`. Server-Sent Events:

| Event | Data |
|---|---|
| `hello` | `v` (protocol, now 1), `update`, `state`, `stats`, `settings`, `chat` (recent lines newer than `since`), `rotate` (true = swap the key) |
| `stats` | `viewers`, `likes`, `likes_hidden`, `peak`, `updated`, `note`, `enabled` |
| `state` | `mode` (live/demo), `live`, `title` |
| `chat` | `lines` (`id`, `uid`, `name`, `text`, `level`, `ts`), `skipped` |
| `purge` | `uids`, `ids` to remove from the window |
| `settings` | the overlay settings: `chat_lines`, `peek_seconds`, `font_size`, `can_send`, `can_mod`, `hide_bots`, `hide_flagged`, `only_special` |
| `unpaired` | `code`: `revoked`, `expired`, `idle` (forget the pairing) or `disabled`, `lockdown`, `replaced` (keep it and wait) |

A comment line `: ping` arrives every 15 seconds. One connection per phone (a reconnect replaces the old one). Errors before the stream starts are JSON with a `code`: 401 `unpaired/revoked/expired/idle` (forget), 403 `disabled/lockdown` and 429 `busy` (retry later). Other routes: `POST /api/live/pair`, `POST /api/live/rotate`, `GET /api/live/pair/open` (the QR page); dashboard routes under `/api/savahlive` (see `docs/API.md`).

Battery and data: the phone closes the stream when the screen goes off and reopens it when the screen is on; stats are sent only when they change; chat is batched and trimmed to author, text and badge.

## Honest limits
- In-app QR scanning is not built (it needs a decoder library or Google Play services, against the "no dependencies" rule). The phone's own camera opens the pairing page instead.
- The app has been built and run on a real phone (debug build, Windows). Some design polish is still planned, and other phone brands (Xiaomi, Oppo, Samsung battery handling) have not been tried yet. Test the overlay on your own phone, especially drag, docking and the Keystore.
- Some phone makers stop background apps aggressively; the app offers a battery-settings shortcut.
- The backend tests in `backend/tests/test_savahlive.py` exercise pairing, keys, expiry, revoking, the feed, batching and cut-offs. Its HTTP test needs the usual test dependencies.
