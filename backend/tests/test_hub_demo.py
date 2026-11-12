import asyncio

from helpers import build_stack, events, summary

from app.models import ChatMessage
from app.seed import seed_defaults


def run(coro):
    return asyncio.run(coro)


def msg(text, name="alice", level="everyone", ts=1_000_000.0, **kw):
    return ChatMessage("demo", name.lower(), name, text, level, ts=ts, msg_id=f"m-{name}-{ts}", demo=True, **kw)


def test_seed_is_idempotent_and_demo_mode_is_live_immediately():
    async def go():
        s = await build_stack()
        assert len(await s.store.list_commands()) == 7 and len(await s.store.list_blacklist()) == 11
        timers = await s.store.list_timers()
        assert len(timers) == 1 and timers[0]["enabled"] is False
        assert await seed_defaults(s.db, s.store) is False
        assert len(await s.store.list_commands()) == 7
        st = s.hub.status()
        assert st["mode"] == "demo" and st["stream_live"] is True and st["source"] == "demo"
        assert s.hub.uptime() is not None
    run(go())


def test_friendly_chat_scenario_flags_nothing():
    async def go():
        s = await build_stack()
        await s.demo.run_scenario("friendly_chat")
        assert len(s.hub.buffer) == 8
        assert all(m["verdict"] == "allow" for m in s.hub.buffer)
        assert await s.store.action_history() == []
    run(go())


def test_raid_in_suggest_mode_queues_pending_deletes_and_notifies():
    async def go():
        s = await build_stack()
        drain = events(s)
        await s.demo.run_scenario("spam_raid")
        pending = await s.store.pending_actions()
        assert len(pending) >= 3 and all(p["action"] == "delete" for p in pending)
        assert all(any(r.startswith("raid") for r in p["reasons"]) for p in pending)
        assert {"mod_pending"} <= {e["type"] for e in drain()}
        assert len(s.notes) == len(pending)  # one approval message each, with buttons
        text, buttons = s.notes[0]
        assert "Approval needed" in text and buttons[0][0][1].startswith("approve:")
        # the offending messages are still shown in the feed, labelled with their verdict
        assert sum(1 for m in s.hub.buffer if m["verdict"] == "delete") == len(pending)
    run(go())


def test_approve_and_reject_flow_with_strikes():
    async def go():
        s = await build_stack()
        await s.demo.run_scenario("link_spammer")
        p = (await s.store.pending_actions())[0]
        assert p["action"] in ("delete", "timeout", "ban")
        res = await s.hub.approve(p["id"])
        assert res == {"ok": True, "status": "simulated", "error": ""}
        assert (await s.store.get_action(p["id"]))["status"] == "simulated"
        assert s.engine.strikes(f"demo:{p['author_id']}") == 1
        assert (await s.hub.approve(p["id"]))["ok"] is False      # cannot approve twice
        assert (await s.hub.reject(p["id"]))["ok"] is False

        await s.demo.run_scenario("link_spammer")
        p2 = (await s.store.pending_actions())[0]
        assert (await s.hub.reject(p2["id"]))["status"] == "rejected"
        assert s.engine.strikes(f"demo:{p2['author_id']}") == 0   # rejected = no strike
    run(go())


def test_link_spam_from_new_account_is_a_ban_candidate():
    async def go():
        s = await build_stack()
        await s.demo.run_scenario("link_spammer")
        p = (await s.store.pending_actions())[0]
        assert p["action"] == "ban" and p["score"] == 100
        assert {r.split(":")[0] for r in p["reasons"]} >= {"blacklist", "link", "new_chatter"}
        assert (await s.store.list_blacklist())[0]["hits"] >= 0
    run(go())


