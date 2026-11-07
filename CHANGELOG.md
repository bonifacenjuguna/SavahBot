# Changelog

## 1.1.6

### The knowledge layer (no AI model, no API)
SavahBot now reads chat with a library of knowledge and a team of detectors. All of it is classic, explainable technique running inside your bot: weighted phrase matching (Aho-Corasick), typo tolerance (BK-tree and edit distance), scam-intent scoring from word groups, a Naive Bayes classifier, BM25 similarity to known spam, link analysis and a raid-wave tracker. Nothing calls an outside service to judge a message.

- **40 knowledge packs, about 1,900 entries**, one JSON file per topic under `backend/app/intel/packs/<category>/`: Scams (giveaways, crypto doublers, fake account warnings, fake support, fake testimonials, get-rich pitches, M-Pesa and betting scams, word groups), Spam (self-promotion, follower sellers, adult bait), Abuse (profanity, insults, threats), Links (shorteners, messenger invites, risky endings, protected brands, scam address patterns, threat lists), Impersonation, Languages (Swahili and a small Sheng starter set), Safe phrases (gaming talk), Normalisation (look-alike letters) and Training examples. Adding knowledge means adding a file.
- **12 detectors**, each Off, **Shadow** (records what it would have caught, never scores) or Live, with its own strength: scam phrases, spam and promotion, abuse, threats and harassment, typo and disguise matching, link intelligence, impersonation guard, text tricks, bot-like accounts, spam-likeness (Naive Bayes), known-spam similarity (BM25) and raid wave.
- **Typo and disguise matching** also covers your own Blocked phrases: `frree robus` now matches `free robux`. Short words must match exactly, so `you have worn` never matches `you have won`.
- **Link intelligence**: look-alike domains (`youtub3.com`, `paypa1.com`), brand names inside other domains, punycode and mixed alphabets, bare IP links, the `user@host` trick, shorteners, messenger invites, risky endings, bait words in the address, and domains from threat lists.
- **Context awareness**: a question about a scam (`is that giveaway real?`) or a warning to others (`don't click that, it's a scam bot`) scores far lower than the scam itself, unless the message carries a link, phone number or wallet address. Safe phrases protect gameplay talk (`kill streak`, `I'm dead lol`).
- **Impersonation guard** for names that copy the streamer or pose as staff, and `I am the admin` claims. Names to protect: the setting `intel_protected_names`.
- **Raid wave tracker**: when many brand-new accounts speak within seconds, suspicious messages from new accounts get extra weight for a few minutes, and you get one Telegram notice per wave.
- **Every verdict now explains itself**: each signal has a plain-words reason, and the verdict has a confidence from 0 to 1 and a list of what only shadow mode noticed.
- **Learning from your decisions.** Approve and Reject are training labels. The model learns instantly, the bot works out how far to trust each detector, suggests phrases that keep appearing in approved actions and safe phrases from rejected ones, and tests shadow detectors against your past decisions to suggest promoting the ones that would have agreed with you. Modes: off, **suggest** (default) or auto (confident suggestions only, safe phrases always wait for you). Every change is logged with an **Undo**.
- **Live data.** Public phishing and malware domain lists are fetched by your bot's own server, once a day, politely (ETag, size cap, one list per tick, a startup delay). Well-known sites can never be added, a failed or suddenly shrunken download is refused and the old data kept, and every refresh can be rolled back. Five built-in lists (OpenPhish starts off because its free feed is for personal use) and up to ten of your own, guarded like `$(urlfetch)`.
- **Settings > Knowledge** (new, next to All settings): Overview, Knowledge (browse, search, add, switch off, re-weight, export every pack), Detectors, Learning, Live data and a Test lab that shows exactly how a message is read. The Overview has an **Accuracy check** that runs a held-out set of 68 spam and 105 normal lines with and without the knowledge layer.
- **Eight new Demo scenarios**: scam messages, typos and disguises, look-alike links, impersonator, text tricks, Swahili scams, raid wave, and two that must flag nothing (warnings and questions, gaming talk).

### Safe by design (nothing existing was changed in behaviour)
- The layer only **adds** signals. Your signals, weights, settings, routes and tables are untouched. `intel_enabled = false` gives exactly the 1.1.5 behaviour (a test compares them message by message).
- Everything it adds is capped (`intel_max_weight`, default 60), so it can never ban anyone on its own. When your own Blocked phrases already matched, it adds a small corroboration instead of stacking.
- Defaults are conservative: Abuse, Naive Bayes, similarity and bot-like detectors, and the fake-testimonial pack start in **Shadow**. Threats, scams, links and impersonation start Live.
- The knowledge you change (packs off, phrases added or switched off, re-weighted entries, feed data) lives in the database over the built-in files, so upgrades never overwrite it.

### Measured (development set, not a promise)
On a labelled set kept separate from the training examples: without the layer and with an empty Blocked phrases list, 6% of spam is flagged; with it, **98.5% is flagged and 75% reaches delete level, with 0 false alarms out of 105 normal lines**. A few fixes came from reading failures on this very set, so treat it as a development benchmark. Real chat will differ; use Shadow mode and the Learning tab to tune on your own.

### Fixes
- `backend/.env.example` was stale in 1.1.5 (old quota defaults of 90s, 25% and 600s). It is regenerated; a test already guarded this.

### API
New under `/api/knowledge/`: `overview`, `categories`, `packs/{id}` (GET, PATCH, `/entries` POST and PATCH, `/entries/remove`, `/export`), `detectors`, `test`, `benchmark`, `learning`, `learning/refresh`, `suggestions/{id}/accept|dismiss`, `log/{id}/undo`, `feeds` (GET, POST, PATCH, `/refresh`, `/rollback`, `/delete`). `POST /api/moderation/test` verdicts gain `confidence`, `shadow` and a `why` per signal.

### Technical
- New: `backend/app/intel/` (textkit, bayes, match, links, packs, core, service, learning, feeds, benchmark and `packs/`), `moderation/explain.py`, `api/knowledge_routes.py`; `frontend/src/pages/knowledge*.ts` and `knowledge.css`.
- 42 new settings under **Intelligence**. Five new tables (`knowledge_packs`, `knowledge_entries`, `knowledge_feeds`, `knowledge_suggestions`, `knowledge_log`), created automatically.
- About 120 tests added (packs, algorithms, detectors, learning, feeds with the network faked, routes, demo scenarios, end-to-end API).
- Version bumped to 1.1.6.

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
