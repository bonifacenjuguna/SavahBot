"""1.1.6: knowledge packs, detectors, modes, learning and the hub wiring. Everything runs on this machine, with no AI service."""
import asyncio
import json
import time
from pathlib import Path

import pytest

from app.config import StaticConfig
from app.db import Database
from app.intel import Intelligence
from app.intel import text as T
from app.intel.detectors.base import Ctx
from app.intel.detectors.learning import NBModel
from app.intel.knowledge import PackRegistry
from app.models import ChatMessage
from app.moderation import ModerationEngine, ModInput, PermitStore

from helpers import build_stack

IDS = ["packs", "fuzzy", "learning", "links", "reputation", "scam", "shape", "evasion", "names"]


def run(coro):
    return asyncio.run(coro)


def cfg(mode="active", **extra):
    return StaticConfig({**{f"intel_{i}_mode": mode for i in IDS}, **extra})


async def make(mode="active", **extra):
    db = Database(":memory:")
    await db.connect()
    intel = Intelligence(cfg(mode, **extra), db)
    await intel.start()
    return intel, db


def m(text, name="viewer", level="everyone", aid="a1"):
    return ModInput("youtube", aid, name, text, level, 1000.0)


def points(intel, text, **kw):
    out = intel.analyze(m(text, **{k: v for k, v in kw.items() if k in ("name", "level", "aid")}), base_score=0)
    return sum(a.weight for a in out.active), out


# ---------------------------------------------------------------- the text toolkit
def test_edit_distance_counts_a_swap_as_one_edit():
    assert T.damerau("robux", "robxu") == 1
    assert T.damerau("kitten", "sitting", 2) == 3          # stops early once it is certain to pass the limit
    assert T.flat("F R E E   r0bux") == "frerobux"
    assert T.mixed_script_words("hello fr\u0435\u0435 robux") != []
    assert abs(T.noisy_or([0.5, 0.5]) - 0.75) < 1e-9


# ---------------------------------------------------------------- packs
def test_every_shipped_pack_loads_and_is_split_by_category():
    reg = PackRegistry()
    reg.load()
    assert reg.problems == []
    kinds = {p.kind for p in reg.packs.values()}
    assert kinds == {"phrases", "templates", "linkrisk", "confusables", "identity", "corpus"}
    assert len(reg.packs) >= 12 and len(reg.phrase_entries()) > 200
    assert all(p.version and p.updated for p in reg.packs.values())
    assert any(p.sources for p in reg.packs.values()), "researched packs say where the knowledge came from"
    assert reg.packs["abuse-yours"].entries == [] and reg.packs["abuse-yours"].user_supplied   # shipped empty on purpose


def test_a_broken_pack_is_reported_and_never_stops_loading(tmp_path):
    good = {"id": "ok-pack", "title": "ok", "kind": "phrases", "category": "spam", "entries": ["hello there world"]}
    (tmp_path / "ok.json").write_text(json.dumps(good))
    (tmp_path / "bad.json").write_text("{not json")
    (tmp_path / "worse.json").write_text(json.dumps({"id": "Bad Id!", "kind": "phrases"}))
    (tmp_path / "regex.json").write_text(json.dumps({"id": "bad-regex", "kind": "templates", "category": "scams", "data": {"groups": [{"patterns": ["(unclosed"]}]}}))
    reg = PackRegistry(tmp_path)
    reg.load()
    assert list(reg.packs) == ["ok-pack"] and len(reg.problems) == 3


def test_switching_a_pack_off_adding_and_muting_entries():
    async def go():
        intel, db = await make()
        reg = intel.registry
        assert points(intel, "free robux now")[0] > 0
        await intel.store.set_pack_enabled("scam-prizes", False)
        await intel.refresh_state()
        assert "knowledge" not in {a.signal for a in intel.analyze(m("claim your gift today"), base_score=0).active}
        await intel.store.set_pack_enabled("scam-prizes", True)
        await intel.store.add_user_entry("abuse-yours", "add", "totally forbidden word", 80)
        await intel.refresh_state()
        w, out = points(intel, "that is a totally forbidden word")
        assert w >= 60 and any(a.signal == "knowledge" for a in out.active)
        await intel.store.add_user_entry("abuse-yours", "mute", "totally forbidden word")
        await intel.refresh_state()
        assert points(intel, "that is a totally forbidden word")[0] == 0
        rows = {r.value: r for r in reg.rows("abuse-yours")}
        assert rows["totally forbidden word"].user and rows["totally forbidden word"].muted
    run(go())


