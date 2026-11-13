# Settings guide

**System > Settings** (shortcut `t`) is the control centre. It does not duplicate other pages; it shows where everything is and what needs you.

## Views (tabs)
| Tab | What it is |
|---|---|
| **Overview** | "Needs a look" list, a card per area with status that was actually checked, global search, recently opened. |
| **Appearance** | Theme (system/light/dark), accent colour, density, text size, reduce motion. Saved on this device only. |
| **Privacy & data** | Every kind of data stored, how many items, retention, where it lives, who receives some of it. Clear notification history, push delivery log and weather cache. Security records are protected and cannot be cleared here. |
| **Device & app** | Install status and install help, service-worker state, notification permission, update check, storage use, clear this browser's saved preferences. |
| **Developer** | Configuration check (plain-language problems), database/Redis/background/event health, feature availability, which secrets are set (never their values), deployment info. |
| **Intelligence** | Knowledge packs, detectors, learning, live lists (see KNOWLEDGE.md). |
| **All settings** | The searchable list of every environment option with reset to default (the original Settings page). |

Other areas keep their own pages and are linked from the cards: **Security** (SECURITY.md), **Notifications** (NOTIFICATIONS.md), **Weather > Weather settings** (WEATHER.md), **Backup** (BACKUP_AND_RECOVERY.md), **Setup** (YouTube and Telegram connections), **Moderation, Bans, Commands**.

## Search
Type in the Overview search box. It searches names, descriptions and keywords of every settings area (about 35 entries, each pointing at a real page or tab) and offers to search all environment options too. Words must all match; titles rank first. Recently opened entries are remembered on this device.

## How settings are stored
- **Server settings** (environment options): defaults < environment variables < values saved from the dashboard. Dashboard changes go to the database (`settings` table) and apply at once; "Reset to default" removes them. Validation happens on the server.
- **Feature settings** (notification preferences, weather preferences and rules): database (`kv`), validated by their own service. Redis is never the only copy.
- **Device settings** (appearance, recent searches): this browser only (`localStorage`), because they describe this screen. Losing them only resets looks.
- Secrets are never shown or returned by any settings API: only "set / not set".

## "Needs a look" items
Only things the server can verify are listed: sign-in protected by password only, lockdown on, no recovery codes left, YouTube/Telegram errors or not connected, quota above 90%, no backup exported (or older than 30 days), no push device, no weather place, and configuration problems (for example a missing or non-https FRONTEND_URL, half-filled Firebase values).

## Not included on purpose
No multi-user accounts or roles (SavahBot has one owner), no placeholder switches, no copy of the notification engine. Items such as dashboard card ordering and a sidebar editor were not built: they would add controls without a real need.
