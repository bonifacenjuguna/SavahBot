import asyncio

from app.db import Database
from app.store import Store

DAY = 86400.0


def run(coro):
    return asyncio.run(coro)


async def seeded():
    db = Database(":memory:")
    await db.connect()
    s = Store(db)
    for i, ts in enumerate([1000.0, 1000.0 + DAY, 1000.0 + 2 * DAY, 1000.0 + 3 * DAY]):
        await s.create_action({"ts": ts, "platform": "youtube", "author_id": f"a{i}", "author_name": f"user{i}",
                               "action": "timeout", "status": "logged", "text": f"msg{i}", "score": 10})
    return s


def test_history_since_is_inclusive_and_until_is_exclusive():
    async def go():
        s = await seeded()
        assert len(await s.action_history()) == 4
        got = await s.action_history(since=1000.0 + DAY, until=1000.0 + 3 * DAY)
        assert sorted(a["body"] for a in got) == ["msg1", "msg2"]            # [since, until)
        assert [a["body"] for a in await s.action_history(since=1000.0 + 3 * DAY)] == ["msg3"]
        assert [a["body"] for a in await s.action_history(until=1000.0)] == []
        assert len(await s.action_history(since=1000.0, until=1000.0 + 4 * DAY, status="logged")) == 4
        assert await s.action_history(since=1000.0, status="rejected") == []
    run(go())
