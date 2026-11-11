# API reference

Generated from the server's route table by `python scripts/gen_api_doc.py`. All paths start with `/api`. Send `Authorization: Bearer <session token>` (from `/api/auth/...`). Errors are `{"error": "message", "code"?: "..."}` with a matching HTTP status; validation errors are 422.

**public** = no sign-in needed. **limited ok** = also allowed for a session in lockdown or one that has not finished two-method sign-in.

Secrets are never returned by any route: only whether they are set. Push device tokens, TOTP secrets, recovery codes and session tokens are never listed.


## activity

| Method | Path | Notes |
|---|---|---|
| GET | `/api/activity` |  |
| GET | `/api/activity/export` |  |

## analytics

| Method | Path | Notes |
|---|---|---|
| GET | `/api/analytics` |  |

## auth

Sign-in (password, passkey, authenticator, recovery) and sessions.

| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/factor` | public |
| POST | `/api/auth/login` | public |
| POST | `/api/auth/logout` | limited ok |
| GET | `/api/auth/me` |  |
| POST | `/api/auth/passkey/options` | public |
| POST | `/api/auth/passkey/verify` | public |

## backup

Encrypted export, import and restore.

| Method | Path | Notes |
|---|---|---|
| POST | `/api/backup/export` |  |
| GET | `/api/backup/first-run` | public |
| POST | `/api/backup/first-run` | public |
| POST | `/api/backup/import` |  |
| GET | `/api/backup/info` |  |
| POST | `/api/backup/undo` |  |
| POST | `/api/backup/verify` |  |

## bans

Bans and timeouts.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/bans` |  |
| POST | `/api/bans/preview` |  |
| POST | `/api/bans/{ban_id:int}/lift` |  |

## blacklist

| Method | Path | Notes |
|---|---|---|
| GET | `/api/blacklist` |  |
| POST | `/api/blacklist` |  |
| DELETE | `/api/blacklist/{id:int}` |  |
| PATCH | `/api/blacklist/{id:int}` |  |

## chat

| Method | Path | Notes |
|---|---|---|
| POST | `/api/chat/act` |  |
| GET | `/api/chat/costs` |  |
| DELETE | `/api/chat/demo` |  |
| GET | `/api/chat/person` |  |
| GET | `/api/chat/recent` |  |
| GET | `/api/chat/search` |  |
| POST | `/api/chat/send` |  |

## commands

| Method | Path | Notes |
|---|---|---|
| GET | `/api/commands` |  |
| POST | `/api/commands` |  |
| POST | `/api/commands/preview` |  |
| DELETE | `/api/commands/{id:int}` |  |
| PATCH | `/api/commands/{id:int}` |  |

## demo

| Method | Path | Notes |
|---|---|---|
| GET | `/api/demo` |  |
| POST | `/api/demo/ambient` |  |
| POST | `/api/demo/scenario` |  |

## events

| Method | Path | Notes |
|---|---|---|
| GET | `/api/events` |  |

## health

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | public |

## history