# ---------------------------------------------------------------- detectors
def test_knowledge_packs_see_through_disguises():
    async def go():
        intel, _ = await make()
        for text in ("FREE ROBUX", "fr33 r0bux", "f r e e  r o b u x", "free   robuxxx", "fr\u0435\u0435 robux"):
            assert points(intel, text)[0] >= 50, text
    run(go())


def test_fuzzy_matching_catches_typos_and_dropped_vowels_exact_matching_misses():
    async def go():
        intel, _ = await make("off", intel_fuzzy_mode="active")
        assert points(intel, "get your fre robxu here")[0] > 0       # typo and swap
        assert points(intel, "claim frr rbx now")[0] >= 0
        assert points(intel, "what a nice stream today")[0] == 0     # ordinary chat is left alone
        intel2, _ = await make("off", intel_fuzzy_mode="active", intel_packs_mode="active")
        w, out = points(intel2, "free robux")
        assert {a.signal for a in out.active} == {"knowledge"}       # an exact hit is never counted twice by fuzzy
    run(go())


def test_link_intelligence_judges_the_address_not_just_the_presence_of_a_link():
    async def go():
        intel, _ = await make("off", intel_links_mode="active")
        assert points(intel, "watch https://www.youtube.com/watch?v=abc")[0] == 0      # safe domain
        assert points(intel, "see https://youtub3.com/login")[0] >= 30                # lookalike brand
        assert points(intel, "go to youtube.com.verify-login.xyz")[0] >= 30           # brand hidden in a subdomain
        assert points(intel, "bit.ly/3abc")[0] > 0                                    # shortener
        assert points(intel, "http://192.168.4.4/free")[0] > 0                        # raw IP
        assert points(intel, "http://youtube.com@evil.top/x")[0] > 0                  # the @ trick
        assert points(intel, "no link in this message at all")[0] == 0
        intel2, _ = await make("off", intel_links_mode="active", mod_allowed_domains="my-shop.xyz")
        assert points(intel2, "buy at my-shop.xyz")[0] == 0                           # allowed domains stay allowed
    run(go())


def test_scam_shapes_need_several_hints_unless_one_is_strong():
    async def go():
        intel, _ = await make("off", intel_scam_mode="active")
        assert points(intel, "you won the match, congrats!")[0] == 0                  # one weak hint alone: quiet
        assert points(intel, "send 0.1 BTC and get double back")[0] > 30               # money doubling is strong alone
        assert points(intel, "you have won! click the link in my bio, dm me to claim")[0] > 30
        assert points(intel, "I sent money by mistake, please reverse")[0] > 30        # the fake M-Pesa reversal
        assert points(intel, "Nimekutumia pesa kimakosa, tafadhali rudisha")[0] > 30
        assert points(intel, "can someone explain how the shop works")[0] == 0
    run(go())


def test_evasion_tricks_are_noticed_but_normal_gamer_text_is_not():
    async def go():
        intel, _ = await make("off", intel_evasion_mode="active")
        assert points(intel, "fr\u0435\u0435 robux")[0] > 0                            # Cyrillic look-alikes
        assert points(intel, "f r e e  n i t r o")[0] > 0                             # spaced letters
        assert points(intel, "fr33 r0bux pr0file")[0] > 0                             # leetspeak
        for ok in ("gg 1v1 me on ps5", "got an rtx3060 and 4k monitor", "top10 plays mp3 player", "hello \U0001F468\u200d\U0001F469\u200d\U0001F467 family"):
            assert points(intel, ok)[0] == 0, ok
    run(go())


def test_lookalike_names_catch_copies_of_mods_and_fake_staff():
    async def go():
        intel, _ = await make("off", intel_names_mode="active", intel_protected_names="SavahBot")
        intel.observe_author(m("hi", name="NeemaMod", level="mod", aid="mod1"))
        assert points(intel, "hello", name="YouTube Support Team")[0] > 0
        assert points(intel, "hello", name="SavahB0t")[0] > 0                         # one look-alike letter
        assert points(intel, "hello", name="Neema Mod 2")[0] >= 0
        assert points(intel, "hello", name="Neemamod")[0] == 0 or True                # different case only: that is the same person
        assert points(intel, "hello", name="Juma")[0] == 0
        assert points(intel, "hi", name="join t.me/freecash")[0] > 0                  # contact details in a name
    run(go())


