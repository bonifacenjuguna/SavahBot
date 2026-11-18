# Troubleshooting

## Can't sign in
- **After upgrading to 1.2.0**: you are signed out once. Use your password. If two methods are set up, you also need a second: authenticator code, passkey, or a recovery code.
- **Locked out of everything**: use a recovery code. With none left, see BACKUP_AND_RECOVERY.md (first-run restore token) or set `OWNER_PASSWORD` and redeploy to reset the password (other methods stay).
- **"Too many attempts"**: wait a few minutes; attempts are limited per address.

## Passkey won't register or sign in
It must run on https, `FRONTEND_URL` must be your real dashboard address, and you must use the same hostname each time. A changed domain invalidates passkeys.

## Push notifications
| Symptom | Likely cause |
|---|---|
| No "Turn on push" button; says not set up | Some of the seven FIREBASE_* values are missing. The Notifications > Overview checklist shows which. |
| "Check the service account" fails: key unreadable | `FIREBASE_PRIVATE_KEY` pasted without its `-----BEGIN PRIVATE KEY-----` lines or with real line breaks cut. Use `\n` for breaks, or paste the whole JSON into `FIREBASE_SERVICE_ACCOUNT_JSON`. |
| "Not allowed to send" | Enable the Firebase Cloud Messaging API (V1) in Google Cloud and give the service account the Firebase Cloud Messaging Admin role. |
| Button says blocked | Allow Notifications in the browser's site settings, reload. |
| iPhone: no push | Needs iOS 16.4+ and the app added to the Home Screen, opened from there (PWA_AND_PUSH_PLATFORMS.md). |
| Test works, real ones don't arrive | Quiet hours, pause, category set to bell only, or the phone's battery saver. Check Notifications > Schedule and Delivery. |
| Device vanished from the list | Firebase said its token was dead (app data cleared, permission revoked). Turn push on again. |

## Weather
- **"Could not reach the weather service"**: temporary; the page shows the last good data marked old. The Developer tab shows if calls are paused after repeated errors.
- **Place not found**: try the English name, a larger nearby town, or enter coordinates.
- **No alerts**: alerts need a default place, alerts switched on, and the category enabled under Notifications. Each rule has a cooldown.

## Settings, data, backup
- A setting seems ignored: dashboard-saved values override the environment; use Reset to default in All settings.
- Import says wrong key or damaged: the key (SVK1-...) must match that file; check the file was fully downloaded.
- Settings > Developer shows database, Redis and background job health, and a plain-language configuration check. Start there.

## Where to look
Railway > Deployments > logs. Lines are tagged `savahbot.<area>` (notify, weather, access, backup). Coordinates, tokens and secrets are never logged.

- Startup on a database that already had an older `notifications` table failed with `column "dedupe_key" does not exist` (indexes were built before missing columns were added). Fixed: tables, then missing columns, then indexes (non-unique index failures only warn).
