# Changelog

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