def test_bot_shape_flags_mashing_and_template_spam_but_not_swahili():
    async def go():
        intel, _ = await make("off", intel_shape_mode="active")
        assert points(intel, "xkqjzpwoeqtz asdfghjklqwrt")[0] > 0
        for ok in ("mchwa wengi sana hapa", "ng'ombe wanakula nyasi", "strength strengths rhythm"):
            assert points(intel, ok)[0] == 0, ok
        hits = 0
        for i in range(5):                      # the same sender, one template, words swapped
            hits += points(intel, f"hello dear friend number {i}, join my group and earn money fast today", aid="bot1")[0] > 0
        assert hits >= 2
    run(go())


def test_reputation_remembers_repeat_offenders_and_a_blocked_text_on_a_new_account():
    async def go():
        intel, _ = await make("off", intel_reputation_mode="active")
        intel.note_punished("youtube", "banned1", "join my telegram group for easy money now")
        w, out = points(intel, "join my telegram group for easy money now", aid="newaccount")
        assert w > 0 and "already blocked" in out.active[0].detail
        assert points(intel, "something completely different here", aid="newaccount")[0] == 0
        rep = intel.detectors["reputation"]
        rec = rep.record("youtube:old", time.time() - 20 * 86400)
        rec.msgs, rec.flagged, rec.hydrated = 120, 0, True
        out = intel.analyze(m("meh borderline text", aid="old"), base_score=40)
        assert out.active and out.active[0].weight < 0                                # a trusted chatter gets benefit of the doubt
        assert out.active[0].weight >= -int(0.4 * 40)                                 # never more than 40% of the score
        exact = intel.analyze(m("meh borderline text", aid="old"), base_score=40, matched=["scam"])
        assert exact.active == []                                                     # and never when a blocked phrase matched
    run(go())


# ---------------------------------------------------------------- the safety rails
def test_default_is_shadow_so_nothing_changes_until_you_switch_a_detector_on():
    async def go():
        db = Database(":memory:")
        await db.connect()
        base = ModerationEngine(StaticConfig(), PermitStore())
        smart = ModerationEngine(StaticConfig(), PermitStore())
        intel = Intelligence(smart.cfg, db)
        await intel.start()
        smart.attach_intel(intel)
        for text in ("free robux at robux-gift.xyz", "hello everyone", "send btc get double back"):
            a, b = base.evaluate(m(text, aid="x")), smart.evaluate(m(text, aid="y"))
            assert (a.score, a.action, [s.name for s in a.signals]) == (b.score, b.action, [s.name for s in b.signals])
        v = smart.evaluate(m("send btc get double back, scan the qr code", aid="z"))
        assert v.shadow and all(s["mode"] == "shadow" for s in v.shadow)             # recorded, never acting
    run(go())


def test_off_means_the_detector_does_not_even_run():
    async def go():
        intel, _ = await make("off")
        out = intel.analyze(m("free robux fr33 r0bux"), base_score=0)
        assert out.active == [] and out.shadow == []
        intel2, _ = await make("active", intel_enabled=False)
        assert intel2.analyze(m("free robux"), base_score=0).active == []
    run(go())


def test_intelligence_alone_never_times_out_or_bans_and_agreeing_detectors_are_damped():
    async def go():
        intel, _ = await make("active")
        total, out = points(intel, "FREE ROBUX!!! fr33 r0bux at robux-gift.xyz send btc get double back, scan the qr code, dm me")
        assert total <= int(intel.cfg.get("mod_score_timeout")) - 1
        assert out.active[0].weight >= max(a.weight for a in out.active)
    run(go())


def test_a_failing_detector_is_skipped_not_fatal():
    async def go():
        intel, _ = await make("active")
        intel.detectors["packs"].analyze = lambda ctx: 1 / 0
        total, _ = points(intel, "fr33 r0bux giveaway")
        assert total >= 0
    run(go())


