# Notification Centre guide

Open **Manage > Notifications** (shortcut `a`). One system sends everything: **push** to your phone or computer (Firebase Cloud Messaging), the **bell** inside the dashboard, and **Telegram**. The old ntfy option is gone.

## What you can get
Each row is a real event the bot raises. Nothing here is a placeholder.

| Group | Notifications |
|---|---|
| Moderation | approval needed, action failed, approvals expired, raid wave |
| Stream | went live, ended, mode changed (Demo/Live) |
| Reminders | reminder due, timer finished |
| System | YouTube problem, quota 75% / 90%, Telegram problem, push delivery trouble |
| Security | new device, password / authenticator / passkey / recovery-code changes, lockdown |
| Backup | exported, restored |

For each you choose: on or off, which channels (Push, Bell, Telegram) and the priority (low, normal, high, critical). Telegram already reports approvals, stream events, reminders, raids, quota and security on its own, so those show "Telegram handled there" and are not sent twice.

## How a notification travels
1. The event happens. Only the **leader** instance reacts, so two servers never double-send.
2. Master switch and the category switch are checked.
3. The same event again within its window (for example five approval requests in a row) folds into one entry with a count, and sends **one** push.
4. It is saved to the in-app history (database = source of truth).
5. Push: paused? quiet hours? hourly cap reached? If so it waits and arrives later as **one summary**. **Critical** security alerts break through pause and quiet hours (you can turn that off).
6. A worker sends it with retries (30 s, 2 min, 10 min, 1 h, 6 h; five tries by default). A token Google says is dead is deleted automatically.

## Setting up Firebase (about 10 minutes, free)
You need seven values. Put them in your host's variables (Railway > backend service > Variables), then redeploy. The Notifications page shows a checklist of which are still missing.

1. Go to <https://console.firebase.google.com> and press **Add project**. Name it (for example `savahbot`). You can switch Google Analytics off.
2. **Project settings** (gear icon) > **General**. Copy **Project ID** → `FIREBASE_PROJECT_ID`.
3. Same page, **Your apps** > press the **`</>` Web** icon, give it a nickname, **Register app** (skip Hosting). Firebase shows `firebaseConfig`:
   - `apiKey` → `FIREBASE_WEB_API_KEY`
   - `appId` → `FIREBASE_WEB_APP_ID`
   - `messagingSenderId` → `FIREBASE_MESSAGING_SENDER_ID`
   These are public by design. SavahBot's backend hands them to your dashboard, so you set them **once, on the backend only** (nothing to add on Vercel).
4. **Project settings > Cloud Messaging**. Under **Web configuration > Web Push certificates** press **Generate key pair**. Copy the **Key pair** (a long string) → `FIREBASE_VAPID_KEY`.
5. Still in **Cloud Messaging**, make sure **Firebase Cloud Messaging API (V1)** says *Enabled*. If not, press the three dots and open it in Google Cloud, then **Enable**.
6. **Project settings > Service accounts > Generate new private key**. A JSON file downloads. Open it:
   - `client_email` → `FIREBASE_CLIENT_EMAIL`
   - `private_key` → `FIREBASE_PRIVATE_KEY` (paste the whole thing; line breaks may be written as `\n`)
   Or paste the **entire file** (or its base64) into `FIREBASE_SERVICE_ACCOUNT_JSON` instead of those two.
7. If Google says the account may not send: in Google Cloud > IAM, give that service account **Firebase Cloud Messaging Admin**.

**Never commit that JSON file, never put it on Vercel, never share it.** It can send messages as your project. SavahBot reads it only on the backend and never returns it from any API.

Then open the Notifications page: **Check the service account** proves Google accepts it, **Turn on push on this device** asks the browser for permission (only when you press the button), and **Send a test** shows the result per device.

## Quiet hours, pause, summaries
Quiet hours use your time zone (`OWNER_TIMEZONE`, editable in Settings). Overnight windows such as 22:00 to 07:00 work. Modes: **Hold** (push waits, then arrives as one summary) or **No push** (bell only). The bell always fills. "Pause push" silences push for 1 or 8 hours.

## Privacy
- Device tokens are stored **encrypted** (AES-GCM) and are never shown in the UI, logs, API responses or backups. Only a short label ("Chrome on Android") is shown.
- Tapping a notification can only open a dashboard page (a clean path such as `/moderation`; the stored token is still written `#/moderation`). Any other address is replaced by the Notifications page.
- Security alerts never put their text on a lock screen. You can hide the text of all pushes ("Hide message text").
- No permission prompt appears on page load, only after you press the button.

## Limits (honest)
- Push on iPhone/iPad needs iOS 16.4+ and SavahBot **added to the Home Screen**. See PWA_AND_PUSH_PLATFORMS.md.
- The Firebase browser library is loaded from Google's CDN when you turn push on, so the dashboard must be able to reach `gstatic.com`.
- If every push device is offline, messages are retried for a while and then marked failed; they are still in the bell.

Settings in `.env.example`: `FIREBASE_*`, `NOTIFY_RETENTION_DAYS`, `NOTIFY_MAX_PUSH_PER_HOUR`, `NOTIFY_MAX_ATTEMPTS`.

## For developers
Add a notification kind with `notify.register(Category(...))`, then call `await c.notifier.emit("your.id", "Title", "Body", key="dedupe-key")`, or publish a bus event and map it in `Notifier.handle`. API: `/api/notify/*` (see API.md).
