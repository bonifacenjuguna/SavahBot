"""1.1.1: mode isolation, timer triggers, blocked-phrase library, notifications, auto-reply foundation."""
import asyncio

from helpers import build_stack, events

from app.autoreply import find_reply, test_message as match_report, trigger_matches
from app.models import ChatMessage
from app.services.scheduler import Scheduler
from app.store import ValidationFailed


def run(coro):
    return asyncio.run(coro)


async def raises(exc, coro):
    try:
        await coro
    except exc:
        return True
    raise AssertionError(f"expected {exc.__name__}")


def live(text, name="bob", ts=1_000_000.0):
    return ChatMessage("youtube", name.lower(), name, text, ts=ts, msg_id=f"y-{name}-{ts}", demo=False)


# ------------------------------------------------------------------------------------------ mode isolation
def test_state_is_one_value_and_follows_mode_and_stream():
    async def go():
        s = await build_stack()
        assert s.hub.state == "demo" and s.hub.status()["state"] == "demo"
        s.cfg.set("bot_mode", "live")
        await s.hub.apply_mode()
        assert s.hub.state == "standby" and s.hub.status()["mode"] == "live"      # live selected, no stream yet
        s.hub.stream_state(True, "Real stream")
        assert s.hub.state == "live"
        s.cfg.set("bot_mode", "demo")
        await s.hub.apply_mode()
        assert s.hub.state == "demo"
    run(go())


def test_switching_mode_resets_session_lines():
    async def go():
        s = await build_stack()
        s.hub.lines = 42
        s.cfg.set("bot_mode", "live")
        await s.hub.apply_mode()
        assert s.hub.lines == 0
    run(go())


def test_store_reads_are_scoped_by_demo_flag():
    async def go():
        s = await build_stack()
        base = {"ts": 1.0, "platform": "x", "author_id": "a", "author_name": "A", "text": "t", "action": "delete", "status": "pending"}
        await s.store.create_action(base | {"demo": True})
        await s.store.create_action(base | {"demo": False, "author_id": "b"})
        assert len(await s.store.pending_actions(True)) == 1 and len(await s.store.pending_actions(False)) == 1
        assert len(await s.store.pending_actions()) == 2
        assert [a["demo"] for a in await s.store.action_history(10, None, False)] == [False]
        assert len(await s.store.flagged_actions(10, True)) == 1
        await s.store.add_chat({"platform": "demo", "author_id": "a", "author_name": "A", "text": "d", "ts": 1.0, "demo": True})
        await s.store.add_chat({"platform": "youtube", "author_id": "b", "author_name": "B", "text": "l", "ts": 2.0, "demo": False})
        assert [m["body"] for m in await s.store.recent_chat(10, False)] == ["l"]
        assert [m["body"] for m in await s.store.recent_chat(10, True)] == ["d"]
    run(go())


def test_approve_all_only_touches_the_active_mode():
    async def go():
        s = await build_stack()
        base = {"ts": 1.0, "platform": "x", "author_id": "a", "author_name": "A", "text": "t", "action": "delete", "status": "pending"}
        await s.store.create_action(base | {"demo": True})
        live_id = await s.store.create_action(base | {"demo": False, "author_id": "b"})
        await s.hub.resolve_all(False, True)
        assert [a["id"] for a in await s.store.pending_actions()] == [live_id]       # the live request was left alone
    run(go())


# ------------------------------------------------------------------------------------------ timers
def timer(**kw):
    return {"id": 1, "kind": "recurring", "interval_seconds": 0, "min_lines": 0, "trigger_mode": "all", "done": False, "run_at": None, **kw}


def test_timer_trigger_semantics():
    due = Scheduler.timer_due
    assert due(timer(interval_seconds=600), 700, 0, 0) and not due(timer(interval_seconds=600), 500, 0, 99)    # time only
    assert due(timer(min_lines=5), 100, 0, 5) and not due(timer(min_lines=5), 100, 0, 4)                        # lines only
    both = timer(interval_seconds=600, min_lines=5)
    assert due(both, 700, 0, 5) and not due(both, 700, 0, 4) and not due(both, 500, 0, 9)                        # all: both needed
    either = both | {"trigger_mode": "any"}
    assert due(either, 700, 0, 0) and due(either, 100, 0, 5) and not due(either, 100, 0, 4)                      # any: one is enough
    assert not due(timer(min_lines=1), 30, 0, 50)                                                                # 60 s floor stops spam
    assert not due(timer(), 9999, 0, 9999)                                                                       # no trigger never fires


