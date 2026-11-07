"""Knowledge management, learning and live data, against a real (in-memory) database."""
import asyncio
import json
import time

import pytest

from app.config import Settings
from app.db import Database
from app.intel import Intel
from app.intel import feeds as feeds_mod
from app.intel.feeds import FeedManager, parse_feed
from app.intel.learning import Learning
from app.intel.service import Knowledge, clean_entry
from app.moderation import ModerationEngine, ModInput, PermitStore
from app.runtime_config import RuntimeConfig
from app.store import Store, ValidationFailed


class Rig:
    pass


async def rig(env=None):
    r = Rig()
    r.db = Database(":memory:")
    await r.db.connect()
    r.cfg = RuntimeConfig(Settings(env=env or {}), r.db)
    await r.cfg.load()
    r.store = Store(r.db)
    r.intel = Intel(r.cfg)
    r.engine = ModerationEngine(r.cfg, PermitStore())
    r.engine.intel = r.intel
    r.kn = Knowledge(r.db, r.cfg, r.intel, r.store)
    r.learn = Learning(r.db, r.cfg, r.intel, r.kn)
    r.feeds = FeedManager(r.db, r.cfg, r.intel, r.kn)
    r.kn.learning, r.kn.feeds = r.learn, r.feeds
    await r.kn.load()
    await r.feeds.load()
    await r.learn.load()
    return r


def score(r, text, name="viewer"):
    return r.engine.evaluate(ModInput("demo", name, name, text, "everyone", time.time()), stateless=True)


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------------------------------------ entries and packs
def test_added_phrase_takes_effect_and_can_be_removed():
    async def go():
        r = await rig()
        assert score(r, "buy zorbnik tokens at the bazaar").score == 0
        res = await r.kn.add_entries("spam.custom", ["zorbnik tokens"], weight=60)
        assert res["added"] == 1
        assert score(r, "buy zorbnik tokens at the bazaar").score >= 55
        await r.kn.remove_entry("spam.custom", "zorbnik tokens")
        assert score(r, "buy zorbnik tokens at the bazaar").score == 0
    run(go())


def test_builtin_entries_can_be_switched_off_reweighted_and_reset():
    async def go():
        r = await rig()
        base = score(r, "free robux").score
        assert base >= 30
        await r.kn.set_entry("scams.giveaway", "free robux", enabled=False)
        assert score(r, "free robux").score < base
        await r.kn.set_entry("scams.giveaway", "free robux", enabled=True, weight=20)
        listing = next(i for i in r.kn.entry_list("scams.giveaway", q="free robux")["items"] if i["phrase"] == "free robux")
        assert listing["weight"] == 20 and listing["edited"] and listing["default_weight"] != 20
        await r.kn.remove_entry("scams.giveaway", "free robux")          # a built-in entry: reset, not delete
        assert score(r, "free robux").score == base
        assert any(i["phrase"] == "free robux" for i in r.kn.entry_list("scams.giveaway", q="robux")["items"])
    run(go())


def test_changes_survive_a_restart():
    async def go():
        r = await rig()
        await r.kn.add_entries("spam.custom", ["glorp deal"], weight=55)
        await r.kn.set_pack("scams.crypto", mode="off")
        await r.kn.set_entry("scams.giveaway", "free robux", enabled=False)
        r2 = Rig()
        r2.cfg, r2.db = r.cfg, r.db
        r2.intel = Intel(r.cfg)
        k2 = Knowledge(r.db, r.cfg, r2.intel)
        await k2.load()
        assert r2.intel.pack_mode(r2.intel.packs["scams.crypto"]) == "off"
        assert any(e["phrase"] == "glorp deal" for e in k2.entry_list("spam.custom")["items"])
    run(go())


