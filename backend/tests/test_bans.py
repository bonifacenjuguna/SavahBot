"""Ban management: softening rules, the ledger, lifting, and the API."""
import asyncio

from helpers import build_stack
from test_api import e2e


class FakeSource:
    name = "youtube"

    def __init__(self, ok=True):
        self.ok, self.lifted = ok, []

    async def unban(self, ref):
        self.lifted.append(ref)
        return (True, "") if self.ok else (False, "YouTube quota exhausted for today.")


def test_limit_rules_only_ever_lower_an_action():
    async def go():
        s = await build_stack()
        b = s.hub.bans
        assert (await b.limit("delete", None, [], "u1", "Ann", True))[0] == "delete"
        assert (await b.limit("ban", None, [], "u1", "Ann", True))[0] == "ban"          # no rules: untouched
        s.cfg.set("mod_max_punishment", "delete")
        act, dur, note = await b.limit("ban", None, [], "u1", "Ann", True)
        assert act == "delete" and dur is None and "delete" in note
        s.cfg.set("mod_max_punishment", "timeout")
        act, dur, _ = await b.limit("ban", None, [], "u1", "Ann", True)
        assert act == "timeout" and dur                                                 # gets a duration from the ladder
        s.cfg.set("mod_max_punishment", "ban")
        s.cfg.set("mod_never_punish", "Ann, UC123")
        assert (await b.limit("timeout", 60, [], "u1", "ann", True))[0] == "delete"      # name match ignores case
        assert (await b.limit("ban", None, [], "UC123", "x", True))[0] == "delete"
        s.cfg.set("mod_never_punish", "")
        s.cfg.set("mod_reason_caps", "link:delete,raid:ban")
        assert (await b.limit("ban", None, ["link"], "u2", "Bo", True))[0] == "delete"
        assert (await b.limit("ban", None, ["raid"], "u2", "Bo", True))[0] == "ban"

    asyncio.run(go())


def test_daily_cap_counts_only_automatic_actions():
    async def go():
        s = await build_stack()
        b = s.hub.bans
        s.cfg.set("mod_auto_punish_daily_cap", 2)
        for i in range(2):
            await b.record(author_id=f"u{i}", author_name="x", kind="ban", duration=None, ban_ref="r", action_id=None, source="auto", reason="")
        await b.record(author_id="m", author_name="x", kind="ban", duration=None, ban_ref="r", action_id=None, source="approved", reason="")
        assert await b.auto_count_today(__import__("time").time()) == 2
        assert (await b.limit("ban", None, [], "new", "N", True))[0] == "delete"        # cap reached
        assert (await b.limit("ban", None, [], "new", "N", False))[0] == "ban"          # approved by you: cap does not apply


    asyncio.run(go())


def test_unban_needs_youtube_to_confirm_and_second_chance_lifts_old_auto_bans():
    async def go():
        s = await build_stack()
        src = FakeSource(ok=False)
        s.hub.sources["youtube"] = src
        bid = await s.hub.bans.record(author_id="u1", author_name="Ann", kind="ban", duration=None, ban_ref="BAN1", action_id=None, source="auto", reason="spam", now=1000.0)
        res = await s.hub.unban(bid)
        assert not res["ok"] and (await s.hub.bans.get(bid))["status"] == "active"      # not marked lifted without confirmation
        src.ok = True
        s.cfg.set("mod_second_chance_hours", 0)
        await s.hub.second_chance(1000.0 + 99 * 3600)
        assert (await s.hub.bans.get(bid))["status"] == "active"                        # off by default
        s.cfg.set("mod_second_chance_hours", 24)
        await s.hub.second_chance(1000.0 + 25 * 3600)
        row = await s.hub.bans.get(bid)
        assert row["status"] == "lifted" and row["lifted_by"] == "second chance" and src.lifted[-1] == "BAN1"
        assert (await s.hub.unban(bid))["ok"] is False                                  # cannot lift twice

    asyncio.run(go())


