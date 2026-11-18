"""Knowledge packs: the data model, the loader for the built-in JSON files, and the overlay of the owner's changes.

Built-in packs live in packs/<category>/<name>.json and are read-only. Everything the owner changes (turning a
pack off, adding or disabling a phrase, feed domains, accepted suggestions) is stored in the database and laid
over the built-ins, so updating the app never overwrites the owner's work.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent / "packs"
KINDS = ("phrases", "facets", "domains", "tlds", "words", "domain_regex", "maps", "corpus")
LISTED_KINDS = ("phrases", "domains", "tlds", "words", "domain_regex")  # kinds whose entries can be edited
SIGNALS = ("scam", "spam", "abuse", "harassment", "impersonation")
MODES = ("off", "shadow", "live")
CATEGORIES = {
    "scams": ("Scams", "Giveaways, crypto doublers, fake support and money tricks."),
    "spam": ("Spam", "Self-promotion, sellers and bait."),
    "abuse": ("Abuse", "Profanity, insults, threats and harassment."),
    "links": ("Links and domains", "Shorteners, risky endings, look-alike brands and threat lists."),
    "impersonation": ("Impersonation", "Fake staff names and 'I am the admin' claims."),
    "languages": ("Languages", "Swahili and Sheng phrases."),
    "safe": ("Safe phrases", "Things that must never be flagged."),
    "normalize": ("Normalisation", "How disguised text is turned back into plain letters."),
    "corpus": ("Training examples", "Example messages the statistical models learn from."),
}
_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


class PackError(ValueError):
    pass


@dataclass
class Entry:
    phrase: str
    weight: int | None = None   # None = use the pack's weight
    regex: bool = False
    source: str = "builtin"
    id: int | None = None       # database row id for non-built-in entries
    enabled: bool = True


@dataclass
class Pack:
    id: str
    category: str
    kind: str
    title: str
    description: str
    version: str = "1.0.0"
    lang: str = "en"
    source: str = "SavahBot built-in"
    license: str = ""
    signal: str = ""
    weight: int = 40
    fuzzy: bool = False
    default_mode: str = "live"
    needs_target: bool = False
    role: str = ""
    entries: list[Entry] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)   # facets, maps, examples, ...
    builtin: bool = True

    @property
    def editable(self) -> bool:
        return self.kind in LISTED_KINDS


def parse_entry(raw: Any, pack_id: str = "?") -> Entry:
    weight = None
    if isinstance(raw, (list, tuple)):
        if len(raw) != 2:
            raise PackError(f"{pack_id}: entry {raw!r} must be [phrase, weight]")
        raw, weight = raw
    if not isinstance(raw, str) or not raw.strip():
        raise PackError(f"{pack_id}: empty or non-text entry {raw!r}")
    phrase = raw.strip()
    if len(phrase) > 300:
        raise PackError(f"{pack_id}: entry too long: {phrase[:30]!r}")
    regex = phrase.startswith("re:")
    if regex:
        phrase = phrase[3:]
        try:
            re.compile(phrase)
        except re.error as exc:
            raise PackError(f"{pack_id}: bad regex {phrase!r}: {exc}") from exc
    if weight is not None and (not isinstance(weight, int) or isinstance(weight, bool) or not 1 <= weight <= 100):
        raise PackError(f"{pack_id}: weight for {phrase!r} must be 1-100")
    return Entry(phrase=phrase, weight=weight, regex=regex)


def validate_pack(data: dict[str, Any]) -> Pack:
    pid = str(data.get("id", ""))
    if not _ID.match(pid):
        raise PackError(f"bad pack id {pid!r}")
    kind = data.get("kind")
    if kind not in KINDS:
        raise PackError(f"{pid}: kind must be one of {KINDS}")
    for key in ("title", "description"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise PackError(f"{pid}: missing {key}")
    mode = data.get("default_mode", "live")
    if mode not in MODES:
        raise PackError(f"{pid}: default_mode must be one of {MODES}")
    signal = data.get("signal", "")
    if kind in ("phrases", "facets") and not data.get("signal") and not pid.startswith("safe."):
        raise PackError(f"{pid}: phrase packs need a signal")
    if signal and signal not in SIGNALS:
        raise PackError(f"{pid}: signal must be one of {SIGNALS}")
    weight = data.get("weight", 40)
    if not isinstance(weight, int) or not 0 <= weight <= 100:
        raise PackError(f"{pid}: weight must be 0-100")
    entries: list[Entry] = []
    seen: set[str] = set()
    for raw in data.get("entries", []):
        e = parse_entry(raw, pid)
        key = e.phrase.casefold()
        if key in seen:
            raise PackError(f"{pid}: duplicate entry {e.phrase!r}")
        seen.add(key)
        entries.append(e)
    known = {"id", "kind", "title", "description", "version", "lang", "source", "license", "signal", "weight", "fuzzy",
             "default_mode", "needs_target", "role", "entries", "category"}
    payload = {k: v for k, v in data.items() if k not in known}
    if kind == "facets":
        facets = payload.get("facets")
        if not isinstance(facets, dict) or len(facets) < 2:
            raise PackError(f"{pid}: facets must hold at least two groups")
        for name, words in facets.items():
            if not isinstance(words, list) or not words:
                raise PackError(f"{pid}: facet {name} is empty")
            for w in words:
                parse_entry(w, pid)
        for a in payload.get("anchors", []):
            if a not in facets:
                raise PackError(f"{pid}: anchor {a} is not a facet")
    if kind == "corpus" and not (payload.get("label") in ("spam", "ham") and payload.get("examples")):
        raise PackError(f"{pid}: corpus packs need a label and examples")
    return Pack(
        id=pid, category=pid.split(".")[0], kind=kind, title=data["title"].strip(), description=data["description"].strip(),
        version=str(data.get("version", "1.0.0")), lang=str(data.get("lang", "en")), source=str(data.get("source", "")),
        license=str(data.get("license", "")), signal=signal, weight=weight, fuzzy=bool(data.get("fuzzy", False)),
        default_mode=mode, needs_target=bool(data.get("needs_target", False)), role=str(data.get("role", "")),
        entries=entries, payload=payload,
    )


def load_builtin(root: Path | None = None) -> dict[str, Pack]:
    packs: dict[str, Pack] = {}
    for path in sorted((root or ROOT).glob("*/*.json")):
        try:
            pack = validate_pack(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise PackError(f"{path.parent.name}/{path.name}: {exc}") from exc
        if path.parent.name != pack.category:
            raise PackError(f"{path.name}: id says {pack.category} but the file sits in {path.parent.name}")
        if pack.id in packs:
            raise PackError(f"duplicate pack id {pack.id}")
        packs[pack.id] = pack
    return packs


def effective_entries(pack: Pack, rows: list[dict[str, Any]]) -> list[Entry]:
    """Built-in entries with the owner's overrides applied, plus entries added by the owner, feeds or learning."""
    overlay = {str(r["phrase"]).casefold(): r for r in rows if r.get("source") == "builtin"}
    out: list[Entry] = []
    for e in pack.entries:
        o = overlay.get(e.phrase.casefold())
        if o is None:
            out.append(e)
        elif o.get("enabled"):
            w = o.get("weight")
            out.append(Entry(e.phrase, int(w) if w else e.weight, e.regex, "builtin", o.get("id"), True))
    for r in rows:
        if r.get("source") != "builtin" and r.get("enabled"):
            out.append(Entry(str(r["phrase"]), int(r["weight"]) if r.get("weight") else None, bool(r.get("is_regex")),
                             str(r.get("source", "user")), r.get("id"), True))
    return out
