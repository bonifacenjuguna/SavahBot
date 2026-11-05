# Changelog

## 1.1.2

### Dashboard
- **Moderation history can be filtered by date.** Quick ranges (Today, Yesterday, 7 days, 30 days), a start and end date (the same date twice selects one day), a visible "Showing ..." summary and a Clear button. The range is applied by the server against the stored history (`GET /api/moderation/history?since=&until=`, unix seconds, start inclusive, end exclusive), so it also reaches entries older than the latest 60. Reversed or invalid ranges are rejected with a clear message, and empty results have their own empty state. CSV export follows the active range. The new filter is a reusable component (`frontend/src/datefilter.ts`).
- **Expandable chat on the desktop Desk.** An Expand button on the Chat card grows the same card into a large centred workspace with a zoom transition; Close, Esc or a click on the backdrop collapse it. History, scroll position, typed text and live updates are untouched because it is the same element. The page behind does not jump, and the control is hidden on narrow screens where the layout is a single column. Respects reduced-motion settings.
- **Navigation.** Each section shows its group (Operate, Manage, System) above its title, an active marker on the current item, tooltips with a short description, and thin group dividers on the tablet icon rail.
- **More (phone) redesigned.** Grouped rows with an icon, title and description for every page, a status row that opens the mode switch, and a Preferences group for theme, search and sign out.
- **Setup guide.** A "next step" card tells you what to do now, the checklist marks the current step and has a Go button for each open step, the YouTube/Telegram/addresses cards are jump targets, troubleshooting tools are collapsed, and loading and error states are explicit.
- Loading placeholders and clearer load errors on Setup, Settings, Community and Notebook.
- Larger touch targets on touch screens, a short fade when changing page.

### Telegram bot
- New look: HTML formatting, consistent cards, quoted chat messages, status bars.
- New main menu (`/start`, `/menu`) with buttons for Status, Waiting, Modes, Stats, Notes, Reminders and Help. Screens are edited in place and have Refresh and Menu buttons.
- New **Modes** screen to switch Demo/Live and Off/Suggest/Auto with one tap (same effect as `/mode` and `/mod`).
- Approval requests, flags, reminders and stream events are formatted as cards. Chat content is always escaped, and if Telegram ever rejects a message's formatting it is re-sent as plain text.
- All existing commands, the `approve:<id>` / `reject:<id>` buttons, the owner-only rules and `/claim` are unchanged. New commands: `/menu`, `/modes`.

### Under the hood
- `Store.action_history(since, until)`; `/api/moderation/history` returns the range it applied.
- Telegram presentation lives in `backend/app/services/telegram_ui.py`; the hub and scheduler still send plain text.
- Version bumped to 1.1.2 (backend, dashboard, package metadata, ZIP).

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
