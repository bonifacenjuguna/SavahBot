from app.config import StaticConfig
from app.moderation import ModerationEngine, ModInput, PermitStore
from app.moderation.ahocorasick import AhoCorasick
from app.moderation.engine import BlacklistMatcher
from app.moderation.normalize import canon, normalize
from app.moderation.trackers import SlidingWindowCounter, hamming, simhash

BLACKLIST = [
    {"id": 1, "phrase": "free robux", "enabled": True, "is_regex": False, "weight": 0},
    {"id": 2, "phrase": "scam", "enabled": True, "is_regex": False, "weight": 0},
    {"id": 3, "phrase": "crypto giveaway", "enabled": True, "is_regex": False, "weight": 0},
]


def make_engine(**overrides):
    e = ModerationEngine(StaticConfig(overrides), PermitStore())
    e.set_blacklist(BLACKLIST)
    return e


def msg(text, author="u1", level="everyone", ts=1000.0):
    return ModInput("demo", author, author, text, level, ts)


# ---------------------------------------------------------------- normalisation
def test_normalize_handles_leet_homoglyphs_and_stretching():
    target = normalize("free robux")
    assert normalize("Fr33 R0bux!!!") == target
    assert normalize("frее robux") == target  # Cyrillic 'е'
    assert normalize("fr​ee robux") == target  # zero-width space
    assert normalize("FREEEEE ROBUX") == target
    assert normalize("𝐟𝐫𝐞𝐞 𝐫𝐨𝐛𝐮𝐱") == target  # maths-bold letters


def test_canon_ignores_random_numbers():
    assert canon("Join my giveaway 4821!!") == canon("join my giveaway 9033!!")


# ---------------------------------------------------------------- aho-corasick
def test_aho_corasick_classic_example():
    ac = AhoCorasick()
    for p in ["he", "she", "his", "hers"]:
        ac.add(p, p)
    found = sorted(p for _, p, _ in ac.build().search("ushers"))
    assert found == ["he", "hers", "she"]


def test_aho_corasick_overlapping_and_empty():
    ac = AhoCorasick()
    ac.add("aa", 1)
    assert len(ac.search("aaaa")) == 3
    assert AhoCorasick().search("anything") == []


# ---------------------------------------------------------------- blacklist matching
def test_blacklist_matches_disguised_text():
    m = BlacklistMatcher()
    m.rebuild(BLACKLIST)
    assert {h["id"] for h in m.scan("get FR33 R0BUX here")} == {1}
    assert {h["id"] for h in m.scan("f r e e   r o b u x now")} == {1}
    assert {h["id"] for h in m.scan("cryрto giveaway tonight")} == {3}  # Cyrillic 'р'
    assert {h["id"] for h in m.scan("this is a sc@m!")} == {2}


def test_short_phrases_respect_word_boundaries():
    m = BlacklistMatcher()
    m.rebuild(BLACKLIST)
    assert m.scan("I love scampi") == []
    assert m.scan("what a lovely day") == []


def test_regex_entries_and_disabled_entries():
    m = BlacklistMatcher()
    m.rebuild([
        {"id": 9, "phrase": r"bit\.ly/\w+", "is_regex": True, "enabled": True},
        {"id": 10, "phrase": "off", "is_regex": False, "enabled": False},
        {"id": 11, "phrase": "([", "is_regex": True, "enabled": True},  # invalid regex is ignored
    ])
    assert [h["id"] for h in m.scan("go to bit.ly/abc")] == [9]
    assert m.scan("this is off") == []


# ---------------------------------------------------------------- trackers
def test_sliding_window_counts_only_recent_events():
    w = SlidingWindowCounter()
    assert [w.hit("a", t, 10) for t in (0, 1, 2)] == [1, 2, 3]
    assert w.hit("a", 20, 10) == 1


def test_simhash_similar_vs_unrelated():
    a = simhash("join my giveaway channel for free subs 123")
    b = simhash("join my giveaway channel for free subs 987")
    c = simhash("what game is this by the way, looks fun")
    assert hamming(a, b) == 0
    assert hamming(a, c) > 12


# ---------------------------------------------------------------- verdicts
def test_normal_chat_is_allowed():
    e = make_engine()
    for i, t in enumerate(["hello everyone!", "gg that was close", "what game is this?", "LET'S GOOO"]):
        v = e.evaluate(msg(t, f"viewer{i}", ts=1000 + i))
        assert v.action == "allow", (t, v.reasons)


def test_blacklist_from_established_user_is_deleted():
    e = make_engine()
    e.evaluate(msg("hi", "bob", ts=0))
    v = e.evaluate(msg("get free robux now", "bob", ts=500))  # no longer a new chatter
    assert v.action == "delete" and v.score == 70
    assert v.signals[0].name == "blacklist"