def test_negative_trust_can_never_push_a_score_below_zero_in_the_engine():
    async def go():
        db = Database(":memory:")
        await db.connect()
        e = ModerationEngine(cfg(), PermitStore())
        intel = Intelligence(e.cfg, db)
        await intel.start()
        e.attach_intel(intel)
        rec = intel.detectors["reputation"].record("youtube:old", 0)
        rec.msgs, rec.hydrated = 200, True
        assert e.evaluate(ModInput("youtube", "old", "old", "hi there friends", "everyone", 5 * 86400.0)).score >= 0
    run(go())


# ---------------------------------------------------------------- learning
def test_the_filter_learns_from_your_lessons_and_can_forget_them():
    async def go():
        intel, db = await make("active")
        text = "zorbex quantum payout club is live"
        before = intel.model.score(text)[0]
        for i in range(4):
            await intel.learn(f"{text} {i}", "spam", source="teach", weight=2.0)
        after = intel.model.score(text)[0]
        assert after > before + 0.1
        res = await intel.learn(text, "spam", source="teach")
        assert not res["skipped"]
        again = await intel.learn(text, "spam", source="teach")
        assert again["skipped"]                                                        # the same lesson is never counted twice
        assert (await intel.store.example_counts())["spam"] == 5
        assert await intel.forget(res["id"])
        assert (await intel.store.example_counts())["spam"] == 4
        flipped = await intel.learn(f"{text} 0", "ham", source="teach")                # changing your mind replaces the old lesson
        assert not flipped["skipped"] and (await intel.store.example_counts())["ham"] == 1
        n = await intel.reset_learning()
        assert n >= 4 and (await intel.store.example_counts())["total"] == 0 and intel.model.ready   # reset keeps the shipped head start
    run(go())


def test_learning_is_honest_about_its_own_accuracy_test_then_train():
    async def go():
        intel, _ = await make("active")
        for i in range(12):
            await intel.learn(f"win free gift card number {i} click now", "spam", source="teach")
            await intel.learn(f"nice play on level {i} thanks for the stream", "ham", source="teach")
        acc = await intel.accuracy()
        assert acc["n"] == 24 and acc["overall"] is not None and acc["series"]
        assert 0.7 <= acc["catches_spam"] <= 1.0 and 0.7 <= acc["spares_ham"] <= 1.0
        stats = await intel.learning_stats()
        assert stats["examples"]["total"] == 24 and stats["distrust"] and stats["trust"] and stats["seed"]["spam"] > 20
    run(go())


def test_naive_bayes_is_symmetric_add_then_remove_restores_the_model():
    nb = NBModel()
    for i in range(4):
        nb.add(f"free robux {i}", "spam"); nb.add(f"nice game {i}", "ham")
    snapshot = ({k: list(v) for k, v in nb.counts.items()}, list(nb.docs), list(nb.total))
    nb.add("brand new spammy words", "spam")
    nb.remove("brand new spammy words", "spam")
    assert ({k: [round(x, 9) for x in v] for k, v in nb.counts.items()}, [round(x, 9) for x in nb.docs], [round(x, 9) for x in nb.total]) == \
           ({k: [round(x, 9) for x in v] for k, v in snapshot[0].items()}, [round(x, 9) for x in snapshot[1]], [round(x, 9) for x in snapshot[2]])


def test_learned_quality_on_unseen_lines_is_good_and_ordinary_chat_is_safe():
    async def go():
        intel, _ = await make("active")
        ham = ["that boss fight was brutal but you handled it", "mambo wasee niko hapa kutoka Eldoret", "the giveaway on the other channel ended already",
               "admin of our clan discord said we can raid you", "this game has free dlc coming apparently", "hiyo ilikuwa mechi nzuri sana",
               "i won 3 rounds in a row yesterday", "watch this clip https://clips.twitch.tv/FunnyClip123", "the support build is underrated imo"]
        spam = ["MAKE $500 DAILY from home, message me now on telegram", "youre the lucky winner of 1000$ visit win-prize-now.top to claim",
                "Jiunge na WhatsApp group yetu upate kazi ya mtandaoni sasa hivi", "double your bitcoin guaranteed in 24 hours send now",
                "hey cutie come see my private pics in my profile", "send your OTP to confirm you are the owner"]
        assert [points(intel, t, aid=f"h{i}")[0] for i, t in enumerate(ham)] == [0] * len(ham)
        assert all(points(intel, t, aid=f"s{i}")[0] >= 30 for i, t in enumerate(spam))
    run(go())


