# Redis (optional, 1.1.8)

SavahBot works without Redis, exactly as before. Add it when you want the bot to remember more and to survive restarts and redeploys without losing its footing.

## Turn it on

1. In Railway, add a **Redis** service to the project.
2. In the SavahBot backend service, add a variable `REDIS_URL` and use Railway's reference to the Redis service's `REDIS_URL`.
3. Redeploy. The start-up log says `Redis: connected` and the logs show `leader` or `standby`.

`GET /api/status` (signed in) shows `redis: { mode, leader, snapshot }`. `mode` is `off`, `redis` or `unreachable`.
Nothing else needs configuring. Optional tuning variables: `REDIS_PREFIX`, `REDIS_SNAPSHOT_SECONDS`, `REDIS_LEADER_TTL_SECONDS`, `SHARED_CACHE_SECONDS`, `REDIS_TIMEOUT_SECONDS`.

## What it does

| # | Feature | What changes |
|---|---------|--------------|
| 1 | **Moderation memory** | Message rates, repeated and near-identical messages, repeat-offender strikes and posting rhythm are saved every 10 s and when the bot shuts down. After a redeploy the bot restores them, so a spammer is not "new" again. |
| 2 | **Login lockout** | Failed sign-ins (dashboard and Telegram `/claim`) are counted in Redis. A restart no longer clears a lockout. |
| 3 | **Live events across instances** | Chat, moderation and stream events are published to every backend instance, so every open dashboard sees them. |
| 4 | **One leader** | Only one instance polls YouTube, runs timers and reminders, and polls Telegram. If it stops, another takes over in about 30 s. The others stay on standby. |
| 5 | **Dashboard cache** | Heavy queries (Insights) are reused for 15 s by every dashboard and instance. |
| 6 | **Cooldowns and duplicates** | Command and auto-reply cooldowns and "just punished" markers survive restarts. A live message id is claimed once, so a restart or hand-over never moderates or answers the same message twice. |

## If Redis goes away

The bot never stops because of Redis. Errors are caught, the bot carries on in memory, and it retries every 15 s. A wrong password or address shows as `unreachable` in the status and in the logs.
During an outage each instance acts as its own leader, which is correct for the usual single instance.

## Good to know

- Everything is saved under one prefix (default `savahbot:`), so a Redis shared with other apps is fine. The saved state is a single compressed key that expires after 6 hours.
- Redis is a helper, not a database: chats, actions, settings and commands stay in your normal database.
- Run several instances only if you need a hot standby. Settings changed on a standby are saved normally, and the leader loads the latest settings when it takes over.
- No `redis` Python package is needed. A small client is built in (`app/shared.py`), so `requirements.txt` is unchanged.
