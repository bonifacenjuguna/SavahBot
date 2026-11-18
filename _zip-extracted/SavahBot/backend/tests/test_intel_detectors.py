"""The intelligence layer through the real moderation engine."""
import time

import pytest

from app.config import StaticConfig
from app.intel import Intel, benchmark
from app.moderation import ModerationEngine, ModInput, PermitStore


def make(overrides=None, blacklist=None, intel=True):
    cfg = StaticConfig(overrides or {})
    permits = PermitStore()
    e = ModerationEngine(cfg, permits)
    if intel:
        e.intel = Intel(cfg, lambda: ["Savah Tech"])
    if blacklist:
        e.set_blacklist(blacklist)
    return e


def check(e, text, name="viewer", level="everyone", stateless=True, uid=None, ts=None):
    return e.evaluate(ModInput("demo", uid or name, name, text, level, ts or time.time()), stateless=stateless)


def names(v):
    return {s.name for s in v.signals}


SPAM = [
    "free robux click my profile", "double your bitcoin send 0.1 btc get 0.2 back", "whatsapp me +254712345678 guaranteed profit",
    "your channel will be removed verify now", "sub4sub i will sub back", "nimekutumia pesa kwa makosa tafadhali rudisha",
    "hot singles near you chat privately click link", "fr33 g1ftcards cl1ck my pr0file", "claim your prize now at the link",
]
HAM = [
    "hello everyone", "gg that was close", "what game is this?", "i will subscribe after the stream", "the game is free on steam",
    "kill streak incoming", "that boss is killing me", "can you share the discord link?", "mambo vipi wasee", "crypto is crashing again lol",
]


@pytest.mark.parametrize("text", SPAM)
def test_spam_is_flagged(text):
    assert check(make(), text).score >= 30


@pytest.mark.parametrize("text", HAM)
def test_normal_chat_is_left_alone(text):
    v = check(make(), text)
    assert v.score < 30 and v.action == "allow", (text, v.to_dict())


def test_benchmark_meets_the_bar():
    e = make()
    r = benchmark.run(e, e.cfg)
    assert r["with_intel"]["recall_flag"] >= 0.95
    assert r["with_intel"]["false_alarm_flag"] <= 0.02
    assert r["with_intel"]["false_alarm_delete"] == 0
    assert r["with_intel"]["recall_flag"] > r["without_intel"]["recall_flag"] + 0.5


def test_benchmark_is_held_out_from_training():
    from app.intel.packs import load_builtin
    cases = benchmark.load_cases()
    trained = {ex.casefold() for p in load_builtin().values() if p.kind == "corpus" for ex in p.payload["examples"]}
    assert not trained & {t.casefold() for t in cases["spam"] + cases["ham"]}


def test_benchmark_restores_the_engine():
    e = make()
    intel = e.intel
    benchmark.run(e, e.cfg)
    assert e.intel is intel


def test_intel_off_is_exactly_the_old_behaviour():
    off = make({"intel_enabled": False})
    old = make(intel=False)
    for t in SPAM + HAM:
        a, b = check(off, t), check(old, t)
        assert (a.score, a.action, names(a)) == (b.score, b.action, names(b)), t


def test_intel_never_bans_on_its_own():
    v = check(make({"intel_abuse_mode": "live"}), "double your bitcoin guaranteed profit whatsapp me +254712345678 free robux claim your prize "
              "send btc get double kys elon musk giveaway")
    intel_weight = sum(s.weight for s in v.signals)
    assert intel_weight <= 60 and v.action != "ban"


def test_shadow_mode_logs_but_never_scores():
    v = check(make({"intel_scam_mode": "shadow"}), "double your bitcoin send 0.1 btc get 0.2 back")
    assert v.score == 0 and "scam" not in names(v)
    assert any(s.name == "scam" for s in v.shadow)


def test_off_mode_does_nothing_at_all():
    v = check(make({"intel_scam_mode": "off"}), "double your bitcoin send 0.1 btc get 0.2 back")
    assert not v.signals and not [s for s in v.shadow if s.name == "scam"]