def test_pack_mode_and_strength_validation():
    async def go():
        r = await rig()
        with pytest.raises(ValidationFailed):
            await r.kn.set_pack("scams.crypto", mode="loud")
        with pytest.raises(ValidationFailed):
            await r.kn.set_pack("scams.crypto", scale=9)
        with pytest.raises(KeyError):
            await r.kn.set_pack("nope.nothing", mode="off")
        info = await r.kn.set_pack("scams.crypto", mode="shadow", scale=0.5)
        assert info["mode"] == "shadow" and info["overridden"] and info["scale"] == 0.5
        info = await r.kn.set_pack("scams.crypto", mode="")                # back to the default
        assert not info["overridden"] and info["mode"] == "live"
    run(go())


def test_entry_validation_per_kind():
    async def go():
        r = await rig()
        P = r.intel.packs
        assert clean_entry(P["links.custom"], "https://www.Evil-Site.xyz/path?x=1") == ("evil-site.xyz", False)
        with pytest.raises(ValidationFailed):
            clean_entry(P["links.custom"], "not a domain")
        assert clean_entry(P["links.suspicious_tlds"], ".XYZ") == ("xyz", False)
        with pytest.raises(ValidationFailed):
            clean_entry(P["links.words"], "two words")
        assert clean_entry(P["spam.custom"], "re:buy\\s+now") == ("buy\\s+now", True)
        with pytest.raises(ValidationFailed):
            clean_entry(P["spam.custom"], "re:(broken")
        with pytest.raises(ValidationFailed):
            clean_entry(P["spam.custom"], "")
        with pytest.raises(ValidationFailed):
            await r.kn.add_entries("scams.intent_facets", ["x"])           # not an editable list
        res = await r.kn.add_entries("spam.custom", ["same thing", "Same Thing", "ok phrase"])
        assert res["added"] == 2 and res["skipped"] == 1
    run(go())


def test_added_domain_is_treated_as_dangerous_with_subdomains():
    async def go():
        r = await rig()
        await r.kn.add_entries("links.custom", ["shady-deals.example"])
        assert "link_risk" in {s.name for s in score(r, "see http://promo.shady-deals.example/x").signals}
    run(go())


def test_non_latin_entries_can_be_removed():
    async def go():
        r = await rig()
        await r.kn.add_entries("spam.custom", ["\u041a\u0443\u043f\u0438 \u0441\u0435\u0439\u0447\u0430\u0441"])
        assert any(i["phrase"].startswith("\u041a\u0443\u043f\u0438") for i in r.kn.entry_list("spam.custom")["items"])
        out = await r.kn.remove_entry("spam.custom", "\u043a\u0443\u043f\u0438 \u0441\u0435\u0439\u0447\u0430\u0441")    # different case
        assert out["removed"] == 1 and not r.kn.entry_list("spam.custom")["items"]
    run(go())


def test_search_ranks_and_filters():
    async def go():
        r = await rig()
        out = r.kn.entry_list("scams.giveaway", q="steam")["items"]
        assert out and all("steam" in i["phrase"].lower() for i in out[:3])
        assert r.kn.entry_list("scams.giveaway", only="added")["total"] == 0
        assert r.kn.entry_list("scams.giveaway", limit=5)["items"].__len__() == 5
    run(go())


def test_export_lists_effective_entries():
    async def go():
        r = await rig()
        await r.kn.add_entries("spam.custom", ["glorp deal"], weight=55)
        text = r.kn.export_text("spam.custom")
        assert "glorp deal\t55" in text and text.startswith("# Your own spam phrases")
    run(go())


def test_detector_settings_and_views():
    async def go():
        r = await rig()
        dets = {d["id"]: d for d in await r.kn.detectors()}
        assert dets["harassment"]["mode"] == "live" and dets["abuse"]["mode"] == "shadow" and dets["abuse"]["default_mode"] == "shadow"
        assert score(r, "you are an idiot").score == 0                      # abuse is shadow by default
        await r.kn.set_detector("abuse", mode="live")
        r.intel.rebuild()
        assert score(r, "you are an idiot").score > 0
        with pytest.raises(ValidationFailed):
            await r.kn.set_detector("abuse", mode="nope")
        with pytest.raises(KeyError):
            await r.kn.set_detector("nope", mode="live")
        ov = await r.kn.overview()
        assert ov["status"]["packs_active"] > 30 and ov["detector_modes"]["live"] >= 6 and ov["categories"]
    run(go())