def test_ban_without_youtube_id_cannot_be_lifted_from_the_dashboard():
    async def go():
        s = await build_stack()
        await s.hub.bans.record(author_id="u1", author_name="Ann", kind="ban", duration=None, ban_ref="", action_id=None, source="approved", reason="")
        item = (await s.hub.bans.search("active"))["items"][0]
        assert item["can_lift"] is False
        await s.hub.bans.record(author_id="u2", author_name="Bo", kind="timeout", duration=60, ban_ref="T", action_id=None, source="approved", reason="", now=1.0)
        assert (await s.hub.bans.search("expired"))["total"] == 1                         # a timeout that ran out is shown as expired

    asyncio.run(go())


def test_approving_a_ban_writes_the_ledger_row():
    async def go():
        s = await build_stack()
        aid = await s.store.create_action({"ts": 1.0, "platform": "youtube", "author_id": "u9", "author_name": "Zed", "message_ids": [], "text": "x",
                                           "action": "ban", "score": 100, "reasons": ["spam"], "status": "pending", "mode": "suggest", "demo": True})
        assert (await s.hub.approve(aid))["ok"]
        rows = (await s.hub.bans.search("active"))["items"]
        assert len(rows) == 1 and rows[0]["author_name"] == "Zed" and rows[0]["demo"] == 1 and rows[0]["can_lift"]
        assert (await s.hub.unban(rows[0]["id"]))["ok"]
        assert (await s.hub.bans.counts())["lifted"] == 1

    asyncio.run(go())




def test_manual_actions_from_a_stored_chat_message():
    """Chosen from the chat: simulated in demo, the owner and bot are protected, a ban reaches the ledger and can be lifted (the Undo button)."""
    async def go():
        s = await build_stack()
        add = lambda name, level="everyone": s.store.add_chat({"platform": "demo", "msg_id": "m", "author_id": "u1", "author_name": name, "text": "hi", "level": level, "ts": 1.0, "demo": True})
        a, owner = await add("Zed"), await add("Boss", "owner")
        assert (await s.hub.manual(a, "delete"))["ok"] and (await s.hub.bans.counts())["active"] == 0
        r = await s.hub.manual(a, "timeout", 60)
        assert r["ok"] and r["simulated"] and r["ban_id"]
        assert (await s.hub.bans.counts())["active"] == 1
        assert (await s.hub.unban(r["ban_id"]))["ok"]
        assert not (await s.hub.manual(owner, "ban"))["ok"]
        assert (await s.hub.manual(999, "ban"))["code"] == 404 and (await s.hub.manual(a, "nuke"))["code"] == 422
    asyncio.run(go())


@e2e
async def test_bans_api(api):
    assert (await api.call("GET", "/api/bans", auth=False))[0] == 401
    st, r = await api.call("GET", "/api/bans")
    assert st == 200 and r["total"] == 0 and "rules" in r
    st, p = await api.call("POST", "/api/bans/preview", {"action": "ban", "signals": ["link"]})
    assert st == 200 and p["action"] == "ban" and not p["changed"]
    assert (await api.call("POST", "/api/bans/preview", {"action": "flag"}))[0] == 404
    assert (await api.call("POST", "/api/bans/99/lift"))[0] == 404


@e2e
async def test_chat_person_card_and_costs(api):
    assert (await api.call("GET", "/api/chat/person"))[0] == 422
    st, p = await api.call("GET", "/api/chat/person?author_id=nobody")
    assert st == 200 and p["messages"] == 0 and p["recent"] == [] and p["actions"] == []
    st, k = await api.call("GET", "/api/chat/costs")
    assert st == 200 and k["ban"] > k["delete"] > 0
    assert (await api.call("POST", "/api/chat/act", {"id": 12345, "action": "ban"}))[0] == 404


@e2e
async def test_demo_sample_history(api):
    await api.call("POST", "/api/mode", {"mode": "demo"})
    st, r = await api.call("POST", "/api/demo/sample")
    assert st == 200 and r["bans"] == 4
    st, b = await api.call("GET", "/api/bans")
    assert b["total"] >= 4 and {i["status"] for i in b["items"]} >= {"active", "lifted"}