def test_pack_modes_are_respected():
    e = make()
    e.intel.pack_state["scams.crypto"] = {"mode": "off", "scale": 1.0}
    e.intel.rebuild()
    assert "scam" not in names(check(e, "double your bitcoin now"))


def test_pack_strength_scales_the_score():
    base = check(make(), "claim your prize now").score
    e = make()
    e.intel.pack_state["scams.giveaway"] = {"mode": None, "scale": 0.5}
    e.intel.rebuild()
    assert check(e, "claim your prize now").score < base


def test_blacklist_match_is_corroborated_not_stacked():
    bl = [{"id": 1, "phrase": "free robux", "enabled": 1, "is_regex": 0, "weight": 70}]
    with_intel = check(make(blacklist=bl), "free robux")
    without = check(make(blacklist=bl, intel=False), "free robux")
    assert with_intel.score - without.score <= 15


def test_context_questions_and_warnings_score_lower():
    e = make()
    plain = check(e, "free robux claim your prize").score
    assert check(e, "is free robux a real thing?").score < plain
    assert check(e, "don't click that, free robux is a scam bot").score < plain
    # ...but a warning that still carries a link or phone number is not trusted
    assert check(e, "ignore the bots, whatsapp me +254712345678 for free robux").score >= 30


def test_safe_phrases_protect_gameplay_talk():
    e = make({"intel_abuse_mode": "live"})
    assert not names(check(e, "kill streak, we are going to kill him"))
    assert "harassment" in names(check(e, "go kill yourself"))


def test_insult_is_stronger_when_aimed_at_someone():
    e = make({"intel_abuse_mode": "live"})
    assert check(e, "you are an idiot").score > check(e, "the idiot ball trope is funny").score


def test_typos_and_stretched_letters_are_caught():
    e = make()
    v = check(e, "frree robus click now")
    assert "typo" in names(v) and v.score >= 30
    assert check(e, "double kill").score == 0
    assert check(e, "you have worn that shirt before").score == 0   # short words must match exactly


def test_typo_matching_covers_your_own_blocklist():
    bl = [{"id": 1, "phrase": "zorbnikcoin", "enabled": 1, "is_regex": 0, "weight": 0}]
    e = make(blacklist=bl)
    assert "typo" in names(check(e, "buy zorbnikcoyn today"))
    assert check(e, "hello there").score == 0


def test_link_intelligence():
    e = make()
    assert "link_risk" in names(check(e, "verify at youtub3.com/login"))
    assert "link_risk" in names(check(e, "claim here bit.ly/abc"))
    assert "link_risk" in names(check(e, "go to http://192.168.4.4/x"))
    assert "link_risk" not in names(check(e, "watch https://youtube.com/watch?v=abc"))
    assert "link_risk" not in names(check(e, "see github.com/someone/repo"))


def test_allowed_and_permitted_links_are_trusted():
    e = make({"mod_allowed_domains": "bit.ly"})
    assert "link_risk" not in names(check(e, "claim here bit.ly/abc"))
    e2 = make()
    e2.permits.permit("viewer", 300, now=time.time()) if hasattr(e2.permits, "permit") else None
    if hasattr(e2.permits, "permit"):
        assert "link_risk" not in names(check(e2, "claim here bit.ly/abc"))


def test_your_own_domain_is_protected_from_lookalikes():
    e = make({"intel_protected_domains": "savahtech.com"})
    assert "link_risk" in names(check(e, "log in at savahtekh.com"))
    assert "link_risk" not in names(check(e, "see savahtech.com/about"))


def test_impersonation_of_the_streamer_and_staff():
    e = make({"intel_protected_names": "Savah Tech"})
    assert "impersonation" in names(check(e, "hi", name="SavahTech"))
    assert "impersonation" in names(check(e, "hi", name="Savah_Tech_Support"))
    assert "impersonation" in names(check(e, "hi", name="Official YouTube Support"))
    assert "impersonation" in names(check(e, "i am the admin of this stream, send me your details"))
    assert "impersonation" not in names(check(e, "hi", name="Wanjiru"))
    assert "impersonation" not in names(check(e, "hi", name="Savah123"))   # a fan with a number is not an impostor