Long-term history and charts.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/history` |  |
| GET | `/api/history/storage` |  |

## knowledge

Knowledge packs, detectors, learning, live lists.

| Method | Path | Notes |
|---|---|---|
| POST | `/api/knowledge/benchmark` |  |
| GET | `/api/knowledge/bundle` |  |
| POST | `/api/knowledge/bundle/import` |  |
| GET | `/api/knowledge/categories` |  |
| GET | `/api/knowledge/detectors` |  |
| PATCH | `/api/knowledge/detectors/{det}` |  |
| GET | `/api/knowledge/feeds` |  |
| POST | `/api/knowledge/feeds` |  |
| PATCH | `/api/knowledge/feeds/{fid}` |  |
| POST | `/api/knowledge/feeds/{fid}/delete` |  |
| POST | `/api/knowledge/feeds/{fid}/refresh` |  |
| POST | `/api/knowledge/feeds/{fid}/rollback` |  |
| GET | `/api/knowledge/health` |  |
| GET | `/api/knowledge/hits` |  |
| GET | `/api/knowledge/learning` |  |
| GET | `/api/knowledge/learning/quality` |  |
| GET | `/api/knowledge/learning/queue` |  |
| POST | `/api/knowledge/learning/refresh` |  |
| POST | `/api/knowledge/learning/reset` |  |
| GET | `/api/knowledge/lessons` |  |
| POST | `/api/knowledge/lessons` |  |
| GET | `/api/knowledge/lessons/export` |  |
| POST | `/api/knowledge/lessons/import` |  |
| DELETE | `/api/knowledge/lessons/{lid:int}` |  |
| POST | `/api/knowledge/lessons/{lid:int}/flip` |  |
| POST | `/api/knowledge/log/{lid:int}/undo` |  |
| GET | `/api/knowledge/overview` |  |
| GET | `/api/knowledge/packs/{pack_id}` |  |
| PATCH | `/api/knowledge/packs/{pack_id}` |  |
| PATCH | `/api/knowledge/packs/{pack_id}/entries` |  |
| POST | `/api/knowledge/packs/{pack_id}/entries` |  |
| POST | `/api/knowledge/packs/{pack_id}/entries/remove` |  |
| GET | `/api/knowledge/packs/{pack_id}/export` |  |
| GET | `/api/knowledge/snapshots` |  |
| POST | `/api/knowledge/snapshots` |  |
| DELETE | `/api/knowledge/snapshots/{sid:int}` |  |
| POST | `/api/knowledge/snapshots/{sid:int}/restore` |  |
| POST | `/api/knowledge/suggestions/bulk` |  |
| POST | `/api/knowledge/suggestions/{sid:int}/accept` |  |
| POST | `/api/knowledge/suggestions/{sid:int}/dismiss` |  |
| POST | `/api/knowledge/test` |  |

## live

| Method | Path | Notes |
|---|---|---|
| GET | `/api/live/events` |  |
| GET | `/api/live/stats` |  |
| GET | `/api/live/streams` |  |

## mode

| Method | Path | Notes |
|---|---|---|
| POST | `/api/mode` |  |

## moderation

| Method | Path | Notes |
|---|---|---|
| GET | `/api/moderation/history` |  |
| GET | `/api/moderation/level` |  |
| POST | `/api/moderation/level` |  |
| GET | `/api/moderation/pending` |  |
| POST | `/api/moderation/test` |  |
| POST | `/api/moderation/{id:int}/{verb}` |  |
| POST | `/api/moderation/{verb}-all` |  |

## notes

| Method | Path | Notes |
|---|---|---|
| GET | `/api/notes` |  |
| POST | `/api/notes` |  |
| DELETE | `/api/notes/{id:int}` |  |
| PATCH | `/api/notes/{id:int}` |  |

## notify

Notification Centre: preferences, inbox, devices, test, stats.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/notify/categories` |  |
| POST | `/api/notify/check` |  |
| GET | `/api/notify/config` | limited ok |
| POST | `/api/notify/delete` |  |
| GET | `/api/notify/devices` |  |
| POST | `/api/notify/devices` |  |
| POST | `/api/notify/devices/unregister` |  |
| DELETE | `/api/notify/devices/{device_id:int}` |  |
| PATCH | `/api/notify/devices/{device_id:int}` |  |
| GET | `/api/notify/inbox` |  |
| GET | `/api/notify/item/{nid:int}` |  |
| GET | `/api/notify/log` |  |
| POST | `/api/notify/pause` |  |
| GET | `/api/notify/prefs` |  |
| PATCH PUT | `/api/notify/prefs` |  |
| POST | `/api/notify/read` |  |
| GET | `/api/notify/stats` |  |
| POST | `/api/notify/test` |  |
| GET | `/api/notify/unread` | limited ok |

## quotes

| Method | Path | Notes |
|---|---|---|
| GET | `/api/quotes` |  |
| POST | `/api/quotes` |  |
| DELETE | `/api/quotes/{id:int}` |  |

## reader

| Method | Path | Notes |
|---|---|---|
| GET | `/api/reader/rules` |  |
| POST | `/api/reader/rules` |  |

## regulars

| Method | Path | Notes |
|---|---|---|
| GET | `/api/regulars` |  |
| POST | `/api/regulars` |  |
| DELETE | `/api/regulars/{id:int}` |  |

## reminders

| Method | Path | Notes |
|---|---|---|
| GET | `/api/reminders` |  |
| POST | `/api/reminders` |  |
| DELETE | `/api/reminders/{id:int}` |  |

## security