def test_hit_counters_are_persisted():
    async def go():
        r = await rig()
        r.engine.evaluate(ModInput("demo", "a", "a", "double your bitcoin now whatsapp me +254712345678", "everyone", 1000.0))
        assert r.intel.pending["live:scam"] == 1
        await r.kn.flush()
        assert (await r.kn.counters())["intel:live:scam"] == 1
        assert not r.intel.pending
    run(go())


# ------------------------------------------------------------------------------------------------ learning
async def add_action(r, text, status, author="u1", reasons=("scam: x",), demo=0):
    await r.db.execute("INSERT INTO mod_actions (ts, platform, author_id, author_name, body, score, reasons, action, status, demo) "
                       "VALUES (?, 'youtube', ?, ?, ?, 60, ?, 'delete', ?, ?)", (time.time(), author, author, text, json.dumps(list(reasons)), status, demo))


def test_feedback_trains_the_model_and_remembers_spam_examples():
    async def go():
        r = await rig()
        action = {"body": "xylophone discount mega bonanza click now", "demo": 0}
        before = r.intel.nb.predict(action["body"])[0]
        for _ in range(4):
            await r.learn.feedback(action, "spam")
        assert r.intel.nb.predict(action["body"])[0] >= before
        assert r.intel.learned_examples == [action["body"]]                  # duplicates are not stored twice
        await r.learn.feedback({"body": "demo line", "demo": 1}, "spam")     # demo traffic never teaches the bot
        assert len(r.intel.learned_examples) == 1
        await r.learn.persist()
        r2 = await rig()
        r2.db = r.db
        l2 = Learning(r.db, r.cfg, Intel(r.cfg), r.kn)
        await l2.load()
        assert l2.intel.learned_examples == [action["body"]]
    run(go())


def test_backfill_learns_from_past_decisions_once():
    async def go():
        r = await rig()
        await add_action(r, "winner winner prize claim click", "executed")
        await add_action(r, "nice game", "rejected")
        await r.db.kv_set("intel_backfilled", "")          # as on the first start after upgrading
        l2 = Learning(r.db, r.cfg, r.intel, r.kn)
        await l2.load()
        assert "winner winner prize claim click" in r.intel.learned_examples
        n = r.intel.learned_nb.docs["spam"]
        await Learning(r.db, r.cfg, r.intel, r.kn).load()                    # second start: no double counting
        assert r.intel.learned_nb.docs["spam"] == n
    run(go())


def test_phrase_suggestions_need_repeats_from_several_accounts():
    async def go():
        r = await rig()
        for i in range(4):
            await add_action(r, f"visit blorptastic shop today {i}", "executed", author=f"acc{i}")
        await add_action(r, "visit lonely thing today", "executed", author="acc9")
        res = await r.learn.refresh()
        phrases = [s["body"] for s in await r.learn.suggestions()]
        assert res["new"] >= 1 and any("blorptastic" in p for p in phrases)
        assert not any("lonely" in p for p in phrases)
        again = await r.learn.refresh()                                       # nothing new the second time
        assert again["new"] == 0
    run(go())


