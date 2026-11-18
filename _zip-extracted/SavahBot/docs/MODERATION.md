# Moderation, commands and timers


Every chat message is normalised (Unicode folding, look-alike letters, leetspeak, zero-width characters, stretched letters) and scored from 0 to 100 by independent signals:

| Signal | What it catches |
|---|---|
| blacklist | Banned words and phrases, including spaced-out or disguised ones (Aho-Corasick), plus regex entries |
| link | Links from people who have not been permitted (`!permit <name>`) |
| caps, symbols, emotes, repetition, length | Shouting, noise, emote walls, stretched characters, walls of text |
| rate, duplicate | Flooding and repeating yourself |
| raid | Several accounts posting near-identical text (SimHash) |
| interval | Accounts posting at machine-regular intervals (timing variation) |
| new_chatter | Extra weight for accounts seen for the first time |

Score maps to flag, delete, timeout or ban, and repeat offenders climb a timeout ladder. Mods, the owner and regulars are exempt or softened by level.

**Modes** (Moderation page or `/mod`): *off* only logs; *suggest* (default) queues the action for your approval in the dashboard and Telegram; *auto* acts immediately and tells you. Messages loaded when the bot first attaches to a chat are stored but never moderated.

## Commands, timers and more

- Custom commands with variables: `$(user) $(touser) $(args) $(1) $(count) $(countdown ...) $(uptime) $(time) $(date) $(random 1 100) $(choose a|b) $(math 2+2) $(quote) $(urlfetch https://...)`. `$(math)` is parsed safely (never `eval`) and `$(urlfetch)` blocks private networks and redirects.
- Per-command user level and cooldowns, aliases, a live preview, and built-ins (`!commands !addcom !editcom !delcom !permit !quote !addquote !uptime`).
- Timers post only while the stream is live. Each timer waits for a time, a number of chat lines, or both (both must happen, or whichever comes first), and can repeat, post once, or post a set number of times. "Post now" sends one immediately.
- Auto-replies answer when a viewer sends an exact phrase (or contains a word). They never override `!commands`, have cooldowns and a user level, and can be switched off with `TRIGGERS_ENABLED`.
- The bell is the notification center (stream start, reminders, failures, quota warnings). Moderation approvals live under Moderation.
- Notes and reminders (`30m`, `2h30m`, `18:30`, `tomorrow 09:00`, `daily 08:00`, `every 2h`), delivered to Telegram and the Desk.
- Insights: activity timeline, top chatters, which signals fire most, and action outcomes.

