# Changelog

## 1.1.0

### Dashboard redesign (frontend only; the backend API is unchanged)

- Responsive layout: desktop side rail, tablet icon rail, phone top bar with bottom tabs and a *More* sheet. Tables turn into stacked cards on phones; touch targets and 16 px inputs on touch screens; safe-area support for notched phones.
- Same colour palette and accent as before. No glow, blur or gradient effects were added.
- New **Overview** home page: stat cards with trend lines, chat-activity column chart (hover or touch details, CSV download), quota gauge, action-outcome donut, approvals waiting, system health, recent actions, top chatters and moderation triggers.
- **Insights** rebuilt on the same dependency-free SVG charts (columns, donuts, ranked bars).
- **Desk**: chat search and filters, staff and member badges, jump-to-latest button, Chat / Waiting tabs on phones.
- Command palette (`Ctrl K`, `Cmd K` or `/`; search button on phones) and a light / dark / device theme switch.
- Installable web app: manifest, app icons and Apple touch icon.
- New logo mark traced from the supplied artwork (background removed), used as an inline SVG that follows the theme, plus favicon and app icons.
- All icons are inline SVG; the checkmark and circle glyphs on Setup were replaced. No emoji anywhere in the interface.
- Version is shown in the side rail.
- Setup page: the target channel now shows the value in force and where it comes from (dashboard or Railway variable), with a one-tap reset.

### Included since 1.0.0

- YouTube safety fixes: fail-closed `YOUTUBE_MODERATOR_ACCOUNT` check, sign-in account verification, refresh tokens never mixed between accounts, five-minute denial cooldown and batch stop, `chatEndedEvent`, exponential backoff, Verify access (`POST /api/youtube/verify`). New setting `YOUTUBE_PERMISSION_RETRY_SECONDS` (default 300).

## 1.0.0 (version number unchanged)

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