def test_accept_adds_the_phrase_and_undo_removes_it():
    async def go():
        r = await rig()
        for i in range(4):
            await add_action(r, f"visit blorptastic shop today {i}", "executed", author=f"acc{i}")
        await r.learn.refresh()
        mine = [x for x in await r.learn.suggestions() if "blorptastic" in x["body"]]
        assert mine and all(len(x["body"].split()) <= 3 for x in mine)       # short phrases generalise better than whole lines
        assert score(r, "come to the blorptastic shop").score == 0
        logs = [(await r.learn.accept(x["id"]))["log_id"] for x in mine]
        assert score(r, "come to the blorptastic shop").score >= 30
        with pytest.raises(ValidationFailed):
            await r.learn.accept(mine[0]["id"])                                # cannot accept twice
        assert (await r.learn.log())[0]["summary"].startswith("Added")
        for lid in logs:
            await r.learn.undo(lid)
        assert score(r, "come to the blorptastic shop").score == 0
        with pytest.raises(ValidationFailed):
            await r.learn.undo(logs[0])
        await r.learn.refresh()
        assert not [x for x in await r.learn.suggestions() if "blorptastic" in x["body"]]   # undone suggestions stay dismissed
    run(go())


def test_safe_phrase_suggestion_from_rejections():
    async def go():
        r = await rig()
        for i in range(3):
            await add_action(r, f"my whatsapp number is on the wall {i}", "rejected", author=f"fan{i}")
        await r.learn.refresh()
        kinds = {(s["kind"], s["pack_id"]) for s in await r.learn.suggestions()}
        assert ("safe", "safe.learned") in kinds
    run(go())


def test_detector_that_is_often_rejected_gets_a_strength_suggestion():
    async def go():
        r = await rig()
        for i in range(12):
            await add_action(r, f"msg {i}", "rejected" if i < 9 else "executed", reasons=("spam: promo",))
        await r.learn.refresh()
        s = next(x for x in await r.learn.suggestions() if x["kind"] == "scale")
        assert s["body"] == "spam" and s["weight"] < 100
        await r.learn.accept(s["id"])
        assert r.intel.learned_scale["spam"] < 1
        log = (await r.learn.log())[0]
        await r.learn.undo(log["id"])
        assert "spam" not in r.intel.learned_scale
    run(go())


def test_shadow_detector_that_agrees_with_you_is_offered_for_promotion():
    async def go():
        r = await rig()
        for i in range(4):
            await add_action(r, f"you are such an idiot number {i}", "executed", author=f"a{i}", reasons=("abuse: idiot",))
        await add_action(r, "nice play team", "rejected")
        await r.learn.refresh()
        s = next(x for x in await r.learn.suggestions() if x["kind"] == "promote")
        assert s["body"] == "abuse"
        await r.learn.accept(s["id"])
        assert r.cfg.get("intel_abuse_mode") == "live"
        await r.learn.undo((await r.learn.log())[0]["id"])
        assert r.cfg.get("intel_abuse_mode") == "shadow"
    run(go())


def test_auto_mode_applies_only_confident_suggestions_and_logs_them():
    async def go():
        r = await rig({"INTEL_LEARNING_MODE": "auto"})
        for i in range(5):
            await add_action(r, f"visit blorptastic shop today {i}", "executed", author=f"acc{i}")
        for i in range(3):
            await add_action(r, f"my whatsapp number is on the wall {i}", "rejected", author=f"fan{i}")
        res = await r.learn.refresh()
        assert res["auto_applied"] >= 1
        assert score(r, "come to the blorptastic shop").score >= 30
        assert any(x["summary"].startswith("Auto:") for x in await r.learn.log())
        assert any(s["kind"] == "safe" for s in await r.learn.suggestions())   # safe phrases always wait for you
    run(go())


def test_learning_stats_report_precision_per_detector():
    async def go():
        r = await rig()
        for i in range(3):
            await add_action(r, f"a{i}", "executed", reasons=("scam: x", "link: y"))
        await add_action(r, "b", "rejected", reasons=("scam: x",))
        await add_action(r, "demo noise", "executed", demo=1)
        st = await r.learn.stats()
        scam = next(s for s in st["signals"] if s["name"] == "scam")
        assert st["decisions"] == 4 and scam["approved"] == 3 and scam["rejected"] == 1 and scam["precision"] == 0.75
    run(go())