Security & Access Centre: methods, sessions, activity, audit, lockdown.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/security/activity` | limited ok |
| POST | `/api/security/lockdown` | limited ok |
| GET | `/api/security/overview` | limited ok |
| POST | `/api/security/passkeys/options` |  |
| POST | `/api/security/passkeys/register` |  |
| DELETE | `/api/security/passkeys/{pid:int}` |  |
| PATCH | `/api/security/passkeys/{pid:int}` |  |
| POST | `/api/security/password` | limited ok |
| POST | `/api/security/recovery` |  |
| GET | `/api/security/sessions` | limited ok |
| POST | `/api/security/sessions/revoke-others` | limited ok |
| DELETE | `/api/security/sessions/{ref}` | limited ok |
| POST | `/api/security/step-up` | limited ok |
| DELETE | `/api/security/totp` |  |
| POST | `/api/security/totp/begin` |  |
| POST | `/api/security/totp/confirm` |  |

## settings

Environment settings and the Settings overview.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/settings` |  |
| PATCH | `/api/settings` |  |
| GET | `/api/settings/overview` |  |
| DELETE | `/api/settings/{name}` |  |

## setup

| Method | Path | Notes |
|---|---|---|
| GET | `/api/setup` |  |

## status

| Method | Path | Notes |
|---|---|---|
| GET | `/api/status` |  |

## system

Service health and the data inventory.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/system/data` |  |
| POST | `/api/system/data/clear` |  |
| GET | `/api/system/health` |  |

## telegram

Telegram bot control.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/telegram/control` |  |
| POST | `/api/telegram/control` |  |
| DELETE | `/api/telegram/log` |  |
| GET | `/api/telegram/log` |  |
| POST | `/api/telegram/mode` |  |
| POST | `/api/telegram/rotate-secret` |  |
| POST | `/api/telegram/shutdown` |  |
| GET | `/api/telegram/status` |  |
| POST | `/api/telegram/test` |  |
| POST | `/api/telegram/unlink` |  |
| POST | `/api/telegram/webhook` | public |

## timers

| Method | Path | Notes |
|---|---|---|
| GET | `/api/timers` |  |
| POST | `/api/timers` |  |
| DELETE | `/api/timers/{id:int}` |  |
| PATCH | `/api/timers/{id:int}` |  |
| POST | `/api/timers/{id:int}/send` |  |

## triggers

| Method | Path | Notes |
|---|---|---|
| GET | `/api/triggers` |  |
| POST | `/api/triggers` |  |
| DELETE | `/api/triggers/{id:int}` |  |
| PATCH | `/api/triggers/{id:int}` |  |

## variables

| Method | Path | Notes |
|---|---|---|
| GET | `/api/variables` |  |
| POST | `/api/variables` |  |
| POST | `/api/variables/delete` |  |

## voices

| Method | Path | Notes |
|---|---|---|
| GET | `/api/voices` |  |
| POST | `/api/voices/delete` |  |
| POST | `/api/voices/file` |  |
| GET | `/api/voices/files/{pack}/{path:path}` | public |
| POST | `/api/voices/host` |  |
| POST | `/api/voices/zip` |  |

## weather

Weather: places, forecast, preferences, alert rules.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/weather/catalog` |  |
| GET | `/api/weather/current` |  |
| GET | `/api/weather/daily` |  |
| GET | `/api/weather/hourly` |  |
| GET | `/api/weather/locations` |  |
| POST | `/api/weather/locations` |  |
| DELETE | `/api/weather/locations/{loc_id:int}` |  |
| PATCH | `/api/weather/locations/{loc_id:int}` |  |
| POST | `/api/weather/locations/{loc_id:int}/default` |  |
| GET | `/api/weather/overview` |  |
| GET | `/api/weather/prefs` |  |
| PATCH PUT | `/api/weather/prefs` |  |
| POST | `/api/weather/refresh` |  |
| GET | `/api/weather/rules` |  |
| POST | `/api/weather/rules` |  |
| DELETE | `/api/weather/rules/{rule_id:int}` |  |
| PATCH | `/api/weather/rules/{rule_id:int}` |  |
| GET | `/api/weather/search` |  |
| GET | `/api/weather/status` |  |

## youtube

YouTube connection and quota.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/youtube/diagnostics` |  |
| POST | `/api/youtube/disconnect` |  |
| GET | `/api/youtube/oauth/callback` | public |
| POST | `/api/youtube/oauth/start` |  |
| POST | `/api/youtube/quota` |  |
| POST | `/api/youtube/source` |  |
| GET | `/api/youtube/status` |  |
| POST | `/api/youtube/use-own-channel` |  |
| POST | `/api/youtube/verify` |  |