def test_auto_mode_executes_and_bans_wait_unless_listed():
    async def go():
        s = await build_stack({"mod_mode": "auto"})
        await s.demo.run_scenario("link_spammer")            # ban-level: not in mod_auto_actions
        assert [p["action"] for p in await s.store.pending_actions()] == ["ban"]
        await s.demo.run_scenario("disguised_words")          # delete-level: runs by itself
        hist = await s.store.action_history()
        assert any(h["status"] == "simulated" and h["action"] == "delete" for h in hist)
        s.cfg.set("mod_auto_actions", "delete,timeout,ban")
        await s.demo.run_scenario("link_spammer")
        assert any(h["status"] == "simulated" and h["action"] == "ban" for h in await s.store.action_history())
    run(go())


def test_repeat_timeouts_for_one_author_merge_into_one_request():
    async def go():
        s = await build_stack()
        for i in range(4):
            await s.hub.ingest(msg(f"FREE ROBUX at robux-gift.xyz round {'abcd'[i]}", "spammer", ts=2_000_000.0 + i))
        pending = await s.store.pending_actions()
        assert len(pending) == 1
        assert len(pending[0]["message_ids"]) == 4 and pending[0]["action"] == "ban"
    run(go())


def test_moderation_off_and_backfill_are_never_moderated():
    async def go():
        s = await build_stack({"mod_mode": "off"})
        await s.hub.ingest(msg("FREE ROBUX at robux-gift.xyz", "spammer"))
        assert await s.store.action_history() == []
        s.cfg.set("mod_mode", "suggest")
        old = msg("FREE ROBUX at robux-gift.xyz", "spammer2")
        old.backfill = True
        await s.hub.ingest(old)
        assert await s.store.action_history() == []
        assert s.hub.buffer[-1]["verdict"] == "allow"  # stored and shown, but not judged
    run(go())


def test_exempt_levels_and_regulars_pass_through():
    async def go():
        s = await build_stack()
        await s.store.add_regular("goodfriend")
        for name, level in (("boss", "owner"), ("mo", "mod"), ("goodfriend", "everyone")):
            await s.hub.ingest(msg("FREE ROBUX at robux-gift.xyz", name, level))
        assert await s.store.action_history() == []
        assert s.hub.buffer[-1]["level"] == "regular"
    run(go())


def test_commands_reply_in_chat_and_are_skipped_for_punished_messages():
    async def go():
        s = await build_stack()
        await s.demo.run_scenario("commands")
        bot = [m for m in s.hub.buffer if m["from_bot"]]
        assert len(bot) >= 3 and all(m["level"] == "bot" for m in bot)
        assert any(m["text"].startswith("Commands:") for m in bot)
        before = len([m for m in s.hub.buffer if m["from_bot"]])
        await s.hub.ingest(msg("!hello FREE ROBUX at robux-gift.xyz", "sneaky"))
        assert len([m for m in s.hub.buffer if m["from_bot"]]) == before  # no reply to a message awaiting deletion
    run(go())


def test_owner_echo_of_bot_message_is_not_treated_as_a_command():
    async def go():
        s = await build_stack()
        await s.store.create_command("loop", "!loop again", cooldown=0, user_cooldown=0)
        await s.hub.ingest(msg("!loop", "boss", "owner", ts=3_000_000.0))
        replies = [m["text"] for m in s.hub.buffer if m["from_bot"]]
        assert replies == ["!loop again"]
        # YouTube would now echo the bot's own message back, authored by the owner account.
        await s.hub.ingest(msg("!loop again", "boss", "owner", ts=3_000_001.0))
        bot_msgs = [m for m in s.hub.buffer if m["from_bot"]]
        assert len(bot_msgs) == 2          # the original reply + the stored echo; a third would mean a reply loop
        assert s.hub.buffer[-1]["from_bot"] is True and s.hub.buffer[-1]["author_name"] == "boss"
    run(go())