# ------------------------------------------------------------------------------------------------ live data
class FakeNet:
    def __init__(self):
        self.status, self.body, self.headers, self.calls = 200, b"", {}, []

    async def __call__(self, method, url, headers=None, **kw):
        self.calls.append((url, dict(headers or {}), kw))
        return self.status, self.body, dict(self.headers)


def hosts(n, prefix="bad"):
    return "\n".join(["# list", "127.0.0.1 localhost"] + [f"0.0.0.0 {prefix}{i}.tracker-site.org" for i in range(n)]).encode()


def test_feed_refresh_stores_domains_and_they_start_to_matter(monkeypatch=None):
    async def go():
        r = await rig()
        net = FakeNet()
        net.body, net.headers = hosts(50), {"ETag": '"v1"'}
        feeds_mod.request_raw = net
        out = await r.feeds.refresh("urlhaus_hosts")
        assert out["ok"] and out["entries"] == 50
        assert "link_risk" in {s.name for s in score(r, "go to http://bad3.tracker-site.org/login").signals}
        # a second refresh sends the ETag and a 304 keeps everything
        net.status, net.body = 304, b""
        out = await r.feeds.refresh("urlhaus_hosts")
        assert out["status"] == "up to date" and net.calls[-1][1].get("If-None-Match") == '"v1"'
        assert "link_risk" in {s.name for s in score(r, "http://bad3.tracker-site.org/").signals}
    run(go())


def test_feed_failures_keep_the_old_data():
    async def go():
        r = await rig()
        net = FakeNet()
        feeds_mod.request_raw = net
        net.body = hosts(40)
        await r.feeds.refresh("urlhaus_hosts")
        for status, body in ((500, b"oops"), (200, b""), (200, b"# only comments\n")):
            net.status, net.body = status, body
            out = await r.feeds.refresh("urlhaus_hosts", force=True)
            assert not out["ok"]
        info = next(f for f in r.feeds.list() if f["id"] == "urlhaus_hosts")
        assert info["entries"] == 40 and info["status"] == "failed" and info["error"]
        assert "link_risk" in {s.name for s in score(r, "http://bad1.tracker-site.org/").signals}
        async def boom(*a, **k):
            raise feeds_mod.NetworkError("offline")
        feeds_mod.request_raw = boom
        assert not (await r.feeds.refresh("urlhaus_hosts"))["ok"]
    run(go())


def test_suspicious_shrinking_list_is_refused_unless_forced():
    async def go():
        r = await rig()
        net = FakeNet()
        feeds_mod.request_raw = net
        net.body = hosts(300)
        await r.feeds.refresh("urlhaus_hosts")
        net.body = hosts(10, "other")
        out = await r.feeds.refresh("urlhaus_hosts")
        assert not out["ok"] and "shrank" in out["error"]
        assert (await r.feeds.refresh("urlhaus_hosts", force=True))["ok"]
    run(go())


def test_feeds_can_never_blocklist_well_known_sites():
    async def go():
        r = await rig()
        net = FakeNet()
        feeds_mod.request_raw = net
        net.body = b"0.0.0.0 youtube.com\n0.0.0.0 www.google.com\n0.0.0.0 github.io\n0.0.0.0 evil.top\n0.0.0.0 pages.github.io\n0.0.0.0 mine.example.org\n"
        await r.cfg.set("mod_allowed_domains", "example.org")
        r.intel.rebuild()
        await r.feeds.refresh("urlhaus_hosts")
        listed = {i["phrase"] for i in r.kn.entry_list("links.threat_feed")["items"]}
        assert listed == {"evil.top", "pages.github.io"}
        assert "link_risk" not in {s.name for s in score(r, "watch https://youtube.com/watch?v=x").signals}
    run(go())


