import asyncio
import json

import pytest

from app.config import Settings
from app.db import Database
from app.runtime_config import RuntimeConfig, is_secret
from app.security import OwnerAuth
from app.store import Store, ValidationFailed


def run(coro):
    return asyncio.run(coro)


async def make_store():
    db = Database(":memory:")
    await db.connect()
    return db, Store(db)


def test_db_kv_and_backend():
    async def go():
        db = Database(":memory:")
        await db.connect()
        assert db.backend == "sqlite"
        assert await db.kv_get("a") is None
        await db.kv_set("a", "1")
        await db.kv_set("a", "2")
        assert await db.kv_get("a") == "2"
        await db.kv_delete("a")
        assert await db.kv_get("a", "dflt") == "dflt"
        await db.close()
    run(go())


def test_postgres_placeholder_rewrite():
    from app.db import _Postgres
    assert _Postgres._q("SELECT * FROM t WHERE a = ? AND b = ?") == "SELECT * FROM t WHERE a = $1 AND b = $2"
    assert Database("postgresql://u:p@h/db").backend == "postgres"
    assert Database("postgres://u:p@h/db").backend == "postgres"


def test_runtime_config_precedence_validation_and_listeners():
    async def go():
        db, _ = await make_store()
        rc = RuntimeConfig(Settings(env={"MOD_SCORE_DELETE": "60"}, env_file=None), db)
        seen = []
        rc.on_change(lambda n, v: seen.append((n, v)))
        assert rc.get("mod_score_delete") == 60  # env beats default
        await rc.set("mod_score_delete", "75")
        assert rc.get("mod_score_delete") == 75 and seen == [("mod_score_delete", 75)]
        with pytest.raises(PermissionError):
            await rc.set("telegram_bot_token", "x")
        with pytest.raises(ValueError):
            await rc.set("mod_mode", "chaos")
        with pytest.raises(KeyError):
            await rc.set("nope", 1)
        # persisted across a "restart"
        rc2 = RuntimeConfig(Settings(env={"MOD_SCORE_DELETE": "60"}, env_file=None), db)
        await rc2.load()
        assert rc2.get("mod_score_delete") == 75
        assert await rc2.reset("mod_score_delete") == 60
        await rc2.set("mod_caps_enabled", False)
        rc3 = RuntimeConfig(Settings(env={}, env_file=None), db)
        await rc3.load()
        assert rc3.get("mod_caps_enabled") is False
    run(go())


def test_snapshot_never_leaks_secrets():
    rc = RuntimeConfig(Settings(env={"TELEGRAM_BOT_TOKEN": "123:SECRET", "OWNER_PASSWORD": "hunter2",
                                     "DATABASE_URL": "postgres://u:pw@h/d"}, env_file=None))
    snap = {s["name"]: s for s in rc.snapshot()}
    blob = json.dumps(snap)
    for leak in ("123:SECRET", "hunter2", "u:pw@h"):
        assert leak not in blob
    assert snap["telegram_bot_token"]["is_set"] is True and snap["telegram_bot_token"]["value"] is None
    assert snap["owner_password"]["secret"] and snap["database_url"]["secret"]
    assert snap["mod_score_delete"]["value"] == 55 and snap["mod_score_delete"]["editable"]
    assert not is_secret("mod_score_delete") and not is_secret("public_base_url")
    assert rc.requirements_status()["telegram"][0] == {"env": "TELEGRAM_BOT_TOKEN", "set": True}


def test_owner_auth_generates_and_remembers_credentials():
    async def go():
        db, _ = await make_store()
        a = OwnerAuth(Settings(env={}, env_file=None), db)
        await a.init()
        assert a.password_generated
        generated = await db.kv_get("_owner_password")
        assert a.check_password(generated) and not a.check_password("wrong")
        token, ttl = a.issue_token()
        assert a.verify(token) and not a.verify(token + "x") and ttl == 72 * 3600
        b = OwnerAuth(Settings(env={}, env_file=None), db)  # restart: same password and same signing key
        await b.init()
        assert not b.password_generated and b.verify(token)
        c = OwnerAuth(Settings(env={"OWNER_PASSWORD": "mine"}, env_file=None), db)
        await c.init()
        assert c.check_password("mine") and not c.check_password(generated)
    run(go())


def test_commands_crud_aliases_and_validation():
    async def go():
        _, s = await make_store()
        cid = await s.create_command("!Hello", "Hi $(user)", aliases=["hi", "hey"])
        assert (await s.find_command("hello"))["id"] == cid
        assert (await s.find_command("hey"))["id"] == cid
        assert (await s.get_command(cid))["aliases"] == ["hi", "hey"]
        with pytest.raises(ValidationFailed):
            await s.create_command("hello", "dup")
        with pytest.raises(ValidationFailed):
            await s.create_command("bad name!", "x")
        with pytest.raises(ValidationFailed):
            await s.create_command("ok", "   ")
        with pytest.raises(ValidationFailed):
            await s.create_command("lvl", "x", userlevel="god")
        assert await s.update_command(cid, response="Yo", enabled=False)
        c = await s.get_command(cid)
        assert c["response"] == "Yo" and c["enabled"] is False
        await s.bump_command(cid)
        assert (await s.get_command(cid))["uses"] == 1
        assert await s.delete_command(cid) and not await s.delete_command(cid)
    run(go())


