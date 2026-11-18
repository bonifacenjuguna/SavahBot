"""Every built-in knowledge pack must load, validate and be consistent with the settings."""
import json
import re

import pytest

from app.config import BY_NAME, ENUMS
from app.intel import DETECTORS
from app.intel import packs as P
from app.intel.packs import Entry, PackError, effective_entries, load_builtin, validate_pack

ALL = load_builtin()


def _ok(**kw):
    base = {"id": "spam.test", "kind": "phrases", "title": "t", "description": "d", "signal": "spam", "entries": ["hello there"]}
    return base | kw


def test_all_builtin_packs_load():
    assert len(ALL) >= 38
    for cat in ("scams", "spam", "abuse", "links", "impersonation", "languages", "safe", "normalize", "corpus"):
        assert any(p.category == cat for p in ALL.values()), cat
    assert sum(len(p.entries) for p in ALL.values()) > 1400


def test_every_category_has_a_description():
    assert {p.category for p in ALL.values()} <= set(P.CATEGORIES)


def test_every_pack_file_matches_its_id_and_folder():
    for path in P.ROOT.glob("*/*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["id"] == f"{path.parent.name}.{path.stem}"


def test_every_regex_compiles_and_weights_are_sane():
    for p in ALL.values():
        for e in p.entries:
            if e.regex:
                re.compile(e.phrase)
            assert e.weight is None or 1 <= e.weight <= 100, (p.id, e.phrase)
        assert 0 <= p.weight <= 100


def test_no_entry_normalises_to_nothing_or_one_letter():
    """A phrase made only of symbols would normalise to an empty string and match every message."""
    from app.intel.textkit import deep_normalize
    for p in ALL.values():
        if p.kind != "phrases" or p.category == "safe":
            continue
        for e in p.entries:
            if not e.regex:
                assert len(deep_normalize(e.phrase).replace(" ", "")) >= 3, (p.id, e.phrase)


def test_detectors_match_settings():
    for d in DETECTORS:
        assert f"intel_{d}_mode" in BY_NAME and f"intel_{d}_scale" in BY_NAME
        assert ENUMS[f"intel_{d}_mode"] == ["off", "shadow", "live"]
    assert ENUMS["intel_learning_mode"] == ["off", "suggest", "auto"]


def test_phrase_pack_signals_have_detectors():
    for p in ALL.values():
        if p.kind == "phrases" and p.category != "safe":
            assert p.signal in DETECTORS, p.id


def test_shipped_defaults_are_conservative():
    """New behaviour that could annoy a streamer must start in shadow mode."""
    assert BY_NAME["intel_abuse_mode"].default == "shadow"
    assert BY_NAME["intel_intent_mode"].default == "shadow"
    assert BY_NAME["intel_max_weight"].default <= 60
    assert BY_NAME["intel_harassment_mode"].default == "live"   # threats should never wait
    assert ALL["scams.testimonials"].default_mode == "shadow"


def test_validate_rejects_bad_packs():
    with pytest.raises(PackError):
        validate_pack(_ok(id="BadId"))
    with pytest.raises(PackError):
        validate_pack(_ok(kind="nonsense"))
    with pytest.raises(PackError):
        validate_pack(_ok(entries=["same", "SAME"]))
    with pytest.raises(PackError):
        validate_pack(_ok(entries=["re:(unclosed"]))
    with pytest.raises(PackError):
        validate_pack(_ok(entries=[["x phrase", 500]]))
    with pytest.raises(PackError):
        validate_pack(_ok(signal="bogus"))
    with pytest.raises(PackError):
        validate_pack(_ok(default_mode="loud"))
    with pytest.raises(PackError):
        validate_pack(_ok(signal=""))
    with pytest.raises(PackError):
        validate_pack({"id": "spam.facets", "kind": "facets", "title": "t", "description": "d", "signal": "scam", "facets": {"a": ["x"]}})


def test_effective_entries_overlay():
    pack = validate_pack(_ok(entries=["alpha one", ["beta two", 30], "gamma three"]))
    rows = [
        {"id": 1, "pack_id": pack.id, "phrase": "Alpha One", "source": "builtin", "enabled": 0, "weight": 0, "is_regex": 0},   # disabled
        {"id": 2, "pack_id": pack.id, "phrase": "beta two", "source": "builtin", "enabled": 1, "weight": 80, "is_regex": 0},   # re-weighted
        {"id": 3, "pack_id": pack.id, "phrase": "delta four", "source": "user", "enabled": 1, "weight": 0, "is_regex": 0},
        {"id": 4, "pack_id": pack.id, "phrase": "epsilon", "source": "user", "enabled": 0, "weight": 0, "is_regex": 0},
    ]
    got = {e.phrase: e for e in effective_entries(pack, rows)}
    assert set(got) == {"beta two", "gamma three", "delta four"}
    assert got["beta two"].weight == 80 and got["gamma three"].weight is None
    assert got["delta four"].source == "user"


def test_parse_entry_forms():
    assert P.parse_entry("hello") == Entry("hello")
    e = P.parse_entry(["re:a+b", 40])
    assert e.regex and e.weight == 40 and e.phrase == "a+b"


def test_facet_pack_is_well_formed():
    f = ALL["scams.intent_facets"]
    assert f.kind == "facets" and set(f.payload["anchors"]) <= set(f.payload["facets"])
    # common everyday words must not be facet words, or normal chat would score as scam
    flat_words = {w for words in f.payload["facets"].values() for w in words if not w.startswith("re:")}
    assert not flat_words & {"now", "today", "send", "join", "link", "free", "message", "text", "contact", "channel"}