def test_notification_rate_limit_summarises_the_rest():
    async def go():
        s = await build_stack({"telegram_notify_max_per_min": 2})
        for i in range(5):
            await s.hub.ingest(msg("free robux at my profile now", f"user{i}", ts=4_000_000.0 + i * 100))
        await asyncio.sleep(0)
        assert len(s.notes) == 2
        assert len(await s.store.pending_actions()) >= 4
        s.hub._notify_times.clear()
        await s.hub.ingest(msg("free robux at my profile now", "user9", ts=4_001_000.0))
        await asyncio.sleep(0)
        assert "more waiting" in s.notes[-1][0]
    run(go())


def test_flood_rate_limit_and_timing_scenarios():
    async def go():
        s = await build_stack()
        await s.demo.run_scenario("flood")
        reasons = {r.split(":")[0] for p in await s.store.pending_actions() for r in p["reasons"]}
        assert "rate" in reasons
        s2 = await build_stack()
        await s2.demo.run_scenario("bot_timing")
        assert any(m["verdict"] != "allow" for m in s2.hub.buffer)
        flagged = await s2.store.action_history()
        assert flagged and any("timing" in r for h in flagged for r in h["reasons"])
    run(go())


def test_mode_switch_stops_demo_and_unknown_source_is_safe():
    async def go():
        s = await build_stack()
        s.cfg.set("bot_mode", "live")
        st = await s.hub.apply_mode()      # no youtube source registered in this stack
        assert st["source"] is None and st["stream_live"] is False
        s.cfg.set("bot_mode", "demo")
        st = await s.hub.apply_mode()
        assert st["source"] == "demo" and st["stream_live"] is True
        assert await s.hub.send_chat("hello") is True
        assert s.hub.buffer[-1]["text"] == "hello" and s.hub.buffer[-1]["from_bot"]
        await s.hub.shutdown()
        assert s.hub.source is None
    run(go())


# ---------------------------------------------------------------- scheduler
def test_reminders_fire_once_and_repeating_ones_reschedule():
    async def go():
        s = await build_stack()
        drain = events(s)
        a = await s.store.add_reminder("stretch", 100.0)
        b = await s.store.add_reminder("water", 100.0, "interval", 3600)
        await s.scheduler.tick(now=500.0)
        got = [e for e in drain() if e["type"] == "reminder"]
        assert {e["data"]["text"] for e in got} == {"stretch", "water"}
        assert [("stretch" in t, "water" in t) for t, _ in s.notes] == [(True, False), (False, True)] and all("Reminder" in t for t, _ in s.notes)
        pending = await s.store.list_reminders("pending")
        assert [r["id"] for r in pending] == [b] and pending[0]["due"] == 3700.0
        await s.scheduler.tick(now=600.0)
        assert not [e for e in drain() if e["type"] == "reminder"]       # nothing fires twice
        s.cfg.set("reminders_enabled", False)
        await s.store.add_reminder("later", 100.0)
        await s.scheduler.tick(now=700.0)
        assert not [e for e in drain() if e["type"] == "reminder"]
    run(go())


def test_timers_need_interval_and_chat_lines_and_a_live_stream():
    async def go():
        s = await build_stack()
        tid = (await s.store.list_timers())[0]["id"]
        await s.store.update_timer(tid, enabled=True, interval_seconds=60, min_lines=3)
        s.scheduler._started = 0.0
        await s.scheduler.tick(now=100.0)                       # baseline lines recorded; interval ok, lines not
        assert [m for m in s.hub.buffer if m["from_bot"]] == []
        for i in range(3):
            await s.hub.ingest(msg(f"just chatting {'abc'[i]}", f"v{i}", ts=5_000_000.0 + i))
        await s.scheduler.tick(now=200.0)
        bots = [m["text"] for m in s.hub.buffer if m["from_bot"]]
        assert len(bots) == 1 and "Subscribe" in bots[0]
        await s.scheduler.tick(now=210.0)                        # interval not elapsed again
        assert len([m for m in s.hub.buffer if m["from_bot"]]) == 1
        assert (await s.store.list_timers())[0]["fired"] == 1
    run(go())