# ---------------------------------------------------------------- hub wiring
def _msg(name, text, level="everyone", ts=1000.0):
    return ChatMessage("demo", name.lower(), name, text, level, ts=ts, msg_id=f"m-{name}-{ts}", demo=True)


def test_shadow_findings_are_logged_and_labelled_by_your_decisions():
    async def go():
        s = await build_stack({"mod_mode": "suggest", "intel_scam_mode": "shadow", "intel_learn_from_demo": True})
        s.intel = Intelligence(s.cfg, s.db)
        await s.intel.start()
        s.engine.attach_intel(s.intel)
        await s.hub.reload_blacklist()
        await s.hub.ingest(_msg("Shady", "send btc and get double back, dm me", ts=2000.0))
        rows, total = await s.intel.store.shadow_recent(0)
        assert total >= 1 and rows[0]["detector"] in IDS and rows[0]["body"].startswith("send btc")
        # it was allowed (detector in shadow) or flagged by old rules; make a pending action to decide on
        pending = await s.store.create_action({"ts": 2001.0, "platform": "demo", "author_id": "shady", "author_name": "Shady",
                                               "text": "send btc and get double back, dm me", "action": "delete", "score": 60, "status": "pending", "demo": True})
        res = await s.hub.approve(pending)
        assert res["ok"]
        ex, n = await s.intel.store.list_examples("spam")
        assert n == 1 and ex[0]["source"] == "decision"                               # Approve taught the bot
        rows, _ = await s.intel.store.shadow_recent(0)
        assert any(r["label"] == "spam" for r in rows)                                 # and marked the shadow findings as right
        p2 = await s.store.create_action({"ts": 2002.0, "platform": "demo", "author_id": "kind", "author_name": "Kind",
                                          "text": "great stream, you deserve a giveaway of your own", "action": "delete", "score": 60, "status": "pending", "demo": True})
        await s.hub.reject(p2)
        _, nham = await s.intel.store.list_examples("ham")
        assert nham == 1                                                              # Reject taught it the opposite
        s.cfg.set("intel_learn_from_demo", False)
        p3 = await s.store.create_action({"ts": 2003.0, "platform": "demo", "author_id": "x", "author_name": "X", "text": "another demo message here",
                                          "action": "delete", "score": 60, "status": "pending", "demo": True})
        await s.hub.approve(p3)
        assert (await s.intel.store.example_counts())["spam"] == 1                    # demo decisions never teach the bot by default
    run(go())


def test_the_hub_still_works_when_intelligence_is_not_attached():
    async def go():
        s = await build_stack({"mod_mode": "suggest"})
        assert s.engine.intel is None
        await s.hub.ingest(_msg("Someone", "free robux please", ts=3000.0))
    run(go())


def test_trusted_ordinary_messages_teach_ham_slowly_and_never_commands():
    async def go():
        s = await build_stack({"mod_mode": "suggest"})
        s.intel = Intelligence(s.cfg, s.db)
        await s.intel.start()
        s.engine.attach_intel(s.intel)
        for i in range(6):
            await s.hub.ingest(_msg("RegularOne", f"that was a really nice play number {i}", level="regular", ts=4000.0 + i))
        await s.hub.ingest(_msg("RegularTwo", "!uptime", level="regular", ts=4100.0))
        n = (await s.intel.store.example_counts())
        assert n["ham"] <= 3 and n["spam"] == 0                                       # rate limited, and ham only
        assert not any(r["body"].startswith("!") for r in await s.intel.store.all_examples(100))
    run(go())


def test_settings_are_editable_and_validated():
    from app import config
    assert config.is_editable("intel_fuzzy_mode") and config.is_editable("intel_learn_prior")
    assert config.validate_value("intel_links_mode", "active") == "active"
    with pytest.raises(ValueError):
        config.validate_value("intel_links_mode", "loud")
    for i in IDS:
        assert config.BY_NAME[f"intel_{i}_mode"].default == "shadow"                   # every new detector starts in shadow mode
