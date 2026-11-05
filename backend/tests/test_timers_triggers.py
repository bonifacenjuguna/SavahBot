import asyncio
import sqlite3

import pytest
from helpers import build_stack

from app.commands.triggers import matches
from app.db import Database
from app.models import ChatMessage
from app.services.scheduler import Scheduler
from app.store import Store, ValidationFailed


def run(coro):
    return asyncio.run(coro)


def chat(text, name="alice", level="everyone", ts=5_000_000.0, **kw):
    return ChatMessage("demo", name.lower(), name, text, level, ts=ts, msg_id=f"m-{name}-{ts}", demo=True, **kw)


async def make_store():
    db = Database(":memory:")
    await db.connect()
    return Store(db)


# ------------------------------------------------------------------ timers: time and lines are each optional
def test_timer_needs_a_time_or_lines_or_both():
    async def go():
        s = await make_store()
        with pytest.raises(ValidationFailed):
            await s.create_timer("none", "hi", 0, 0)
        with pytest.raises(ValidationFailed):
            await s.create_timer("short", "hi", 30, 0)
        await s.create_timer("time", "hi", 600, 0)
        await s.create_timer("lines", "hi", 0, 20)
        await s.create_timer("both", "hi", 600, 20, match_mode="any", max_runs=3)
        t = {x["name"]: x for x in await s.list_timers()}
        assert (t["time"]["interval_seconds"], t["time"]["min_lines"]) == (600, 0)
        assert (t["lines"]["interval_seconds"], t["lines"]["min_lines"]) == (0, 20)
        assert t["both"]["match_mode"] == "any" and t["both"]["max_runs"] == 3
        with pytest.raises(ValidationFailed):          # switching both off at once is refused
            await s.update_timer(t["both"]["id"], interval_seconds=0, min_lines=0)
        assert await s.update_timer(t["both"]["id"], interval_seconds=0)   # lines alone is fine
        assert not await s.update_timer(9999, enabled=True)
    run(go())


def test_timer_due_rules():
    due = Scheduler.timer_due
    base = {"last_fired": 0, "interval_seconds": 600, "min_lines": 10, "match_mode": "all"}
    assert due(base | {"min_lines": 0}, 700, 0, 0)                      # time only
    assert not due(base | {"min_lines": 0}, 500, 0, 99)
    assert due(base | {"interval_seconds": 0}, 1, 0, 10)                # lines only, any time
    assert not due(base | {"interval_seconds": 0}, 9999, 0, 9)
    assert not due(base, 700, 0, 3) and not due(base, 100, 0, 50) and due(base, 700, 0, 10)   # both needed
    assert due(base | {"match_mode": "any"}, 700, 0, 3) and due(base | {"match_mode": "any"}, 100, 0, 50)
    assert not due(base | {"match_mode": "any"}, 100, 0, 3)


def test_post_once_timer_switches_itself_off_and_counts_again_when_enabled():
    async def go():
        s = await build_stack()
        tid = (await s.store.list_timers())[0]["id"]
        await s.store.update_timer(tid, enabled=True, interval_seconds=0, min_lines=2, max_runs=1)
        s.scheduler._started = 0.0
        await s.scheduler.tick(now=100.0)                       # baseline
        for i in range(2):
            await s.hub.ingest(chat(f"chatting {'ab'[i]}", f"v{i}", ts=5_000_000.0 + i))
        await s.scheduler.tick(now=200.0)
        t = (await s.store.list_timers())[0]
        assert t["fired"] == 1 and t["enabled"] is False        # posted once, then off
        await s.store.update_timer(tid, enabled=True)
        assert (await s.store.list_timers())[0]["runs"] == 0    # a new run starts from zero
    run(go())