def test_one_time_timer_semantics():
    due = Scheduler.timer_due
    assert due(timer(kind="once"), 5, 0, 0) and due(timer(kind="once", run_at=100.0), 100, 0, 0)
    assert not due(timer(kind="once", run_at=100.0), 99, 0, 0) and not due(timer(kind="once", done=True), 5, 0, 0)


def test_timer_validation_rules():
    async def go():
        s = await build_stack(seed=False)
        await raises(ValidationFailed, s.store.create_timer("a", "msg", 0, 0))              # recurring needs a trigger
        await raises(ValidationFailed, s.store.create_timer("a", "msg", 30, 0))             # too short
        await raises(ValidationFailed, s.store.create_timer("a", "  ", 600, 0))
        await raises(ValidationFailed, s.store.create_timer("a", "msg", 600, 0, kind="weekly"))
        t1 = await s.store.create_timer("time-only", "m", 600, 0)
        t2 = await s.store.create_timer("lines-only", "m", 0, 10)
        t3 = await s.store.create_timer("once", "m", 0, 0, kind="once")                         # one-time needs no trigger
        assert {t["name"]: (t["interval_seconds"], t["min_lines"], t["kind"]) for t in await s.store.list_timers()} == {
            "time-only": (600, 0, "recurring"), "lines-only": (0, 10, "recurring"), "once": (0, 0, "once")}
        await raises(ValidationFailed, s.store.update_timer(t1, interval_seconds=0))        # would leave no trigger
        assert await s.store.update_timer(t1, min_lines=3) and await s.store.update_timer(t1, interval_seconds=0)
        await raises(ValidationFailed, s.store.create_timer("lines-only", "m", 600, 0))     # duplicate name
        assert t2 and t3
    run(go())


def test_once_timer_posts_once_then_switches_off_and_logs_history():
    async def go():
        s = await build_stack(seed=False)
        tid = await s.store.create_timer("hello", "Welcome everyone!", kind="once", enabled=True)
        s.scheduler._started = 0.0
        await s.scheduler.tick(now=100.0)
        await s.scheduler.tick(now=200.0)
        assert [m["text"] for m in s.hub.buffer if m["from_bot"]] == ["Welcome everyone!"]
        t = await s.store.get_timer(tid)
        assert t["done"] is True and t["enabled"] is False and t["fired"] == 1
        runs = await s.store.timer_runs(tid)
        assert len(runs) == 1 and runs[0]["ok"] is True and runs[0]["demo"] is True
        assert await s.store.update_timer(tid, enabled=True)                                  # re-enabling re-arms it
        assert (await s.store.get_timer(tid))["done"] is False
    run(go())


def test_lines_only_recurring_timer_and_progress():
    async def go():
        s = await build_stack(seed=False)
        tid = await s.store.create_timer("chatty", "Thanks for chatting!", 0, 3, enabled=True)
        s.scheduler._started = 0.0
        await s.scheduler.tick(now=100.0)                      # records the baseline
        assert s.scheduler.progress(await s.store.get_timer(tid), 100.0)["lines_needed"] == 3
        for i in range(3):
            await s.hub.ingest(live(f"hi {i}", f"v{i}", 5_000_000.0 + i).__class__("demo", f"v{i}", f"V{i}", f"hi {i}", ts=5_000_000.0 + i, msg_id=f"m{i}", demo=True))
        await s.scheduler.tick(now=200.0)
        assert len([m for m in s.hub.buffer if m["from_bot"]]) == 1
    run(go())