def test_blacklist_plus_link_from_new_account_is_a_ban_candidate():
    e = make_engine()
    v = e.evaluate(msg("FREE ROBUX at robux-gift.xyz right now everybody", "spambot1"))
    assert v.action == "ban"
    names = {s.name for s in v.signals}
    assert {"blacklist", "link", "new_chatter"} <= names


def test_links_allowed_domain_disguise_and_permit():
    e = make_engine()
    assert e.evaluate(msg("watch https://youtu.be/abc123", "a1")).action == "allow"
    v = e.evaluate(msg("visit cheapviews dot shop today", "a2"))
    assert any(s.name == "link" for s in v.signals)
    e.permits.permit("Alice", 60, now=1000)
    assert not any(s.name == "link" for s in e.evaluate(msg("see www.example.org", "Alice", ts=1010)).signals)
    assert any(s.name == "link" for s in e.evaluate(msg("see www.example.org", "Bob", ts=1010)).signals)


def test_caps_alone_flags_but_caps_plus_stretching_deletes():
    e = make_engine()
    e.evaluate(msg("hi", "vet", ts=0))
    only_caps = e.evaluate(msg("THIS STREAM IS ABSOLUTELY INCREDIBLE", "vet", ts=500))
    assert only_caps.action == "flag" and only_caps.score == 30
    shout = e.evaluate(msg("WOOOOOOOOOOOOW THIS IS SO COOL LETS GO", "vet", ts=501))
    assert shout.action == "delete"


def test_copy_paste_raid_is_caught_from_the_fourth_account():
    e = make_engine()
    text = "join my giveaway channel for free subs {}"
    actions = [e.evaluate(msg(text.format(1000 + i), f"raider{i}", ts=2000 + i)).action for i in range(6)]
    assert actions[:3] == ["allow"] * 3
    assert all(a == "delete" for a in actions[3:])


def test_flood_from_new_account_is_deleted():
    e = make_engine()
    acts = [e.evaluate(msg(f"message number {c}", "flooder", ts=3000 + i * 0.3)).action
            for i, c in enumerate("abcdef")]
    assert acts[:3] == ["allow"] * 3
    assert acts[3:] == ["delete"] * 3


def test_exact_repeats_escalate_to_flag():
    e = make_engine()
    acts = [e.evaluate(msg("buy my cool thing", "dupe", ts=4000 + i)).action for i in range(3)]
    assert acts == ["allow", "flag", "flag"]


def test_machine_regular_timing_is_detected():
    e = make_engine()
    last = None
    topics = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"]  # distinct: no duplicate signal
    for i, word in enumerate(topics):  # one message every 6s: slow enough that the rate limiter stays quiet
        last = e.evaluate(msg(f"giveaway round {word}", "metronome", ts=5000 + i * 6.0))
    names = {s.name for s in last.signals}
    assert "timing" in names and "rate" not in names
    assert last.action == "flag"  # timing (30) + new chatter (15) = 45: logged, not punished


def test_humans_with_irregular_timing_are_not_flagged():
    e = make_engine()
    last = None
    for ts in (0, 7, 8, 31, 33, 70, 71):
        last = e.evaluate(msg(f"thought number {ts}", "human", ts=6000 + ts))
    assert not any(s.name == "timing" for s in last.signals)


def test_exempt_levels_and_regulars():
    e = make_engine()
    for level in ("owner", "mod", "regular", "bot"):
        v = e.evaluate(msg("FREE ROBUX at robux-gift.xyz NOW NOW NOW", "x", level=level))
        assert v.exempt and v.action == "allow"
    assert not e.evaluate(msg("FREE ROBUX at robux-gift.xyz NOW NOW NOW", "x", level="member")).exempt


def test_strikes_escalate_delete_to_timeout_to_ban():
    e = make_engine()
    key = "demo:repeat"
    e.evaluate(msg("hi", "repeat", ts=0))
    e.add_strike(key, 100)
    e.add_strike(key, 101)
    v = e.evaluate(msg("get free robux", "repeat", ts=500))
    assert v.action == "timeout" and v.duration == 60
    e.add_strike(key, 502)
    e.add_strike(key, 503)
    assert e.evaluate(msg("get free robux again", "repeat", ts=504)).action == "ban"
    # strikes decay
    assert e.strikes(key, now=100000) == 0


def test_stateless_mode_records_nothing():
    e = make_engine()
    v = e.evaluate(msg("get free robux", "tester"), stateless=True)
    assert v.action in ("delete", "flag") and v.score >= 70
    assert e.rate._events == {} and e.behavior._state == {}


def test_settings_change_behaviour_live():
    cfg = StaticConfig()
    e = ModerationEngine(cfg)
    e.set_blacklist(BLACKLIST)
    e.evaluate(msg("hi", "p", ts=0))
    assert e.evaluate(msg("get free robux", "p", ts=500)).action == "delete"
    cfg.set("mod_blacklist_enabled", False)
    assert e.evaluate(msg("get free robux", "p", ts=501)).action == "allow"
