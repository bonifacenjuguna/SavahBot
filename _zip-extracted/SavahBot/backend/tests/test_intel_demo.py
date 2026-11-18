"""The demo scenarios for the intelligence layer, run with the layer switched on."""
import asyncio

from helpers import build_stack

from app.services.demo import SCENARIOS


def run(coro):
    return asyncio.run(coro)


def flagged(s):
    return [m for m in s.hub.buffer if m["verdict"] != "allow"]


async def play(name, **kw):
    s = await build_stack(intel=True, **kw)
    await s.demo.run_scenario(name)
    return s


def test_new_scenarios_are_registered():
    new = {"scam_wave", "typo_scam", "lookalike_links", "impersonator", "art_spam", "swahili_scam", "raid_wave",
           "warnings_and_questions", "gaming_talk"}
    assert new <= set(SCENARIOS)
    for name in SCENARIOS:
        assert hasattr(__import__("app.services.demo", fromlist=["DemoSource"]).DemoSource, f"_sc_{name}"), name


def test_friendly_chat_stays_clean_with_intel_on_for_many_seeds():
    async def go():
        for seed in range(8):
            s = await build_stack(intel=True, seed_value=seed)
            await s.demo.run_scenario("friendly_chat")
            assert not flagged(s), [m["text"] for m in flagged(s)]
    run(go())


def test_attack_scenarios_are_caught_message_by_message():
    async def go():
        for name in ("scam_wave", "typo_scam", "lookalike_links", "impersonator", "art_spam", "swahili_scam"):
            s = await play(name)
            texts = [(m["text"], m["verdict"]) for m in s.hub.buffer]
            assert texts and all(v != "allow" for _, v in texts), (name, texts)
    run(go())


def test_the_calm_scenarios_flag_nothing():
    async def go():
        for name in ("warnings_and_questions", "gaming_talk"):
            s = await play(name)
            assert len(s.hub.buffer) == 4 and not flagged(s), (name, [(m["text"], m["score"]) for m in flagged(s)])
    run(go())


def test_scam_wave_reaches_delete_level_and_queues_actions():
    async def go():
        s = await play("scam_wave")
        assert sum(1 for m in s.hub.buffer if m["verdict"] in ("delete", "timeout", "ban")) >= 3
        pending = await s.store.pending_actions(True)
        assert pending and all(any(r.split(":")[0] in ("scam", "link_risk") for r in p["reasons"]) for p in pending)
    run(go())


def test_raid_wave_boosts_the_late_suspicious_account_only():
    async def go():
        s = await play("raid_wave")
        late = [m for m in s.hub.buffer if m["text"] in ("claim your prize now", "nice stream everyone")]
        assert late[0]["verdict"] != "allow" and late[1]["verdict"] == "allow"
        assert s.intel.waves_seen == 1
        # the same suspicious line without a wave scores lower
        calm = await build_stack(intel=True)
        n, a = calm.demo._newcomer("lateguest")
        await calm.demo._post(n, a, "claim your prize now")
        assert calm.hub.buffer[-1]["score"] < late[0]["score"]
    run(go())


def test_wave_notice_goes_to_telegram_outside_demo_only():
    async def go():
        s = await play("raid_wave")
        assert not [t for t, _ in s.notes if "Raid wave" in t]      # demo traffic never pings the owner's phone
    run(go())


def test_old_scenarios_still_behave_with_intel_on():
    async def go():
        s = await play("link_spammer")
        assert s.hub.buffer[-1]["verdict"] in ("delete", "timeout", "ban")
        s = await play("disguised_words")
        assert s.hub.buffer[-1]["verdict"] != "allow"
        s = await play("spam_raid")
        assert sum(m["verdict"] != "allow" for m in s.hub.buffer) >= 3     # the same three the raid detector caught in 1.1.5
        s = await play("caps_flood")
        assert s.hub.buffer[-1]["verdict"] != "allow"
    run(go())


def test_mixed_scenario_still_runs_end_to_end():
    async def go():
        s = await play("mixed")
        assert len(s.hub.buffer) > 15 and any(m["verdict"] != "allow" for m in s.hub.buffer)
    run(go())