def test_pending_requests_expire():
    async def go():
        s = await build_stack({"mod_pending_ttl_minutes": 0})
        await s.demo.run_scenario("link_spammer")
        assert len(await s.store.pending_actions()) == 1
        await asyncio.sleep(0.01)
        await s.scheduler.tick(now=__import__("time").time() + 5)
        assert await s.store.pending_actions() == []
        assert (await s.store.action_history())[0]["status"] == "expired"
    run(go())


def test_analytics_summary_counts_and_filters_by_demo():
    async def go():
        s = await build_stack()
        await s.demo.run_scenario("mixed")
        now = s.clock.now() + 10
        a = await summary(s.store, hours=1, demo=True, now=now)
        assert a["totals"]["messages"] == len(s.hub.buffer) > 15
        assert a["totals"]["flagged_messages"] > 0 and a["totals"]["actions"] > 0
        assert sum(t["messages"] for t in a["timeline"]) == a["totals"]["messages"]
        assert any(x["name"] == "raid" for x in a["signals"]) and a["top_chatters"]
        assert (await summary(s.store, hours=1, demo=False, now=now))["totals"]["messages"] == 0
        assert (await summary(s.store, hours=1, demo=None, now=now))["totals"]["messages"] == a["totals"]["messages"]
    run(go())


def test_ambient_demo_chat_runs_and_stops_cleanly():
    async def go():
        s = await build_stack({"demo_messages_per_minute": 600, "demo_spam_probability": 0.2})
        s.demo.set_ambient(True)
        for _ in range(500):               # database writes run in worker threads, so wait on real time
            if len(s.hub.buffer) > 20:
                break
            await asyncio.sleep(0.01)
        s.demo.set_ambient(False)
        n = len(s.hub.buffer)
        assert n > 20
        await asyncio.sleep(0.1)
        assert len(s.hub.buffer) == n      # stopped means stopped
        await s.hub.shutdown()
    run(go())


def test_ambient_chat_never_looks_like_a_raid():
    async def go():
        s = await build_stack({"demo_spam_probability": 0.0})
        await s.hub.apply_mode()
        s.demo.set_ambient(True)
        for _ in range(400):
            await asyncio.sleep(0.01)
            if len(await s.store.recent_chat(500)) > 60:
                break
        s.demo.set_ambient(False)
        rows = await s.store.recent_chat(500)
        assert len(rows) > 40, len(rows)
        assert all(r["verdict"] in (None, "allow") for r in rows), [r for r in rows if r["verdict"] not in (None, "allow")][:3]
    run(go())



def test_top_chatters_is_ten_people_with_ids_and_same_names_stay_apart():
    async def go():
        s = await build_stack()
        now = s.clock.now()
        ins = "INSERT INTO chat_messages (platform, msg_id, author_id, author_name, body, ts, demo) VALUES ('youtube', ?, ?, ?, 'hi', ?, 0)"
        n = 0
        for i in range(12):                                   # twelve different people, the first one the loudest
            for _ in range(12 - i):
                n += 1
                await s.store.db.execute(ins, (f"m{n}", f"u{i}", f"Person{i}", now - 5))
        for k in range(3):                                    # two different people who share a display name are two rows, not one
            await s.store.db.execute(ins, (f"x{k}", "twinA", "Twin", now - 5))
        await s.store.db.execute(ins, ("y1", "twinB", "Twin", now - 5))
        a = await summary(s.store, hours=1, demo=False, now=now + 5)
        top = a["top_chatters"]
        assert len(top) == 10 and top[0]["author_id"] == "u0" and top[0]["platform"] == "youtube" and top[0]["messages"] == 12
        assert all("author_id" in t for t in top)
        twins = [t for t in top if t["name"] == "Twin"]
        assert not twins or all(t["messages"] in (3, 1) for t in twins)
    run(go())
