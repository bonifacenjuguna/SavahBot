# Installing SavahBot and push, by platform

SavahBot is a PWA: it can be installed like an app, and (with Firebase set up, see NOTIFICATIONS.md) it can push to you even when closed. What works depends on the device.

| Platform | Install | Push when the app is closed | Notes |
|---|---|---|---|
| Android, Chrome / Edge | Menu > Install app | Yes | Works in a normal tab too; installed is more reliable. |
| Android, Firefox | Menu > Install | Yes | |
| Windows / macOS / Linux, Chrome / Edge | Install icon in the address bar | Yes | Browser (or its background service) must be running. |
| macOS, Safari 17+ | File > Add to Dock | Yes | |
| Desktop Firefox | no install | Yes, while Firefox runs | |
| iPhone / iPad, Safari | Share > **Add to Home Screen** | **Yes, only from the Home Screen app, iOS 16.4+** | A Safari tab cannot receive push. Open the Home Screen icon, then turn push on there. |
| iOS, Chrome/Firefox/Edge | same as Safari (they use Apple's engine) | same | |

## Good to know
- The permission prompt appears only when you press **Turn on push on this device**. If you tapped Block, allow it again in the site settings (lock icon in the address bar; on iPhone: Settings > Notifications > SavahBot).
- Each browser/device is a separate registration. Remove old ones on the Devices tab.
- Battery savers on some Android phones kill background apps and delay push. Exclude the browser/app from battery optimisation if messages arrive late.
- While the dashboard is open and visible, you get a toast and the bell updates; the system notification is skipped to avoid a double alert.
- Do-not-disturb / Focus modes of the phone always win over SavahBot.
- Not verified here: real iOS, Android and desktop push delivery. The code follows the Web Push and FCM v1 documentation; test on each device with **Send a test**.

## Why Safari tabs fail
Apple only allows web push for sites added to the Home Screen. SavahBot detects this and tells you instead of showing a button that cannot work.

## The installed app (1.4.11)

Everything below is optional and quiet: where a browser lacks a feature, that feature is simply absent and the rest works.

| Feature | What you get | Where it works |
|---|---|---|
| **App icon badge** | The number of moderation requests waiting, on the home-screen / dock / taskbar icon. It follows every push, and the open app. | Installed app on Android, Windows, macOS, Linux (Chromium). iOS shows the badge from push messages only. |
| **Approve / Reject on the notification** | An approval push has two buttons that decide that one request without opening the app. | Android and desktop Chromium. iOS ignores notification buttons: tap to open instead. |
| **Opens offline** | The installed app opens with no connection and shows the last data it saw, under a strip that says when it was taken. | Every browser that supports service workers. |
| **Saved for later** | A note, a quote or a clock-time reminder written offline waits on the device and is sent when the connection returns, even if the app is closed. | Sending with the app closed needs Background Sync (Chromium). Elsewhere, the open app sends it. |
| **Fresh badge while closed** | The icon number refreshes about every 15 minutes or more, using a read-only link. | Installed Chromium apps only; the push messages are the dependable path. |
| **Updates wait for you** | "A new version is ready. Reload" instead of the app changing under you. | Everywhere. |
| **Share to SavahBot** | Share a line or a link from any app, choose SavahBot, and save it as a note or a quote. | Android and desktop Chromium (the installed app appears in the share menu). |
| **`web+savahbot:` links** | `web+savahbot:moderation`, `web+savahbot:notebook` and the like open that page of the installed app. | Chromium. |
| **Title-bar app on desktop** | The installed app draws into its own title bar (window controls overlay) and re-uses one window when launched again. | Windows, macOS, Linux (Chromium). |
| **Windows of their own** | "Open the Desk in its own window" in the command palette (Ctrl+K). Windows share one live connection. | Desktop. |
| **Faster first screen** | Pages load when first opened and are fetched quietly while idle (not on Data Saver or 2G), so they work offline too. | Everywhere. |

### What is kept on the device, and what is not
- **Saved copies for offline reading** live in this browser profile (IndexedDB), only for read-only pages (status, notes, quotes, moderation lists, charts, the inbox). Never sign-in, security, backups, push devices or settings. They expire after a week and are wiped on sign-out.
- **The service worker keeps no API data.** It keeps the app's own files (public code with a hash in its name) and the last page HTML.
- **The Approve and Reject buttons never carry your sign-in.** The server signs a short link that can decide that one request until it would expire anyway; it is refused during lockdown and cannot do anything else.
- **The icon badge link** can read the number of waiting requests and nothing else. It lasts 14 days, is renewed whenever the app is opened, and is removed on sign-out.
- **While a saved write waits,** the service worker is given your sign-in so it can send it; that copy is deleted the moment nothing is waiting, and on sign-out.
