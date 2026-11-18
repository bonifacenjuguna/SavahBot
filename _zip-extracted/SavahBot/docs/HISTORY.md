# Charts and long history

## Tap a chart for the big view
In **Manage > Insights**, tap the *Messages* or *Flagged* number cards, or press **Expand** on *Chat activity* and *What the bot did*. The big view is a bottom sheet on phones and a wide panel on desktop. It offers:

- ranges: 24 h, 7 days, 30 days, 90 days, 1 year, All (hourly points up to 4 days, daily beyond);
- six series you can switch on and off (messages, flagged, people chatting, deleted, timeouts, bans), each with its own colour *and* line style;
- **Compare with the period before** (dotted lines);
- a crosshair you can drag, or move with the arrow keys, Home and End;
- **Show table** (accessible data table), **CSV** and **Image** (PNG) export.

## How history is kept
Raw chat and moderation rows are pruned after `CHAT_RETENTION_DAYS` (now **90**, was 14) and `ACTION_RETENTION_DAYS` (now **365**, was 90). Before anything is pruned, every finished UTC day is summed into two small tables, `stats_hourly` and `stats_daily`, which are **never** deleted. A day is a few rows, so years of history cost almost nothing.

- **Backfill:** the first start on 1.2.0 sums up all existing days. The prune step can never delete past what has been summed.
- **Today** is computed live from the raw rows, so the newest data is always there.
- Demo and real data are kept apart.
- Days are UTC days, so a day boundary may sit a few hours off your local midnight.
- History from before the old 14-day limit pruned it cannot be recovered.

## API
`GET /api/history?since=&until=&res=auto|hour|day&demo=0|1` and `GET /api/history/storage`.
