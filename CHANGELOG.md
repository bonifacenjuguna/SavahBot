# Changelog

## 1.1.1

Backward compatible: old API calls still work, database changes are additive (new columns and tables only, applied automatically and safely on SQLite and PostgreSQL).

### Fixed
- **Page opened scrolled to the middle.** Sheets (More, editors) focused their first button, which scrolled the sheet. Focus no longer scrolls, sheets open at the top, new pages always open at the top, and the browser no longer restores a stale scroll offset.
- **Flagged count with an empty Flagged list.** The count included blocked lines but the filter only showed flag-only lines. Counts, filter chips and highlighting now use one classifier; Flagged and Blocked are separate, tappable cards. Moderation has a Flagged tab built from the same records as Waiting for you (`GET /api/moderation/flagged`).
- **Demo and Live out of sync.** Chat, pending requests, history, counters and notifications were not separated by mode, and pages were never redrawn on a switch. Now: one backend state (`hub.state`: demo, standby or live), every read is scoped to the active mode, the session line counter resets on a switch, Approve all only touches the active mode, and every page redraws when the mode changes (here, on another device, or from the Demo page).
- Removed the duplicate theme button from the top bar (theme stays in the sidebar and the More sheet).
- A real stream-ended notification no longer fires when leaving Demo.

### New
- **Mode control**: Demo, Standby and Live in one component, flat colours, confirmation before going Live that states what moderation will do.
- **Notifications** are their own page and store (stream, timers, reminders, mode changes), separate from Moderation. The bell and its badge belong to Notifications; Moderation keeps its own Waiting badge.
- **Moderation**: tabs for Waiting, Flagged, History, Library, Rules and Test. Waiting is a compact, searchable list with expandable rows and progressive loading. Rules lists the real detection signals in categories (spam and flooding, words and phrases, links, suspicious content) with on/off and weight.
- **Library**: collections (words, phrases, spam, links, suspicious, custom), search, multi-select, bulk enable, disable, move and delete, import with a preview that reports new, duplicate and invalid entries before saving, CSV export.
- **Timers**: recurring or one-time; time trigger, line trigger or both (both: wait for "and" or "or"); at least one trigger required for recurring; last and next post, lines still needed, run history, duplicate, bulk actions, failure reporting. Existing timers keep their behaviour (both triggers, "and").
- **Commands**: tabs for Commands, Timers and Auto-replies; templates, bulk actions, usage counts, and a catalog of the built-in commands.
- **Auto-replies (foundation)**: rules are stored and validated, and a tested matcher (phrase, word, contains; case rules; priority) powers a tester. The bot does **not** answer automatically yet, and the page says so.

### API additions
`/api/moderation/flagged`, `/api/blacklist/import` (with `dry_run`), `/api/blacklist/bulk`, `/api/timers/bulk`, `/api/timers/runs`, `/api/timers/{id}/duplicate`, `/api/commands/bulk`, `/api/notifications` (+ `/read`), `/api/auto-replies` (+ `/test`). `scope=all` on list endpoints opts out of mode scoping. Timer create accepts `kind`, `trigger_mode`, `run_at`, and `interval_seconds` of 0.

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
