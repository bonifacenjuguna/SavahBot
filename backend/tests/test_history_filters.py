"""1.1.2: moderation history and stored chat can be filtered by date range and text."""
import asyncio

from app.db import Database
from app.store import Store

DAY = 86400.0
T0 = 1_800_000_000.0


def run(coro):
    return asyncio.run(coro)


async def seeded():
    db = Database(":memory:")
    await db.connect()
    store = Store(db)
    for i, (who, body, verdict) in enumerate([("ann", "hello there", "allow"), ("bob", "100% free stuff", "flag"), ("cy", "buy now", "delete"), ("ann", "late message", "allow")]):
        await store.add_chat({"platform": "youtube", "author_id": who, "author_name": who, "text": body, "ts": T0 + i * DAY, "verdict": verdict})
    for i, (who, action, status) in enumerate([("bob", "delete", "executed"), ("cy", "timeout", "rejected"), ("dee", "ban", "executed")]):
        await store.create_action({"ts": T0 + i * DAY, "platform": "youtube", "author_id": who, "author_name": who, "message_ids": [],
                                   "action": action, "text": f"spam from {who}", "duration": None, "score": 5, "reasons": ["link"], "status": status, "mode": "auto", "demo": False})
    return store


def test_action_history_date_range_text_and_paging():
    async def go():
        s = await seeded()
        assert len(await s.action_history(50)) == 3
        assert [a["author_name"] for a in await s.action_history(50, since=T0 + DAY)] == ["dee", "cy"]
        assert [a["author_name"] for a in await s.action_history(50, until=T0 + DAY)] == ["bob"]          # until is exclusive
        assert [a["author_name"] for a in await s.action_history(50, since=T0 + 0.5 * DAY, until=T0 + 1.5 * DAY)] == ["cy"]
        assert [a["author_name"] for a in await s.action_history(50, q="TIMEOUT")] == ["cy"]
        assert [a["author_name"] for a in await s.action_history(50, status="executed", since=T0 + DAY)] == ["dee"]
        assert len(await s.action_history(1, offset=1)) == 1 and (await s.action_history(1, offset=1))[0]["author_name"] == "cy"
    run(go())


def test_chat_search_filters_and_treats_wildcards_as_text():
    async def go():
        s = await seeded()
        assert len(await s.search_chat()) == 4
        assert [m["author_name"] for m in await s.search_chat(since=T0 + 2 * DAY)] == ["cy", "ann"]
        assert [m["body"] for m in await s.search_chat(q="100%")] == ["100% free stuff"]
        assert [m["body"] for m in await s.search_chat(q="%")] == ["100% free stuff"]    # a literal percent sign, not "match everything"
        assert [m["body"] for m in await s.search_chat(q="_")] == []                      # a literal underscore
        assert [m["author_name"] for m in await s.search_chat(verdict="flagged")] == ["bob", "cy"]
        assert [m["author_name"] for m in await s.search_chat(verdict="blocked")] == ["cy"]
        assert [m["author_name"] for m in await s.search_chat(q="ann", until=T0 + 2 * DAY)] == ["ann"]
    run(go())