def test_owner_and_mods_are_never_judged():
    e = make({"intel_protected_names": "Savah Tech"})
    assert check(e, "free robux claim your prize", level="owner").score == 0
    assert check(e, "free robux claim your prize", level="mod").score == 0


def test_text_tricks():
    e = make()
    assert "obfuscation" in names(check(e, "fr\u0435e r\u043ebux now"))                       # Cyrillic look-alikes inside Latin words
    assert "obfuscation" in names(check(e, "he\u200bl\u200bl\u200bo\u200b there"))             # hidden characters
    assert "obfuscation" in names(check(e, "h\u0300\u0301\u0302\u0303e\u0300\u0301\u0302\u0303l\u0300\u0301\u0302\u0303l\u0300\u0301\u0302\u0303o\u0300\u0301\u0302\u0303"))
    assert "obfuscation" not in names(check(e, "\u043f\u0440\u0438\u0432\u0435\u0442 \u0434\u0440\u0443\u0437\u044c\u044f"))   # plain Russian is fine


def test_bot_like_names_are_a_shadow_hint_by_default():
    v = check(make(), "hello", name="user83749201")
    assert not v.signals and any(s.name == "bot_like" for s in v.shadow)
    live = check(make({"intel_bot_like_mode": "live"}), "hello", name="user83749201")
    assert "bot_like" in names(live)


def test_statistical_detectors_are_shadow_by_default_and_explain_themselves():
    e = make()
    v = check(e, "guaranteed daily profit join vip group now")
    shadow = {s.name: s for s in v.shadow}
    assert "intent" in shadow and "spam-like" in shadow["intent"].detail
    reacts = e.intel.probe("guaranteed daily profit join vip group now")
    assert "intent" in reacts or "scam" in reacts


def test_known_spam_similarity_finds_reworded_copies():
    e = make({"intel_known_spam_mode": "live"})
    v = check(e, "claim your free gift card at the link below please")
    assert "known_spam" in names(v) or v.score >= 30


def test_language_packs_follow_the_setting():
    text = "tuma pesa kwa namba hii upate mara mbili"
    with_sw = check(make({"intel_languages": "en,sw"}), text).score
    without = check(make({"intel_languages": "en"}), text).score
    assert with_sw > without


def test_raid_wave_boosts_suspicious_new_accounts_only():
    e = make({"intel_wave_accounts": 4, "intel_wave_window_seconds": 30})
    t = 1_000_000.0
    for i in range(4):
        check(e, f"hello number {i}", name=f"newbie{i}", stateless=False, uid=f"n{i}", ts=t + i)
    assert e.intel.pop_wave_started() and not e.intel.pop_wave_started()
    sus = check(e, "claim your prize now", name="late1", stateless=False, uid="late1", ts=t + 6)
    calm = check(e, "nice stream everyone", name="late2", stateless=False, uid="late2", ts=t + 7)
    assert "raid_wave" in names(sus) and "raid_wave" not in names(calm)


def test_verdict_carries_confidence_and_plain_explanations():
    e = make()
    weak = check(e, "check my channel")
    strong = check(e, "double your bitcoin, whatsapp me +254712345678, hurry guaranteed profit, bit.ly/x")
    d = strong.to_dict()
    assert 0 <= weak.confidence < strong.confidence <= 1
    assert d["signals"] and all(s["why"] for s in d["signals"]) and "shadow" in d
    plain = check(make(intel=False), "buy zorbnik now", ).to_dict()
    assert plain["confidence"] == 0 and plain["signals"] == []


def test_evaluation_stays_fast():
    e = make()
    started = time.perf_counter()
    for i in range(300):
        check(e, SPAM[i % len(SPAM)] + f" {i}")
        check(e, HAM[i % len(HAM)] + f" {i}")
    assert time.perf_counter() - started < 8
