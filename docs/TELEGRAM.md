# Telegram guide

The Telegram bot is your private control panel. Only the owner's account can use it; everyone else gets silence.

## Setup (short)
1. In Telegram, talk to @BotFather, `/newbot`, copy the token into `TELEGRAM_BOT_TOKEN`.
2. Redeploy, open the bot, send `/claim <your dashboard password>` once. It binds the bot to you.
3. Pick `webhook` (needs `PUBLIC_BASE_URL`) or `polling` with `/tgmode`.

## Commands
| Area | Commands |
|---|---|
| Status | `/status`, `/stats [hours]`, `/quota`, `/menu` |
| Modes | `/mode demo|live`, `/mod off|suggest|auto`, `/tgmode webhook|polling` |
| Moderation | `/pending`, `/approve <id|all>`, `/reject <id|all>`, `/permit <user> [seconds]`, `/history`, `/bans`, `/unban <id|name>` |
| Security | `/lockdown` signs every dashboard device out immediately |
| Chat | `/say <text>`, `/find <text> [date]`, `/demo [scenario]` |
| Notes | `/note`, `/notes`, `/delnote`, `/remind <when> <text>`, `/reminders`, `/delremind` |
| **Weather** | `/weather [place]`, `/forecast [place]`, `/hourly [place]`, `/locations [number]` |

Weather commands use your default place when none is given, accept a saved place's name or number, or search any place by name. They go through the same cached service as the dashboard, so Telegram never calls Open-Meteo directly and says plainly when data is old.

## What Telegram receives from the Notification Centre
Telegram already reports approvals, stream events, reminders, raids, quota warnings and security alerts through its own settings, so those are not repeated. The Notification Centre adds Telegram messages for: failed moderation actions, YouTube problems, push delivery problems and (if you switch them on per category) weather alerts and summaries. Switch per category under Notifications > Categories.

## Safety
Commands from any account other than the owner are ignored. `/lockdown` needs no password because it only reduces access; lifting lockdown needs the dashboard and a full sign-in.