# ------------------------------------------------------------------------------------------ library
def test_blocked_phrase_import_preview_dedupe_validate_and_bulk():
    async def go():
        s = await build_stack(seed=False)
        await s.store.add_blacklist("existing")
        items = [{"phrase": "free robux"}, {"phrase": "Existing"}, {"phrase": "free robux"}, {"phrase": ""},
                 {"phrase": "(", "is_regex": True}, {"phrase": "x", "weight": 500}, {"phrase": "ok", "category": "nope"}, {"phrase": "buy followers", "category": "spam"}]
        plan = await s.store.preview_blacklist_import(items)
        assert [i["phrase"] for i in plan["new"]] == ["free robux", "buy followers"]
        assert len(plan["duplicates"]) == 2 and len(plan["invalid"]) == 4
        assert len(await s.store.list_blacklist()) == 1                                         # preview wrote nothing
        res = await s.store.import_blacklist(items)
        assert res["added"] == 2 and res["duplicates"] == 2
        ids = [b["id"] for b in await s.store.list_blacklist()]
        assert await s.store.bulk_blacklist(ids, "disable") == 3
        assert all(not b["enabled"] for b in await s.store.list_blacklist())
        assert await s.store.bulk_blacklist(ids[:1], "move", "spam") == 1
        assert await s.store.bulk_blacklist(ids, "delete") == 3 and await s.store.list_blacklist() == []
    run(go())


# ------------------------------------------------------------------------------------------ notifications
def test_notifications_are_separate_scoped_and_markable():
    async def go():
        s = await build_stack()
        drain = events(s)
        await s.hub.notice("timer", "Timer failed", "reason", "warning")                        # demo mode
        s.cfg.set("bot_mode", "live")
        await s.hub.apply_mode()
        await s.hub.notice("stream", "Stream is live")
        assert [n["title"] for n in await s.store.list_notifications(10, False) if n["kind"] == "stream"] == ["Stream is live"]
        assert [n["kind"] for n in await s.store.list_notifications(10, True)] == ["timer"]
        assert await s.store.unread_notifications(False) >= 1
        await s.store.mark_notifications_read(None, False)
        assert await s.store.unread_notifications(False) == 0 and await s.store.unread_notifications(True) == 1
        assert any(e["type"] == "notification" for e in drain())
        assert await s.store.clear_notifications(True) == 1
    run(go())


# ------------------------------------------------------------------------------------------ auto reply foundation
def test_auto_reply_matching_and_rules():
    assert trigger_matches("How do I join?", "how do i join", "phrase")
    assert not trigger_matches("rules", "what are the rules?", "phrase")
    assert trigger_matches("rules", "what are the rules?", "word") and not trigger_matches("rule", "what are the rules?", "word")
    assert trigger_matches("rule", "what are the rules?", "contains")
    assert not trigger_matches("Rules", "rules", "phrase", case_sensitive=True)
    rules = [
        {"id": 1, "name": "join", "triggers": ["how do i join"], "responses": ["Use the link."], "match_type": "phrase", "enabled": True, "priority": 50},
        {"id": 2, "name": "off", "triggers": ["how do i join"], "responses": ["x"], "match_type": "phrase", "enabled": False, "priority": 1},
    ]
    assert find_reply(rules, "How do I join?")["reply"] == "Use the link."            # disabled rules never answer
    assert [m["name"] for m in match_report(rules, "How do I join?")] == ["off", "join"]  # the tester still shows them


def test_auto_reply_store_validation_and_duplicates():
    async def go():
        s = await build_stack(seed=False)
        await raises(ValidationFailed, s.store.create_auto_reply("n", [], ["r"]))
        await raises(ValidationFailed, s.store.create_auto_reply("n", ["t"], []))
        await raises(ValidationFailed, s.store.create_auto_reply("n", ["t"], ["r"], match_type="regex"))
        rid = await s.store.create_auto_reply("join", ["How do I join?", "how do i join?"], ["Use the link."])
        (rule,) = await s.store.list_auto_replies()
        assert rule["triggers"] == ["How do I join?"] or len(rule["triggers"]) == 2
        assert rule["enabled"] is False                                                   # saved rules start off
        await raises(ValidationFailed, s.store.create_auto_reply("again", ["HOW DO I JOIN?"], ["x"]))
        assert await s.store.update_auto_reply(rid, enabled=True, responses=["a", "b"])
        assert (await s.store.list_auto_replies())[0]["responses"] == ["a", "b"]
        assert await s.store.delete_auto_reply(rid)
    run(go())