def test_rollback_restores_the_previous_version():
    async def go():
        r = await rig()
        net = FakeNet()
        feeds_mod.request_raw = net
        net.body = hosts(120, "old")
        await r.feeds.refresh("urlhaus_hosts")
        net.body = hosts(150, "new")
        await r.feeds.refresh("urlhaus_hosts", force=True)
        assert "link_risk" in {s.name for s in score(r, "http://new7.tracker-site.org/").signals}
        assert next(f for f in r.feeds.list() if f["id"] == "urlhaus_hosts")["can_rollback"]
        out = await r.feeds.rollback("urlhaus_hosts")
        assert out["entries"] == 120
        assert "link_risk" in {s.name for s in score(r, "http://old7.tracker-site.org/").signals}
        assert "link_risk" not in {s.name for s in score(r, "http://new7.tracker-site.org/").signals}
        with pytest.raises(ValidationFailed):
            await r.feeds.rollback("urlhaus_hosts")
    run(go())


def test_disabled_feed_contributes_nothing_and_comes_back_when_enabled():
    async def go():
        r = await rig()
        net = FakeNet()
        feeds_mod.request_raw = net
        net.body = hosts(40)
        await r.feeds.refresh("urlhaus_hosts")
        await r.feeds.set_enabled("urlhaus_hosts", False)
        assert "link_risk" not in {s.name for s in score(r, "http://bad1.tracker-site.org/").signals}
        await r.feeds.set_enabled("urlhaus_hosts", True)
        assert "link_risk" in {s.name for s in score(r, "http://bad1.tracker-site.org/").signals}
        assert next(f for f in r.feeds.list() if f["id"] == "openphish")["enabled"] is False    # licence-restricted: opt in
    run(go())


def test_custom_feeds_are_guarded_and_removable():
    async def go():
        r = await rig()
        with pytest.raises(ValidationFailed):
            await r.feeds.add_custom("Local", "http://127.0.0.1/list.txt", "domains")
        with pytest.raises(ValidationFailed):
            await r.feeds.add_custom("Bad format", "https://example.org/x", "xml")
        with pytest.raises(ValidationFailed):
            await r.feeds.add_custom("", "https://example.org/x", "domains")
        net = FakeNet()
        feeds_mod.request_raw = net
        net.body = b"scam-one.example\nscam-two.example\n"
        import app.commands.variables as v
        async def ok(url, cfg):
            return None
        real = v.check_url
        v.check_url = ok
        try:
            fid = (await r.feeds.add_custom("My list", "https://lists.example.org/x.txt", "domains"))["id"]
            assert (await r.feeds.refresh(fid))["entries"] == 2
            assert net.calls[-1][2]["follow_redirects"] is False              # custom URLs never follow redirects
            await r.feeds.remove_custom(fid)
        finally:
            v.check_url = real
        assert all(f["id"] != fid for f in r.feeds.list())
        with pytest.raises(KeyError):
            await r.feeds.remove_custom("urlhaus_hosts")                     # built-in feeds cannot be deleted
    run(go())


def test_scheduler_tick_waits_for_the_startup_delay():
    async def go():
        r = await rig({"INTEL_FEED_STARTUP_DELAY_SECONDS": "3600"})
        net = FakeNet()
        feeds_mod.request_raw = net
        await r.feeds.tick(time.time())
        assert not net.calls
        r2 = await rig({"INTEL_FEED_STARTUP_DELAY_SECONDS": "0", "INTEL_FEEDS_ENABLED": "false"})
        feeds_mod.request_raw = net
        await r2.feeds.tick(time.time())
        assert not net.calls
    run(go())


def test_parse_feed_formats():
    assert parse_feed("# x\n0.0.0.0 a-bad.top\n127.0.0.1 localhost\nnot a line", "hosts", 10) == ["a-bad.top"]
    assert parse_feed("http://x.bad.club/p?q=1\nhttps://www.y.top/", "urls", 10) == ["x.bad.club", "y.top"]
    assert parse_feed("dup.top\ndup.top\nother.top", "domains", 10) == ["dup.top", "other.top"]
    assert parse_feed("buy cheap pills now\nhi", "phrases", 10) == ["buy cheap pills now"]
    assert len(parse_feed("\n".join(f"d{i}.top" for i in range(50)), "domains", 7)) == 7
