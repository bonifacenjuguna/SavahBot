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