# ------------------------------------------------------------------ old databases are upgraded
def test_old_timers_table_gets_new_columns(tmp_path):
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE timers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, message TEXT NOT NULL,
        interval_seconds INTEGER NOT NULL, min_lines INTEGER NOT NULL DEFAULT 5, enabled INTEGER NOT NULL DEFAULT 1,
        last_fired REAL NOT NULL DEFAULT 0, fired INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL)""")
    con.execute("INSERT INTO timers (name, message, interval_seconds, min_lines, created) VALUES ('old', 'hi', 900, 4, 1)")
    con.commit()
    con.close()

    async def go():
        db = Database(path)
        await db.connect()
        await db.connect()                                       # running twice is harmless
        t = (await Store(db).list_timers())[0]
        assert t["match_mode"] == "all" and t["max_runs"] == 0 and t["runs"] == 0 and t["interval_seconds"] == 900
        await db.close()
    run(go())


# ------------------------------------------------------------------ auto-replies
def test_trigger_matching():
    exact = {"phrase": "gm", "match_type": "exact"}
    assert matches(exact, "GM") and matches(exact, "  gm  ") and not matches(exact, "gm chat") and not matches(exact, "")
    word = {"phrase": "discord", "match_type": "word"}
    assert matches(word, "is there a Discord?") and matches(word, "discord") and not matches(word, "discordant")
    two = {"phrase": "good  morning", "match_type": "word"}
    assert matches(two, "well GOOD morning everyone")


def test_trigger_store_rules():
    async def go():
        s = await make_store()
        a = await s.create_trigger("GM", "Good morning!")
        with pytest.raises(ValidationFailed):
            await s.create_trigger(" gm ", "again")             # same phrase, ignoring case and spaces
        await s.create_trigger("gm", "word version", match_type="word")   # a different match type is allowed
        with pytest.raises(ValidationFailed):
            await s.create_trigger("x", "y", match_type="regex")
        with pytest.raises(ValidationFailed):
            await s.create_trigger("   ", "y")
        assert [t["id"] for t in await s.enabled_triggers()][0] in (a, a + 1)
        await s.update_trigger(a, enabled=False)
        assert all(t["id"] != a for t in await s.enabled_triggers())   # cache refreshed
        assert await s.delete_trigger(a) and not await s.delete_trigger(a)
    run(go())


def test_trigger_replies_end_to_end():
    async def go():
        s = await build_stack()
        await s.store.create_trigger("gm", "Good morning!", cooldown=0, user_cooldown=0)
        await s.store.create_trigger("discord", "Join us: discord.example", match_type="word", mention=False, cooldown=0, user_cooldown=0)
        await s.store.create_trigger("mods only", "secret", userlevel="mod", cooldown=0, user_cooldown=0)
        bot = lambda: [m["text"] for m in s.hub.buffer if m["from_bot"]]
        await s.hub.ingest(chat("GM", "Ann"))
        assert bot() == ["@Ann Good morning!"]
        await s.hub.ingest(chat("gm everyone", "Bob", ts=5_000_001.0))      # exact needs the whole message
        assert len(bot()) == 1
        await s.hub.ingest(chat("anyone have the Discord link?", "Cy", ts=5_000_002.0))
        assert bot()[-1] == "Join us: discord.example"
        await s.hub.ingest(chat("mods only", "Dee", ts=5_000_003.0))         # level too low
        assert len(bot()) == 2
        await s.hub.ingest(chat("!hello", "Eve", ts=5_000_004.0))            # commands are never treated as triggers
        assert "Hello" in bot()[-1] and len(bot()) == 3
    run(go())


def test_trigger_cooldown_and_switch():
    async def go():
        s = await build_stack()
        await s.store.create_trigger("gm", "Good morning!", cooldown=300, user_cooldown=300)
        bot = lambda: [m for m in s.hub.buffer if m["from_bot"]]
        await s.hub.ingest(chat("gm", "Ann"))
        await s.hub.ingest(chat("gm", "Ann", ts=5_000_001.0))
        await s.hub.ingest(chat("gm", "Bob", ts=5_000_002.0))                # global cooldown
        assert len(bot()) == 1
        s.cfg.set("triggers_enabled", False)
        s2 = await build_stack({"triggers_enabled": False})
        await s2.store.create_trigger("gm", "hi", cooldown=0, user_cooldown=0)
        await s2.hub.ingest(chat("gm", "Ann"))
        assert [m for m in s2.hub.buffer if m["from_bot"]] == []
    run(go())