def test_timers_quotes_regulars_notes():
    async def go():
        _, s = await make_store()
        with pytest.raises(ValidationFailed):
            await s.create_timer("t", "msg", 10)
        tid = await s.create_timer("socials", "Follow me", 600, 3)
        await s.mark_timer_fired(tid, 123.0)
        t = (await s.list_timers())[0]
        assert t["last_fired"] == 123.0 and t["fired"] == 1 and t["enabled"] is True

        q1 = await s.add_quote("first")
        await s.add_quote("second", "me")
        assert (await s.quote_number(2))["body"] == "second" and await s.quote_number(3) is None
        assert (await s.random_quote())["body"] in ("first", "second")
        assert await s.delete_quote(q1)

        await s.add_regular("@Alice", "Alice")
        assert s.is_regular("alice") and s.is_regular("zzz", "ALICE") and not s.is_regular("bob")
        rid = (await s.list_regulars())[0]["id"]
        await s.delete_regular(rid)
        assert not s.is_regular("alice")

        n1 = await s.add_note("old", ["a"])
        await s.add_note("pinned one", pinned=True)
        notes = await s.list_notes()
        assert notes[0]["pinned"] is True and notes[1]["tags"] == ["a"]
        await s.update_note(n1, body="edited", tags=["x", "y"])
        assert [n for n in await s.list_notes() if n["id"] == n1][0]["tags"] == ["x", "y"]
    run(go())


def test_blacklist_validation_and_hits():
    async def go():
        _, s = await make_store()
        with pytest.raises(ValidationFailed):
            await s.add_blacklist("([", is_regex=True)
        with pytest.raises(ValidationFailed):
            await s.add_blacklist("x", weight=500)
        bid = await s.add_blacklist("free robux", weight=80)
        with pytest.raises(ValidationFailed):
            await s.add_blacklist("free robux")
        await s.bump_blacklist([bid, bid])
        e = (await s.list_blacklist())[0]
        assert e["hits"] == 2 and e["enabled"] is True and e["is_regex"] is False
        await s.update_blacklist(bid, enabled=False)
        assert (await s.list_blacklist())[0]["enabled"] is False
    run(go())


def test_reminders_lifecycle():
    async def go():
        _, s = await make_store()
        a = await s.add_reminder("soon", 100.0)
        b = await s.add_reminder("later", 900.0, "daily")
        assert [r["id"] for r in await s.due_reminders(500.0)] == [a]
        await s.finish_reminder(a, 500.0)
        assert await s.due_reminders(500.0) == []
        await s.reschedule_reminder(b, 2000.0, 1000.0)
        assert (await s.list_reminders("pending"))[0]["due"] == 2000.0
        assert await s.cancel_reminder(b) and not await s.cancel_reminder(b)
        assert len(await s.list_reminders(None)) == 2
    run(go())


def test_chat_actions_counters_quota_and_purge():
    async def go():
        _, s = await make_store()
        for i in range(5):
            await s.add_chat({"platform": "demo", "author_id": "u", "author_name": "U", "text": f"m{i}", "ts": 100.0 + i, "demo": i < 3})
        assert [m["body"] for m in await s.recent_chat(3)] == ["m2", "m3", "m4"]
        await s.clear_demo_data()
        assert [m["body"] for m in await s.recent_chat(10)] == ["m3", "m4"]

        aid = await s.create_action({"ts": 1000.0, "platform": "youtube", "author_id": "x", "author_name": "X", "action": "timeout",
                                     "duration": 60, "score": 95, "reasons": ["blacklist: scam"], "status": "pending", "message_ids": ["m1"]})
        got = await s.get_action(aid)
        assert got["reasons"] == ["blacklist: scam"] and got["message_ids"] == ["m1"] and got["demo"] is False
        assert (await s.pending_for_author("youtube", "x"))["id"] == aid
        assert await s.pending_for_author("youtube", "other") is None
        await s.update_action(aid, message_ids=["m1", "m2"], score=100)
        assert (await s.get_action(aid))["message_ids"] == ["m1", "m2"]
        assert await s.expire_pending(2000.0) == 1
        assert (await s.get_action(aid))["status"] == "expired" and await s.pending_actions() == []

        assert await s.counter_add("c") == 1 and await s.counter_add("c", 4) == 5 and await s.counter_get("none") == 0
        assert await s.quota_add("2026-11-02", 5) == 5 and await s.quota_add("2026-11-02", 20) == 25
        await s.purge(chat_before=104.0, actions_before=5000.0)
        assert [m["body"] for m in await s.recent_chat(10)] == ["m4"]
        assert await s.action_history() == []
    run(go())
