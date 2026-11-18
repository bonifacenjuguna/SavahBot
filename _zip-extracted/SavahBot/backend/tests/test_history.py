"""Roll-ups: totals must match the raw rows, survive pruning, and the live tail must fill in the unfinished day."""
import asyncio

from helpers import build_stack
from app.history import DAY, HOUR, Rollups, aggregate
from test_api import e2e

T0 = 1_700_000_000 - (1_700_000_000 % DAY)  # a UTC midnight


async def put_chat(s, ts, author="a", verdict="allow", demo=0, level="everyone"):
    await s.db.execute("INSERT INTO chat_messages (platform, msg_id, author_id, author_name, body, level, ts, score, verdict, demo) VALUES ('demo','',?,?,?,?,?,0,?,?)",
                       (author, author, "hi", level, ts, verdict, demo))


async def put_action(s, ts, action="delete", status="executed", demo=0):
    await s.db.execute("INSERT INTO mod_actions (ts, platform, author_id, author_name, action, status, demo) VALUES (?, 'demo','a','a',?,?,?)", (ts, action, status, demo))


def test_aggregate_counts_people_actions_and_ignores_bots_and_unexecuted():
    chat = [{"ts": 10, "author_id": "a", "level": "everyone", "verdict": "allow", "demo": 0}, {"ts": 20, "author_id": "a", "level": "everyone", "verdict": "delete", "demo": 0},
            {"ts": 30, "author_id": "b", "level": "everyone", "verdict": "allow", "demo": 0}, {"ts": 40, "author_id": "bot", "level": "bot", "verdict": "allow", "demo": 0}]
    acts = [{"ts": 25, "action": "delete", "status": "executed", "demo": 0}, {"ts": 26, "action": "ban", "status": "failed", "demo": 0}, {"ts": 27, "action": "timeout", "status": "simulated", "demo": 0}]
    out = aggregate(chat, acts, HOUR)[(0, 0)]
    assert out == {"messages": 3, "flagged": 1, "chatters": 2, "deleted": 1, "timeouts": 1, "bans": 0}


def test_rollup_backfill_series_and_safe_pruning():
    async def go():
        s = await build_stack()
        r = Rollups(s.db)
        for i in range(5):                                   # day 0: 5 messages by 2 people, 1 flagged, 1 delete
            await put_chat(s, T0 + 100 + i * 60, author="ab"[i % 2], verdict="delete" if i == 0 else "allow")
        await put_action(s, T0 + 150)
        await put_chat(s, T0 + DAY + 5)                      # day 1
        now = T0 + DAY + HOUR                                # day 1 is still unfinished
        assert await r.run(now) == 1 and r.rolled_until == T0 + DAY
        assert await r.run(now) == 0                         # idempotent
        # prune raw rows older than a day: totals must not change, because they were summed first
        await s.store.purge(r.safe_cutoff(now), r.safe_cutoff(now))
        await s.db.execute("DELETE FROM chat_messages WHERE ts < ?", (T0 + DAY,))
        out = await r.series(T0, now, "day", now=now)
        pts = {p["t"]: p for p in out["points"]}
        assert pts[T0]["messages"] == 5 and pts[T0]["chatters"] == 2 and pts[T0]["flagged"] == 1 and pts[T0]["deleted"] == 1
        assert pts[T0 + DAY]["messages"] == 1                # the unfinished day comes from the live rows
        hourly = await r.series(T0, T0 + DAY, "hour", now=now)
        assert sum(p["messages"] for p in hourly["points"]) == 5 and len(hourly["points"]) == 24
        assert (await r.series(T0, now, "auto", now=now))["res"] == "hour"
        assert (await r.storage(now))["daily"]["rows"] == 1
        # a cutoff never passes what has been rolled up
        assert r.safe_cutoff(now + 10 * DAY) == r.rolled_until
    asyncio.run(go())


def test_demo_data_is_kept_apart():
    async def go():
        s = await build_stack()
        r = Rollups(s.db)
        await put_chat(s, T0 + 5, demo=1)
        await put_chat(s, T0 + 6, demo=0)
        await r.run(T0 + 2 * DAY)
        real = await r.series(T0, T0 + DAY, "day", demo=False, now=T0 + 2 * DAY)
        demo = await r.series(T0, T0 + DAY, "day", demo=True, now=T0 + 2 * DAY)
        assert real["points"][0]["messages"] == 1 and demo["points"][0]["messages"] == 1
    asyncio.run(go())


@e2e
async def test_history_api(api):
    assert (await api.call("GET", "/api/history", auth=False))[0] == 401
    st, r = await api.call("GET", "/api/history?res=hour")
    assert st == 200 and r["res"] == "hour" and len(r["points"]) >= 168
    assert (await api.call("GET", "/api/history?since=5&until=1"))[0] == 400
    assert (await api.call("GET", "/api/history?since=abc"))[0] == 400
    st, s = await api.call("GET", "/api/history/storage")
    assert st == 200 and s["retention"]["chat_days"] == 90
