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

## Telegram controls (Setup, then Telegram)

For when you want to limit the bot, or you suspect it leaks. Every switch is saved in the database and takes effect at once.

| Control | What it does |
| --- | --- |
| **Telegram** (master) | Off removes the webhook, stops polling, hears nothing and sends nothing. On registers it again. |
| **Listen to commands** | Off: commands and buttons are ignored, alerts can still arrive. |
| **Send messages** | Off: the bot sends nothing, including replies. |
| **Allow changes** | Off = read-only. `/mode /mod /tgmode /approve /reject /permit /say /demo /note /delnote /remind /delremind /lockdown /unban` and their buttons are refused; lookups still work. |
| **Allow claiming** | Off: `/claim` is ignored. Leave it off once the bot is claimed. |
| **Pause** | 30 min, 2 h or 8 h of silence in both directions, then it resumes by itself. |
| **Alert types** | Approvals, reminders and stream events can each be switched off. |

**If you think it is compromised**, in order: replace the webhook secret, unlink the owner, or press **Cut Telegram off** (does all of it, closes claiming, removes the webhook). Then open @BotFather, send `/revoke`, pick the bot, and set the new `TELEGRAM_BOT_TOKEN`. If `TELEGRAM_OWNER_ID` or `TELEGRAM_WEBHOOK_SECRET` are set in the environment, those keep applying until you change them there.

**Recent activity** shows what happened (command names, ignored strangers, wrong claim passwords, setting changes), never message text, tokens or passwords. The last 300 entries are kept.
