# Ban management guide

Find it in **Manage > Bans** (shortcut `b`), and in Telegram with `/bans` and `/unban`.

## What it does

- **Ledger.** Every timeout and ban SavahBot makes (automatic or approved by you) is recorded with who, when, why and YouTube's ban id.
- **Lift a ban.** The Lift button calls YouTube's `liveChatBans.delete` (200 quota units, per YouTube's quota table). The ledger only marks it lifted after YouTube confirms. Lifting also clears that person's strikes.
- **Timeouts** show as *Ended* once their time runs out, and can be lifted early.
- **Telegram:** `/bans [name]` lists active ones, `/unban <id or name>` lifts them.

### Limits you should know
YouTube has no call that lists a channel's bans, and lifting needs the id YouTube returned at ban time. So only bans made by SavahBot from 1.2.0 can be lifted here. Older bans and bans made in YouTube Studio must be lifted in YouTube Studio. The Lift button is greyed out when a row has no id.

## Be gentler: the rules

All rules only ever *lower* an action. A message that breaks a rule is still deleted.

| Setting | Effect |
|---|---|
| `MOD_MAX_PUNISHMENT` | `delete` = never time out or ban anyone (delete-only mode); `timeout` = never ban; `ban` = no limit |
| `MOD_NEVER_PUNISH` | Names or channel ids that are never timed out or banned |
| `MOD_REASON_CAPS` | Cap per trigger, e.g. `link:delete,caps:delete,raid:ban` |
| `MOD_AUTO_PUNISH_DAILY_CAP` | After this many automatic timeouts and bans in a day, the bot only deletes (0 = no limit). Things you approve by hand are not counted against it |
| `MOD_SECOND_CHANCE_HOURS` | Lift permanent bans the bot made by itself after this many hours (0 = never) |

Already existing, in Settings > Moderation: `MOD_STRIKES_TO_TIMEOUT` (delete first N times), `MOD_STRIKES_TO_BAN` with `MOD_STRIKE_DECAY_MINUTES` (ban after X strikes within Y minutes), `MOD_TIMEOUT_LADDER`, `MOD_MODE` and `MOD_AUTO_ACTIONS`.

Try a rule without risk: `POST /api/bans/preview` with `{"action":"ban","signals":["link"]}` returns what the rules would turn it into and changes nothing.

## API
`GET /api/bans?status=active|lifted|expired&q=name`, `POST /api/bans/{id}/lift`, `POST /api/bans/preview`.
