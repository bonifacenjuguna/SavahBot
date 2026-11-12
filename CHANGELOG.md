# Changelog

## 1.3.7

A tidier top of every page, a usable pinned message, and a calmer stream strip.

### Changed
- **The connection pill at the top shows only the signal icon.** The glowing dot is gone; the colour and the icon still say live, reconnecting or offline.
- **No page title block.** The big icon, page name and description above the cards are gone, so the cards start right under the top bar with a small margin. A page's own buttons (for example "Run a scenario" on the Desk) are still shown. The heading stays for screen readers and for "On this page".
- **No breadcrumb row** ("More › Manage › Insights") under the top bar.
- **The stream strip in the Chat card was redesigned.** The stream name is on top and may use two lines, with a Live / Demo / Off air tag and the time it has run underneath, so nothing is cut off. The glowing dot is gone. The stream-link button is there in every state (it used to be missing in demo and while streaming).
- **On a phone the pause button sits on the same row** as the filter, history and date buttons.

### Fixed
- **Pinned messages had no options.** Each pin is now its own row: tap it (or long-press or right-click) for the same options sheet as any chat line, and the new cross unpins it at once. Every pin is reachable (the bar scrolls instead of hiding all but three), long-pressing a pin no longer starts a text selection, and the pin and selection bars stay above the chat in the expanded view. Pins now remember the details the sheet needs (older pins still open with the basic options).

### Tests
- `frontend/tests/pins.test.ts`. `npm test` runs 33 tests.

## 1.3.6

Clean URLs. The dashboard no longer uses `/#/desk`; every page has a real address.

### Changed
- **Real paths instead of hash routes.** `/desk`, `/moderation`, `/security`, `/settings?tab=appearance` and so on, on the browser History API (a small router in `src/router.ts`, no library). Back, forward, refresh, bookmarks and shared links all work on the real path. The same page opened twice in a row does not add history entries.
- **Old links still work.** `/#/security`, `/#/moderation?tab=rules`, `/#/dashboard` and similar are rewritten to the clean address on load (and if one appears while the app is open), without adding a history entry. Query strings are kept; `token`, `password`, `key` and similar parameters are dropped. A plain `#fragment` is left alone.
- **A real "Page not found" page** for an address that is not a page, instead of silently showing the Desk.
- **Only pages of this app can be navigated to.** Addresses are checked against the list of registered pages, so `//host`, `https://…` and `javascript:` can never be a destination.
- **Vercel:** `vercel.json` rewrites page paths to `index.html`, and leaves `api/`, `assets/` and anything with a file extension alone.
- **YouTube sign-in return** now goes to `/setup?youtube=…` (old `/#/setup?…` links still convert).
- Installed-app shortcuts and push-notification taps open clean paths. The backend still stores notification routes as `#/route` tokens; the dashboard converts them.

### Added
- `npm test` runs the routing rules (`frontend/tests/routes.test.ts`, Node's built-in test runner, no new dependencies).

### Fixed (engineering audit of the clean-URL release)
- **Sign out now closes the session on the server.** It used to forget the token only in the browser, so a copied token kept working until it expired. `POST /api/auth/logout` is now called (best effort) with the token being signed out.
- **A late "401" can no longer sign you out of a newer sign-in**, and a request that carried no token no longer reports "Your session ended". When the session really does end, several requests failing together give one notice and one redraw (the page behind is torn down first, so it no longer re-requests data with no token).
- **The sign-in lockout could be dodged.** The client address was read from the *first* `X-Forwarded-For` value, which a caller can invent for every request. It is now read from the right, counting `TRUSTED_PROXY_HOPS` proxies (default 1, Railway). Set `0` if the server is reached directly with no proxy. The restore-token lockout and the audit log use the same address.
- **Reflected markup in the Google sign-in callback page.** When `FRONTEND_URL` is not set, the small page the callback shows printed the `error` parameter unescaped. It is escaped now and the page carries a locked-down `Content-Security-Policy`.
- **API answers are `Cache-Control: no-store`** (plus `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`) so signed-in data is never kept by a browser or proxy. Routes that choose their own caching (live feed, public voice files) are left alone.
- **Vercel:** added `Content-Security-Policy: frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'` and a `Permissions-Policy` that turns off camera, microphone, payment and USB.
- **Router:** a `#fragment` is kept when an unusual spelling (`/Security#keys`) is rewritten to the canonical path; a back or forward step that only moves the `#fragment` no longer redraws the page; the "Page not found" page no longer lights up the More tab.
- **Test:** `test_a_protected_user_refusal...` expected an older wording of the "stream has ended" message; it now checks the message the code gives.

### Tests
- Frontend: `tests/api.test.ts` (sign-out and 401 handling), `tests/router.test.ts` (history, legacy links, back/forward, fragments), `tests/vercel.test.ts` (rewrite and headers). `npm test` now runs 30 tests.
- Backend: `tests/test_hardening.py` (client address, lockout with forged headers, response headers, server-side sign-out, escaped callback page).

## 1.3.5

One chat per livestream, a stream history, and a dashboard that reconnects by itself.

### Fixed
- **Going live again continued the old chat.** Every livestream is now its own session. A new stream starts on an empty Desk; the Desk never shows lines from an earlier stream. When a stream ends its last lines stay readable until the next one starts.
- **Overlapping dates in saved chat.** The date was printed on every line and ran into the author's name. Saved chat now shows one small heading per day ("Today", "Yesterday", "Mon, Nov 9") and a fixed-width time on each line. The date filter chips wrap instead of being cut off ("Cust...").
- **Refreshing after the backend or the connection dropped.** The live feed now notices a dead connection within 40 seconds (and straight away when the tab wakes up or the network returns), retries every 0.5 to 10 seconds, and tells you why: "Offline" (no internet) or "Reconnecting (n)" (server not answering). Tap the chip to retry now. When it is back, the Desk fetches the lines it missed, other pages redraw themselves, and if the dashboard itself was updated meanwhile it reloads.

### Changed
- **Connection chip redesigned** (same behaviour: tap to retry now). A soft pill with a glowing status dot: green and gently pulsing when live, amber and blinking while reconnecting, red when the device has no internet. On phones it is just the dot and the signal icon so the top bar stays uncrowded; on wider screens it also says "Live" / "Reconnecting (n)" / "Offline". This also removes the grey box 1.3.5 first showed around it on phones.

### Added
- **Streams** (button on the Desk chat): every stream with its date, start and end time, duration, lines, chatters, flagged lines, deletes, timeouts and bans, busiest minute and most active chatters. Open a stream to read its chat, rename it, export it as a .txt file, or delete it.
- **Stream strip** under the chat toolbar: what is on air, for how long, and a Stream link shortcut.
- **Stream link shortcut:** the YouTube row in Bot status is now tappable (and so is the Stream link button). It opens a small sheet to paste the live video link, with the video ID checked as you type, plus the auto-search switch. It saves through the same endpoint as Setup.
- API: `GET /api/streams`, `/api/streams/last`, `/api/streams/{id}`, `/api/streams/{id}/chat`, `/api/streams/{id}/export`, `PATCH` and `DELETE /api/streams/{id}`. `GET /api/chat/recent` returns only the current stream.

### Notes
- A stream that drops and comes back within 10 minutes (same video, or a backend restart) resumes its own session instead of starting a new one. A session with no chat that lasted under 2 minutes is not kept.
- New table `stream_sessions` and column `chat_messages.session_id`, added automatically on start. Chat lines made before 1.3.5 have no stream and do not appear in Streams (they still appear in Dates).
- Chat lines follow the retention setting; each stream's numbers are kept.
- New files: `backend/app/sessions.py`, `backend/app/api/stream_routes.py`, `frontend/src/pages/streams.ts`, `frontend/src/pages/stream-link.ts`, `frontend/src/streams.css`. Tests in `backend/tests/test_sessions.py`.
- Checked here: backend tests, TypeScript, and a browser run against the real backend (history, saved chat, link sheet, backend killed and restarted with no refresh). Not checked: `vite build`, a real YouTube stream.

## 1.3.4

Desktop layout. Phones and tablets are unchanged (checked pixel for pixel against 1.3.3); everything new applies only at 1100px wide and up.

### Changed (desktop only)
- **Cards flow into balanced columns** instead of one long full-width column: Security, Bans, Backup, Notifications, Moderation and Community use two columns (three on screens 1700px and wider). Cards never split across columns, and cards with a table span the full width.
- **Desk:** the chat fills the height of the screen and stays in place while the side cards scroll.
- **Weather:** now and the 7-day forecast sit side by side, the next 24 hours run across the page.
- **Insights:** charts no longer grow to a huge height; "What stood out" and "Busiest hours" sit side by side; the paired cards are the same height.
- **Settings and More tiles:** the status chip sits under the text instead of squeezing it.
- **Card finish:** soft shadows, a tinted header, a coloured top edge on figure cards, a small lift on hover.
- Moderation history keeps its buttons and times on one line in a half-width card (icon-only review button; the Why column is hidden between 1100 and 1299px).

### Notes
- New file `frontend/src/desktop.css`, imported last in `main.ts`. To undo everything, remove that import.
- Checked with screenshots of a build against sample data at 390, 820, 1100, 1440 and 1920px, light and dark. Not checked: Knowledge pages, Setup tabs and live data. `vite build` and `pytest` could not be run here; run them before deploying.

## 1.3.3

Notification switches, pop-up notices you can control, and a much faster chat reader.

### Fixed
- **"Unknown item: categories" on every Notifications switch.** Flipping Notifications, Push to devices, In-app bell or Telegram saved the setting and then failed, because the activity-log line was built from a `categories` key that a plain switch does not send. The switches now save and answer normally (regression test added). The red errors you saw were this bug, one per tap.

### Added
- **Pop-up notices are yours to control** (Settings → Appearance → Pop-up notices, also linked from Notifications): show **All**, **Errors only** or **Off**; put them at the **top** or **bottom**; choose how long they stay (1 to 15 seconds, errors stay twice as long). Saved on the device. "Show a sample" previews it.
- **Swipe a notice left or right to dismiss it** (or tap it). A finger on a notice keeps it from disappearing under you.
- **The same message no longer stacks.** Four identical errors become one with a ×4 counter.
- **Faster mode for the neural voice** (Chat reader settings): tries the phone's graphics chip (WebGPU) and falls back to the processor by itself. Off by default because it downloads a larger file (about 300 MB, one time).

### Performance
- **Chat reader: many more lines per minute.** Before, one line was made into sound, played to the end, and only then the next was started, so the processor sat idle during every playback. Now the next clips are made while the current one plays (two ahead), lines that pile up are joined into one clip (up to 3, same voice), the silent edges of each clip are trimmed, playback speeds up slightly (10 to 20 %) while a queue builds, and up to 12 lines wait instead of 4. If the neural voice fails, every waiting line goes to the built-in voice instead of being lost.
- Stopping or clearing the reader while a line is playing can no longer leave the player waiting forever.

### Notes
- Backend tests and `vite build` could not be run in the build environment (no packages). `py_compile` passes, `tsc --noEmit` passes, and the new reader logic was exercised in Node with a simulated worker and audio. Run `pytest` and `npm run build` before deploying.
- Real speed depends on the phone. If one line is still slower than it is spoken, the neural voice cannot keep up on that device: turn on Faster mode, or use the built-in voice.

## 1.3.2

Fixes from phone testing: tab rows, layers, cut-off cards, the stream-ended bug and a freezing chat reader.

### Fixed
- **Tab rows keep their place.** Settings views, Notification sections, the Manage/System switcher, Knowledge, Commands and the Moderation tabs now open with the current tab in the middle and remember where they were, instead of jumping back to the first tab after every tap. Only the row scrolls, never the page.
- **The dark spot beside the selected tab is gone.** The edge fades were drawn on top of the row; they are now a mask on the row itself and only appear on an edge that still hides tabs.
- **Sheets open above the expanded chat.** Person cards, message actions and "Why it was flagged" used to open behind the expanded chat the second time. Layers now have one order (sheets 90, menus 95, toasts 100, expanded chat 70).
- **Cards cut off at the side.** Blocked phrases, History and other cards were wider than the screen because a single-column grid (`1fr`) would not shrink below its content. Grids now use `minmax(0, 1fr)`, long phrases wrap, and the form controls stay inside the card.
- **Cards no longer touch the tab row** in Notifications and the other Manage/System pages.
- **Figures are cards.** "43 unread / 2 push devices / active" and the other figure rows are small cards with a status edge instead of plain text.
- **Read chat has its own place.** The button moved into the chat header (icon only on a phone); loading and error messages show on a thin line under the toolbar and take no room when empty. It no longer sits on top of chat lines.
- **Stream ended, bot still "On air".** The bot now notices the end of a stream from YouTube's own offline marker, from a send or delete that YouTube refuses with "chat ended", and from a quiet chat check (one cheap `videos.list` call, at most every 90 seconds, only while the chat is quiet). The Desk then returns to Standby, and a send attempt says plainly that the stream has ended.

- **Read chat read only the test sentence.** Real lines were judged "too old" by YouTube's publish time (behind by the polling gap and any clock difference), so they were skipped. Age is now counted from when the dashboard received the line, and lines loaded from history are never read.
- **Expanded chat:** the Close button is icon only.

### Performance
- **The neural voice runs in a Web Worker.** Downloading and running Kokoro no longer blocks the page, so scrolling, taps and the live chat stay smooth while it loads and speaks. The worker reports download progress, and the reader keeps only the newest 4 lines waiting for the neural voice so it never falls behind.
- The reader control redraws at most once per frame, releases its listener when you leave the Desk, and stops cleanly if Read chat is switched off while a line is being made.

### Not changed
- Existing backend tests could not be run in the build environment (no Python packages available). `py_compile` passes for the changed files, and the dashboard typechecks with `tsc --noEmit`. Run `pytest` and `npm run build` once before deploying.

## 1.3.1

Finishes the items 1.3.0 left partial.

- **Chat actions:** lift a ban or timeout from the person card, "Always allow links to this site", a fuller "Why it was flagged" sheet, single-message deletes are logged.
- **Activity log:** retention days and "notify me about sensitive entries" are controls on the page; notification-setting changes are now logged.
- **Insights:** click a past stream to see its viewers and likes graph.
- **Long lists:** timers, auto-replies, commands and regulars show the first few with "Show all", and Recent deliveries too.
- **Notifications:** quick presets (Essentials only, No push, Everything on) and mute for 15 min / 1 h / 8 h / until morning.
- **Demo:** "Add sample history" fills chat, a flagged message and bans in different states; past streams and their graphs have labelled sample data; "Clear demo data" now also removes demo bans.

Not changed: the stray Chrome notification could not be reproduced here. The service worker is unchanged except its version; see REPORT.md.

## 1.3.0

A bug-fix and polish release with several new features. Guides are in `docs/`.

### Fixes
- Appearance and other setting rows no longer cut off on phones; cards no longer touch; the notification panel filter bar no longer overlaps.
- One refined SVG status icon set replaces emoji-looking marks everywhere.
- Notifications: the status-bar white square is fixed (proper monochrome badge); tapping a notification opens what it was for (a test notification opens inside Notifications showing it); foreground push is no longer suppressed (`if (watching && p.category !== "test.test") return;`, with a regression test); a payload-less push now shows our own notification instead of the browser's generic one; new count-badge design; "Stop these" in the notification detail sheet.
- Sheets can be closed by dragging the grip, not only the X.
- `/tgmode` switch from inside polling no longer leaves the webhook unregistered or the bot silent.
- Signing in always lands on the Desk. Tab strips keep their position and centre the active tab.
- Database start-up on PostgreSQL: tables, then missing columns, then indexes (fixes `column "dedupe_key" does not exist` on older databases).

### New
- **Navigation:** "On this page" jump chip, "Show all" sheets for long lists, back-to-top, progress line, breadcrumbs, quick switcher with recents and actions, tab strips with fades and an all-pages grid.
- **YouTube source:** auto-search switch, paste a stream link or ID, calm quota notice, falls back to the configured source after a stream ends.
- **Telegram control centre:** on/off, link/unlink, rotate secret, shutdown, activity log.
- **Custom variables:** `$(TikTok)` in commands, timers, auto replies and messages you send as the bot; types text/link/number; Settings > Variables; insert chips; included in backups.
- **Activity log** (Settings): sorted by importance and area, before/after for ordinary settings, never secrets or message text, search, dates, export, retention, optional notification for sensitive entries.
- **Chat actions:** hold (or tap / double tap, per device) a chat line for copy, reply as the bot, dashboard-only pins, person card, notes, teach spam/fine, block phrase, delete / timeout presets / ban with quota cost and 10-second Undo, multi-select.
- **Chat reader:** built-in browser voices and a neural voice (Kokoro, free, downloads once) with automatic fallback; who-to-read rules, per-person always/never/own voice, name first, skip links and emoji, shorten, collapse repeats, drop backlog, pronunciation dictionary; voice-pack upload card and self-hosted link.
- **Stream alerts:** members, Super Chat, Super Sticker and membership gifts recognised in chat; best-effort new-subscriber detection and subscriber-count milestones; settings for intervals and thank-you messages.
- **Live stats:** likes, viewers, likes per minute, peak and milestone alerts on the Desk; `$(likes)`, `$(viewers)`, `$(subs)`; per-stream history in Insights.
- **Moderation levels:** Basic, Balanced, Strict presets for the auto thresholds.
- **Demo mode:** zoomed charts show labelled sample history instead of zeros; live card shows sample stats.
- Long lists (Telegram log, Security activity, Recent deliveries) end in a "Show all" sheet.

### Known limits
Not testable in the build environment: real FCM/browser push, Telegram, PostgreSQL, YouTube (subscriber list, likes, member events), voices (sound), and the neural model download. Subscriber detection is best effort (public subscribers only). Voice packs need a Railway Volume to survive redeploys. Service worker version 1.3.0.

## 1.2.0

One coordinated release. Guides for everything are in `docs/` (start at `docs/README.md`).

### Notification Centre (Firebase Cloud Messaging)
- Push to phones and computers through Firebase, an in-app bell and history that now live on the server, and Telegram, all through one pipeline. ntfy is gone.
- 17 notification kinds, each raised by real code. Per category: on/off, channels, priority. Duplicate folding, quiet hours (hold-and-summarise or silent), pause, hourly cap, critical alerts that break through, retries with growing delays, dead tokens cleaned up automatically, leader-only sending.
- Seven-tab Notifications page. Service worker handles push and opens the right page on tap. Device tokens are encrypted and never shown. Guide with a Firebase console walkthrough: `docs/NOTIFICATIONS.md`; platform limits: `docs/PWA_AND_PUSH_PLATFORMS.md`.

### Weather (Open-Meteo)
- Provider interface with Open-Meteo, normalization, retries and backoff, memory + Redis cache, stale data clearly labelled, one provider call for simultaneous requests.
- Places (search, coordinates, device-location button only on press), units, dashboard, settings page, alert rules through the Notification Centre, Telegram `/weather /forecast /hourly /locations`. No API key; attribution shown. See `docs/WEATHER.md`.

### Security & Access Centre
- Password, passkeys and authenticator app: any two once two are set up. Recovery codes, sessions and devices, sign-in activity, audit log, step-up checks, lockdown. See `docs/SECURITY.md`. **Everyone is signed out once on upgrade.**

### Settings & Control Centre
- Settings is now a hub: verified status cards, a "needs a look" list, search, Appearance (theme, accent, density, text size, motion), Privacy & data, Device & app, Developer (health, config check). See `docs/SETTINGS.md`.

### Backup & recovery
- Encrypted `.svbak` export and import with a key shown once, dry-run, merge or replace, safety snapshot with undo, first-run restore. `docs/BACKUP_AND_RECOVERY.md`.

### Also
- Knowledge: transplanted tools, packs and learning 2.0 (`docs/KNOWLEDGE.md`). Ban management with unban and limits (`docs/BANS.md`). Interactive charts and long history (`docs/HISTORY.md`).
- GIPHY removed. Docs split into per-subsystem guides; `ENVIRONMENT.md` and `API.md` are generated from the code and checked by tests. README is short.
- Removed variables: `NTFY_URL`, `NTFY_TOPIC`, `WEATHER_API_KEY`, `GIPHY_API_KEY`. New: `FIREBASE_*`, `NOTIFY_*`, `WEATHER_*` (see ENVIRONMENT.md).
- Service worker version 1.2.0.

## 1.1.9

### Install SavahBot as an app (PWA)
The dashboard can now be installed on a phone, tablet or computer and opens in its own window, with no browser bars.

- **A calm install card** appears at the bottom of the signed-in dashboard, only when installing makes sense. It uses the dashboard's own colours, shows the app icon, says what you get, and has **Install** and **Not now**. It never shows on the sign-in screen, while a dialog is open, or while the tab is in the background, and it waits a few seconds after the dashboard opens.
- **The browser's own install prompt is never shown automatically.** It is held until you press Install.
- **Not now is remembered, but never final.** The card returns after 3 days, then 14, then 60. An **Install app** button stays in the sidebar, on the **More** page and in the command palette (Ctrl K), so you can install whenever you like. It disappears once the app is installed.
- **iPhone and iPad get their own steps** (Share, then Add to Home Screen), written for Safari, for other iOS browsers (iOS 16.4 and later), and for apps with a built in browser, where it asks you to open the page in Safari. Android steps are never shown on iOS. Safari 17 on a Mac gets Add to Dock.
- **Browsers without an install prompt** (for example Firefox on Android) get menu steps. Browsers that cannot install web apps see nothing.
- **Detection:** `beforeinstallprompt`, `appinstalled`, `display-mode` (standalone, minimal-ui, window-controls-overlay), iOS `navigator.standalone`, and Android app launches. Changes made in another tab are followed.
- **Home screen shortcuts** (long press the app icon): Desk, Moderation queue, Commands. The manifest also gained a stable `id`, `lang` and `categories`. Existing name, colours and icons are unchanged.
- **Offline page.** Opening the installed app with no connection shows a branded "You are offline" page instead of a browser error.

### Safety
- The new service worker (`public/sw.js`) caches **one static page** (`/offline.html`) and nothing else. It only handles page loads, tries the network first, and never touches POST requests, other origins (your backend, fonts), `/api/` paths, requests with an Authorization header, or addresses with a token. Sign-in, the API and the live feed behave exactly as before.
- The only thing stored by the install card is the dismissal count and time (`savahbot.pwa` in local storage).

### Code
- New `frontend/src/pwa.ts` (`initPWA()`, called once from `main.ts`) and `pwa.css`. The sidebar button, More tile and palette action read the same state. Two small icons (`share`, `plusSquare`) were added.
- `vercel.json` adds headers for `sw.js` (never cached), the manifest (correct type) and the offline page.

## 1.1.8

### Optional Redis
Set `REDIS_URL` and the bot uses Redis for six things; leave it empty and nothing changes. Guide: `docs/REDIS.md`.

1. **Moderation memory survives restarts.** Message rates, repeats, near-identical raids, strikes and posting rhythm are saved every 10 seconds and on shutdown, and restored on start.
2. **Login lockout is shared and restart-proof** (dashboard and Telegram `/claim`).
3. **Live dashboard events across instances** through Redis pub/sub.
4. **One leader instance** polls YouTube, runs timers and reminders and polls Telegram; another takes over within about 30 seconds if it stops.
5. **Short shared cache** for heavy dashboard queries (Insights).
6. **Restart-proof cooldowns and duplicate protection**: command and auto-reply cooldowns, "just punished" markers, and each live message id is handled once.

- Redis is never required. If it is missing or unreachable, the bot carries on in memory and reconnects by itself.
- The Redis client is built in (no new package). `REDIS_URL` is no longer "reserved"; new optional variables: `REDIS_PREFIX`, `REDIS_TIMEOUT_SECONDS`, `REDIS_SNAPSHOT_SECONDS`, `REDIS_LEADER_TTL_SECONDS`, `SHARED_CACHE_SECONDS`. `.env.example` regenerated.
- `/api/status` and `/api/health` report the Redis state. The Desk "Status" panel shows a Redis row right under Database (Off, Connecting, Unreachable, Leader or Standby, and when the moderation memory was last saved).
- 16 new tests (`tests/test_redis.py`) run against a small stand-in Redis server, so the real wire client is exercised.

## 1.1.7

### Bottom navigation (phone)
- The grey highlight behind the selected tab is gone, along with the tap flash.
- A white bar now sits on the top edge of the footer, above the active tab.
- Tab icons pop (zoom out, then settle) when you select them, and shrink slightly while pressed. Reduced-motion settings turn this off.

### Sign-in page, redesigned
- Matches the dashboard theme (colours, accent, light and dark), with a branded card, a show/hide password button and a clear loading state.
- No more setup hints: the page no longer names the `OWNER_PASSWORD` variable or the Railway logs, and the backend address is no longer printed. It is asked for only when none is set, or under "Connection settings" (leave it empty to keep the current connection).
- Wrong-password and unreachable-server messages are now plain and friendly.
- Phone: full-width card. Tablet: centred card. Desktop: brand panel beside the card. Short landscape phones are handled too.

## 1.1.6

### Intelligence without AI services
The bot can now recognise spam and scams well beyond a phrase list, using plain algorithms and data files that run on your own server. No AI model, no outside API. Full guide: `docs/KNOWLEDGE.md`.

- **Knowledge, split by category.** `backend/app/intel/knowledge/packs/` holds one JSON file per category: promo and sub-for-sub, crypto fraud, fake prizes, account phishing, contact lures, adult-link bots, Kenya and East Africa scams (English, Swahili and Sheng), scam message shapes, risky links, disguise maps, official-sounding names, and training examples in English and Swahili/Sheng. Each pack has a version, date and sources (researched November 2026 from current reports on live-chat spam, crypto-doubling streams, abused link endings and M-Pesa fraud). An empty **abusive language** pack ships for you to fill; nothing is shipped there.
- **Nine detectors**, each Off, Shadow or Active, with its own sensitivity and maximum points: Knowledge packs (disguise-proof exact matching), Fuzzy matching (trigram index and edit distance, plus a consonant skeleton for dropped vowels), Learning filter (Naive Bayes over words, pairs and fragments, in English and Swahili), Link intelligence (shorteners, abused endings, brand lookalikes, brand-in-subdomain, the @ trick, raw IPs), Viewer reputation (trust discount, repeat offenders, blocked text returning on a new account), Scam patterns (shapes combined as independent hints), Bot shape (keyboard-mashing, template spam, channel waves), Evasion tricks, Lookalike names.
- **Safe by design.** Every new detector starts in **Shadow**: it runs and is logged but never changes what happens in chat. Agreeing detectors count for less each time, and intelligence alone can never reach the timeout score, so it cannot time out or ban anyone by itself. A failing detector is skipped, never fatal. With everything in shadow, verdicts are identical to 1.1.5 (tested).
- **It learns from you.** Approve teaches "spam", Reject teaches "fine", "Teach the bot" gives a deliberate lesson, and ordinary messages from trusted chatters teach "fine" slowly. Every lesson is stored and can be forgotten; accuracy is measured honestly (each message is guessed before it is learned). Demo decisions never teach it unless you allow it.

### Dashboard: Settings, Knowledge
- **Overview**: the state of the bot's mind and the one most useful next step.
- **Packs**: browse and search every pack, switch packs on or off, add your own entries, mute entries you do not want, see where each pack's knowledge came from.
- **Detectors**: mode, sensitivity and most points for each, and **Try it here**, which shows every detector's opinion on any message, even ones that are Off.
- **Learning**: lessons, accuracy over time, the words it distrusts and trusts, teach by pasting a message, forget one lesson or all of them, and what it may learn from.
- **Shadow report**: what detectors would have done, how often your own decisions agreed, and a one-tap "Switch to Active" when one is mostly right.
- **Moderation, History**: "Why and teach" explains why a message was flagged, shows what each detector thinks, and lets you teach the bot.
- Command palette: Open Knowledge, Shadow report, Teach the bot, Knowledge packs.

### API
New under `/api/intel/`: `overview`, `packs`, `packs/{id}/enable`, `packs/{id}/entries` (GET, POST, DELETE), `packs/{id}/mute`, `test`, `learning`, `examples`, `examples/{id}` (DELETE), `learning/reset`, `teach`, `shadow`. Verdicts gain a `shadow` list. New tables: `intel_examples`, `intel_shadow`, `intel_packs`, `intel_user`.

### Settings
New `INTEL_*` settings (editable in the dashboard). `.env.example` regenerated.

### Technical
- New `app/intel/` package: `text.py`, `knowledge/`, `detectors/` (one file each), `service.py`, `store.py`. About 0.7 ms per message with every detector on.
- 25 new tests (`tests/test_intel.py`, plus two API tests). Version bumped to 1.1.6.

## 1.1.5

### Quota
- **Resets on Pacific Time, shown in your time.** YouTube resets the daily quota at midnight Pacific, which moves with daylight saving. The backend now sends the exact reset moment (`quota.resets_at`) and the Desk shows it on your own clock, e.g. "11:00 AM Nairobi time (in 5h 12m)". It is 11:00 in Nairobi while the US is on standard time and 10:00 in summer. The count drops to 0 by itself: the dashboard refreshes the moment the reset passes.
- **"Fix count" removed** from Bot status. (`POST /api/youtube/quota` still exists for scripts.) The side-bar quota meter now says when it resets.

### Moderation tools, rebuilt
- **Try a message** is now a test lab. It scores as you type, shows a verdict (Allowed, Flagged, Would be deleted, timed out or banned), a score ladder with your flag, delete, timeout and ban limits, and each check that fired in plain words. It says what would happen in your current moderation mode, lets you pick who sent it (viewer, member, regular, mod), has example messages, and offers **Block this phrase** when a message slips through.
- **Blocked phrases**: one clear add box, phrase or pattern, and what a match should do (Standard, Flag, Delete, Time out). **Add several at once**, two **starter packs** of common spam lines, filters (All, On, Off, Patterns), search, a switch per phrase, **Undo** after removing, and **Copy every phrase**.
- API: `GET /api/blacklist` and `POST /api/moderation/test` now include `thresholds` (and `mode` on the test).

### Manage
- **Notebook**: a real composer (auto-growing, tag suggestions, Ctrl+Enter), templates (Stream plan, Ideas, Shout-outs), **checklists** (start a line with `[ ]`; tick boxes save instantly with a progress bar), links become clickable, **edit in place**, **Undo** after delete, pinned notes in their own section, tags filter, date filter behind one button. Reminders get a **Next up** card, live countdowns, and sit in their own tab on phones.
- **Community**: a quote spotlight with **Another**, one-tap copy of `!quote N`, avatars for regulars, **Add several regulars at once**, a two-tap confirm for deletes (quote numbers are used in chat, so they have no Undo), counts, and real search.
- **Insights**: change versus the period before on Messages and Flagged, **What stood out** (plain sentences), **Busiest hours**, ranked chatters with avatars and share, and readable names everywhere ("Blocked phrase", "Viewers", "What the bot did").
- **Demo**: scenarios grouped by what they test, each with what you should see and how long it takes, a running indicator, an "Open Desk" shortcut, a calmer background-chat switch, and a confirmed Clean up. The page no longer flickers while it polls.
- **Command palette** gains New note, Set a reminder, Add a quote and Test a message.

### Technical
- New: `pages/widgets.ts`, `pages/modtools.ts`, `manage.css`. `toastAction` (a toast with Undo) in `dom.ts`.
- Tests added for the reset moment (including the clock-change night) and for the new API fields.
- Version bumped to 1.1.5.

## 1.1.4

### Fixes
- **YouTube quota that never reset.** The number shown could stay at yesterday's total whenever the bot was idle, because the daily roll-over only happened inside the live loop. It is now worked out from the current Pacific-time day every time it is read, so it drops to 0 at the reset. The Desk status card shows "Resets in 5h 12m".
- **Quota used with no stream.** While live mode waited for a stream, SavahBot kept looking for it. The search budget for other channels was kept only in memory, so every restart gave it a fresh allowance. It is now stored in the database. Defaults are gentler: own-channel check every 180s (was 90s), search for another channel every 900s (was 600s) and at most 10% of the daily quota (was 25%). Set `YOUTUBE_VIDEO_ID` to skip searching completely. The YouTube loop only runs in live mode, so Demo never adds to the count.
- **Quota is an estimate, and now says so.** YouTube gives apps no way to read the real remaining quota (only the Google Cloud Console shows it), so SavahBot counts what it spends. The card says "(estimate)" and has a **Fix count** button to type the number from the Console, or start again from 0. API: `POST /api/youtube/quota {"used": n}`.
- **Chat no longer shows the bot's internals.** Moderated lines used to print the verdict, the score and the exact rule matches (including blacklist words). The feed now shows a small label such as "Blocked · banned phrase, link". Full details stay on the Moderation page.
- **More tab icon** is now the three-line menu instead of the same grid as Desk.

## 1.1.3

### Fixes
- **Expand no longer lags or freezes the phone.** The chat card used to animate its size and position while live chat kept arriving, forcing a re-layout every frame, and blurred the whole screen behind it. It now appears with a short fade and slide (no blur, no size animation), and chat auto-scroll is batched to once per frame.
- **One tap to close.** The expand/collapse button works on a single tap in both directions. The hidden double-click on the title bar is removed, and a quick re-tap during the animation can no longer leave the card stuck.
- **Close button always visible.** On phones the tool row could scroll the expand/close button off the right edge. It is now pinned outside the scrolling tools and reads "Close" when expanded.
- **Expanded chat now really closes.** Closing tried to move the waiting list inside itself, which throws and stopped the card from closing (the icon flipped but the card stayed). Fixed, and closing can no longer be blocked by an error. The Close button keeps its icon and label side by side on phones.
- **Chat card polish.** Rounder, calmer card with a clearer header and input bar, softer rows and larger touch targets for the expand button.

## 1.1.2

### Redesign
- **More is now a real page.** On phones the More tab opens a full hub instead of a small sheet: a live status card with the Demo/Live switch, searchable Manage and System sections with live counts (notes, reminders, quotes, regulars, setup progress), theme, search, shortcuts and sign out. It works on tablets and desktops too (`#/more`, shortcut `g` then `o`).
- **Manage and System feel like one place.** Notebook, Community, Insights and Demo (Manage) and Setup and Settings (System) share a switcher at the top, so you can move between them in one tap on any screen size.
- **Setup rebuilt as a guided stepper.** Overview with a progress ring and a "Next up" button, then Addresses, YouTube, Telegram and Variables as separate steps with their own navigation (a side list on desktop, a scrolling step bar on phones), done/needs-attention marks, Back and Next buttons, and links that open a given step (`#/setup?step=youtube`). The two checks on the YouTube step (Verify access, Run check) sit where they are needed. A "only what is missing" filter was added to Variables.
- **Desk chat zooms to fill the screen.** Click the chat title bar, the expand button, or press `F`: the card grows from where it sits to fill the workspace (the whole screen on phones) and shrinks back to the same spot with Esc. Expanded, it adds text size controls, a live messages-per-minute pill and the waiting-for-you list beside the chat (a slide-in panel on narrow screens). Respects reduced motion.
- Notebook: grid or list view, newest/oldest order, copy a note, show when it was written.
- Community: one search box for quotes and regulars.

### Search and dates
- **Date filters** (Any time, Today, Yesterday, 7 days, 30 days, or a custom From/To) now exist in: Moderation history, the Desk chat (searches the saved chat for that range, with a Back to live button), Notifications and Notebook.
- Moderation history is filtered on the server (outcome, text, dates) and has Load more, so older actions are reachable. New API: `GET /api/moderation/history?since=&until=&q=&status=&offset=` and `GET /api/chat/search?q=&since=&until=&verdict=`. Times are epoch seconds; `until` is exclusive.

### Telegram
- Rich cards: bold headings, status meters, quoted chat lines, icons. Approval requests, stream start/end, flags and reminders were restyled.
- **Tap menu.** `/menu` (or `/start`) opens buttons for Status, Waiting, Stats, Modes, Notes, Reminders, Recent actions and Help. Buttons edit the same message in place, so the chat stays tidy. Demo/Live and Off/Suggest/Auto switch with one tap.
- New `/find <text> [date]` searches saved chat and `/history [date] [outcome]` lists what the bot did. Date words: `today`, `yesterday`, `week`, `month`, `3d`, `12h`, `2026-11-05`, `2026-11-01..2026-11-05` (in your timezone).
- Formatting never loses a message: if Telegram rejects the formatted version it is resent as plain text. Anything typed by viewers is escaped.
- Approve/Reject buttons now read "✅ Approve" and "❌ Reject".

### Technical
- Version is defined once in `frontend/src/version.ts` and `backend/app/__init__.py`.
- New styles live in `frontend/src/redesign.css` (palette unchanged). No database changes.

## 1.1.1

### Fixes
- **Sheets open at the top.** The More sheet (and other sheets) no longer scroll to the middle when opened.
- **Flagged filter.** Flagged on the Desk now shows everything moderation reacted to (it matches the Flagged number); Blocked shows the part that needed action. Both show counts.
- **Demo and Live no longer mix.** Pages redraw when you switch mode. Chat, waiting approvals, history and the "waiting" count now belong to the mode you are in (backend and dashboard). The chat-line counter restarts on a mode switch.
- Removed the duplicate theme button from the top bar (it stays in the sidebar and in More).

### New
- **Notification center.** The bell now opens its own panel (stream start and end, reminders, failed actions, expired approvals, YouTube and Telegram problems, quota warnings) with unread badge, filters, mark all read and clear. Moderation approvals stay under Moderation.
- **Timers rebuilt.** A time and a number of chat lines are each optional (at least one is required). When both are set choose "both must happen" or "whichever comes first". Repeat, post once, or post a set number of times. Presets, a plain-language summary, "Post now", and timers that finish switch themselves off. Existing timers keep working unchanged; the database is upgraded automatically on start.
- **Auto-replies (new foundation).** When a viewer sends an exact phrase, or a message containing a word, the bot answers. Commands always win. Per-rule user level, cooldowns, optional @mention and $(variables). API: `/api/triggers`. Settings: `TRIGGERS_ENABLED`, `TRIGGER_DEFAULT_COOLDOWN`, `TRIGGER_USER_COOLDOWN`.
- **New status card** with a distinct icon for Demo, Standby and Live (no more orange lamp) and a redesigned Demo / Live switch; the phone status pill matches.
- Commands page is now tabs: Commands, Auto-replies, Timers.

Version bumped to 1.1.1.

## 1.1.0

### Dashboard redesign (frontend only, no API or database changes)

- **Adaptive layout.** Full sidebar on desktop, icon rail on tablets, and on phones a top bar with a bottom tab bar plus a "More" sheet. Safe-area aware, 44 px touch targets, 16 px inputs (no iOS zoom), tables turn into cards on phones, forms open as bottom sheets.
- **New logo** (transparent background, SVG, inline and as app icons), favicon, Apple touch icon and an installable web app manifest ("Add to Home Screen"). Logo files are also in `branding/`.
- **All emoji and glyph icons replaced** by a built-in SVG icon set.
- **Charts and graphs.** Insights now has KPI cards with trend lines, an interactive area chart (hover or touch), donut charts (chatter levels, moderation outcomes), bar charts, peak and average rate, and CSV export. The Desk shows a live chat-rate trend and a YouTube quota ring.
- **Desk:** KPI strip, chat filters (all, flagged, blocked), chat search, pause and resume, "Latest" jump button, and a bot status card (YouTube, Telegram, database).
- **Moderation:** mode picker cards, history filters, search and CSV export, phrase search, and a tester that shows each signal as a weighted bar.
- **Commands:** search, inline on/off switches, tap-to-insert variables, editor in a sheet.
- **Notebook:** note cards, pinned first, search and tag filter, quick reminder presets.
- **Setup:** progress checklist. **Settings:** "changed from default only" filter and remembered open groups.
- **Command palette** (Ctrl or Cmd + K, or `/`): jump to any page, switch mode, change theme, run demo scenarios. Shortcuts: `g` then `d m c n u i x s t`, `?` for help.
- **Theme switch:** auto, light or dark, remembered, no flash on load. Colours and accent unchanged; no glows.
- Sign-in screen redesigned.

Version bumped to 1.1.0 (backend `__version__`, dashboard `package.json`).

## 1.0.0

### YouTube safety fixes on top of the account / target-channel work

- **Moderator identity fails closed.** When `YOUTUBE_MODERATOR_ACCOUNT` is set, SavahBot no longer monitors a chat or performs any action unless the signed-in account has been confirmed to match. A failed, skipped or empty identity lookup used to be treated as a pass. It is re-checked every 30 s while blocked, and also when the setting is changed mid-stream (the stream is released).
- **Sign-in is verified before it is kept.** The OAuth callback asks Google which account signed in and only then saves the login. A wrong or unconfirmable account is not saved and a previous working connection is left unchanged. Changing to a different account is explicit and releases the attached stream, learned permissions and cooldowns.
- **Refresh tokens are never mixed between accounts.** A sign-in that returns no refresh token is refused (it used to keep the new account's access token with the old account's refresh token). A token refresh that was in flight when the login changed is discarded.
- **Deletion safeguards restored.** A permission refusal stops a batch of deletes (and the ban that follows), and starts a five-minute cooldown per kind of action (`YOUTUBE_PERMISSION_RETRY_SECONDS`) with no requests and no quota spent. Protected-user refusals (owner or another moderator) are not treated as permission denials.
- **`chatEndedEvent`** now ends monitoring immediately.
- **Exponential backoff** (30 s up to 5 min) for repeated unexpected errors, reset on success.
- **Verify access**: `POST /api/youtube/verify` and a Setup page button. It never searches (100 units) and never moderates; delete and ban are reported as unverified until YouTube answers a real action.
- Unchanged on purpose: `@handle` targets, pinned video links, the search budget cap, and livestream discovery.

New setting: `YOUTUBE_PERMISSION_RETRY_SECONDS` (default 300). No database changes.
