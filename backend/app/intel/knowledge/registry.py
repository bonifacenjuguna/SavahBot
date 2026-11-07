"""Knowledge packs: one JSON file per category, loaded and validated here.

A pack is plain data (phrases, scam shapes, risky link parts, disguise maps, a training set...). The detectors hold
the algorithms; the packs hold what they know. Splitting them keeps each file small and lets you switch a whole
category on or off, add your own entries, or mute single ones, all without touching a pack file.

A pack file looks like:
    {"id": "spam-promo", "title": "...", "description": "...", "category": "spam", "kind": "phrases",
     "language": "en", "version": "2026.11.1", "updated": "2026-11-06", "sources": [{"title": "...", "url": "..."}],
     "user_supplied": false, "entries": [...]  or  "data": {...}}
A broken pack is reported in `problems` and skipped. It can never stop the bot from starting.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("savahbot.intel")

PACK_DIR = Path(__file__).parent / "packs"

# kind -> what consumes it
KINDS = {
    "phrases": "Banned or suspicious phrases, matched exactly and fuzzily.",
    "templates": "Shapes of known scam messages (several weak hints add up).",
    "linkrisk": "Risky link parts: shorteners, bad endings, brands to guard.",
    "confusables": "Extra look-alike letters and leetspeak for fuzzy matching.",
    "identity": "Words that make a chatter name look official.",
    "corpus": "Labelled example messages that give the learning filter a head start.",
}
CATEGORIES = {
    "spam": "Spam", "scams": "Scams", "links": "Links", "evasion": "Disguises",
    "identity": "Identity", "learning": "Learning", "custom": "Yours",
}
EDITABLE_KINDS = {"phrases", "identity"}   # kinds where you can add or mute single entries
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")
MAX_ENTRIES = 20000


@dataclass
class Pack:
    id: str
    title: str
    description: str
    category: str
    kind: str
    language: str = "en"
    version: str = ""
    updated: str = ""
    sources: list[dict[str, str]] = field(default_factory=list)
    user_supplied: bool = False
    entries: list[Any] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def editable(self) -> bool:
        return self.kind in EDITABLE_KINDS


@dataclass
class Row:
    """One browsable line of a pack, whatever the kind of pack."""
    value: str
    weight: int = 0
    tags: list[str] = field(default_factory=list)
    user: bool = False
    muted: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "weight": self.weight, "tags": self.tags, "user": self.user, "muted": self.muted, "note": self.note}


def _entry(raw: Any) -> tuple[str, int, list[str]]:
    """A phrase entry is a string or {"p": phrase, "w": weight, "tags": [...]}."""
    if isinstance(raw, str):
        return raw.strip(), 0, []
    return str(raw.get("p", "")).strip(), int(raw.get("w", 0) or 0), [str(t) for t in raw.get("tags", [])]


class PackRegistry:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or PACK_DIR
        self.packs: dict[str, Pack] = {}
        self.problems: list[str] = []
        self.disabled: set[str] = set()
        self.added: dict[str, dict[str, int]] = {}      # pack id -> {value: weight}
        self.muted: dict[str, set[str]] = {}            # pack id -> {value}
        self.revision = 0                                # bumps on any change so detectors know to rebuild

    # ------------------------------------------------------------------ loading
    def load(self) -> None:
        self.packs, self.problems = {}, []
        for path in sorted(self.directory.glob("*.json")):
            try:
                pack = self._read(path)
            except Exception as exc:  # a broken file must never take the bot down
                self.problems.append(f"{path.name}: {exc}")
                logger.warning("Skipping knowledge pack %s: %s", path.name, exc)
                continue
            if pack.id in self.packs:
                self.problems.append(f"{path.name}: duplicate id {pack.id}")
                continue
            self.packs[pack.id] = pack
        self.revision += 1

    @staticmethod
    def _read(path: Path) -> Pack:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("the file must hold one JSON object")
        pid = str(raw.get("id", ""))
        if not _ID.match(pid):
            raise ValueError("id must be lowercase letters, digits and dashes")
        kind = raw.get("kind")
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {sorted(KINDS)}")
        category = raw.get("category", "custom")
        if category not in CATEGORIES:
            raise ValueError(f"category must be one of {sorted(CATEGORIES)}")
        entries = raw.get("entries", [])
        data = raw.get("data", {})
        if not isinstance(entries, list) or not isinstance(data, dict):
            raise ValueError("entries must be a list and data an object")
        if len(entries) > MAX_ENTRIES:
            raise ValueError(f"too many entries (limit {MAX_ENTRIES})")
        if kind == "templates":
            for g in data.get("groups", []):
                for pat in g.get("patterns", []):
                    re.compile(pat)
        if kind == "corpus":
            for e in entries:
                if not isinstance(e, dict) or e.get("l") not in ("spam", "ham") or not str(e.get("t", "")).strip():
                    raise ValueError("corpus entries look like {\"t\": text, \"l\": \"spam\" or \"ham\"}")
        sources = [{"title": str(s.get("title", "")), "url": str(s.get("url", ""))} for s in raw.get("sources", []) if isinstance(s, dict)]
        return Pack(id=pid, title=str(raw.get("title", pid)), description=str(raw.get("description", "")), category=category, kind=kind,
                    language=str(raw.get("language", "en")), version=str(raw.get("version", "")), updated=str(raw.get("updated", "")),
                    sources=sources, user_supplied=bool(raw.get("user_supplied", False)), entries=entries, data=data)

    # ------------------------------------------------------------------ your changes
    def apply_state(self, disabled: set[str], added: list[dict[str, Any]], muted: list[dict[str, Any]]) -> None:
        self.disabled = set(disabled)
        self.added, self.muted = {}, {}
        for r in added:
            self.added.setdefault(r["pack"], {})[r["value"]] = int(r.get("weight") or 0)
        for r in muted:
            self.muted.setdefault(r["pack"], set()).add(r["value"])
        self.revision += 1

    def set_enabled(self, pack_id: str, enabled: bool) -> None:
        (self.disabled.discard if enabled else self.disabled.add)(pack_id)
        self.revision += 1

    def enabled(self, pack_id: str) -> bool:
        return pack_id in self.packs and pack_id not in self.disabled

    # ------------------------------------------------------------------ what detectors read
    def active(self, kind: str) -> list[Pack]:
        return [p for p in self.packs.values() if p.kind == kind and p.id not in self.disabled]

    def phrase_entries(self) -> list[tuple[Pack, str, int, list[str]]]:
        """Every live phrase: (pack, text, weight 0-100 or 0 for the pack default, tags). Muted ones are left out, yours are added."""
        out: list[tuple[Pack, str, int, list[str]]] = []
        for p in self.active("phrases"):
            muted = self.muted.get(p.id, set())
            for raw in p.entries:
                text, weight, tags = _entry(raw)
                if text and text not in muted:
                    out.append((p, text, weight, tags))
            for text, weight in self.added.get(p.id, {}).items():
                if text not in muted:
                    out.append((p, text, weight, ["yours"]))
        return out

    def identity_terms(self) -> list[str]:
        terms: list[str] = []
        for p in self.active("identity"):
            muted = self.muted.get(p.id, set())
            terms += [t for t in (_entry(e)[0] for e in p.entries) if t and t not in muted]
            terms += [t for t in self.added.get(p.id, {}) if t not in muted]
        return terms

    def identity_entries(self) -> list[tuple[str, int]]:
        """(term, weight 0-100) for every live identity term, yours included."""
        out: list[tuple[str, int]] = []
        for p in self.active("identity"):
            muted = self.muted.get(p.id, set())
            for raw in p.entries:
                text, weight, _ = _entry(raw)
                if text and text not in muted:
                    out.append((text, weight or 50))
            out += [(t, w or 50) for t, w in self.added.get(p.id, {}).items() if t not in muted]
        return out

    def template_groups(self) -> list[dict[str, Any]]:
        return [g for p in self.active("templates") for g in p.data.get("groups", [])]

    def linkrisk(self) -> dict[str, Any]:
        """All enabled link-risk packs merged into one lookup."""
        out: dict[str, Any] = {"shorteners": set(), "tld_high": set(), "tld_medium": set(), "brands": {}, "scam_words": set(), "safe": set()}
        for p in self.active("linkrisk"):
            d = p.data
            out["shorteners"] |= {x.lower() for x in d.get("shorteners", [])}
            out["tld_high"] |= {x.lower() for x in d.get("risky_tlds", {}).get("high", [])}
            out["tld_medium"] |= {x.lower() for x in d.get("risky_tlds", {}).get("medium", [])}
            out["scam_words"] |= {x.lower() for x in d.get("scam_words", [])}
            out["safe"] |= {x.lower() for x in d.get("safe_domains", [])}
            for brand, domains in d.get("brands", {}).items():
                out["brands"].setdefault(brand.lower(), set()).update(x.lower() for x in domains)
        return out

    def confusables(self) -> tuple[dict[str, str], dict[str, str]]:
        single: dict[str, str] = {}
        multi: dict[str, str] = {}
        for p in self.active("confusables"):
            single.update({k: v for k, v in p.data.get("map", {}).items() if len(k) == 1})
            multi.update({k: v for k, v in p.data.get("multi", {}).items() if len(k) > 1})
        return single, multi

    def corpus(self) -> list[tuple[str, str]]:
        return [(str(e["t"]), e["l"]) for p in self.active("corpus") for e in p.entries]

    # ------------------------------------------------------------------ browsing (dashboard)
    def rows(self, pack_id: str) -> list[Row]:
        p = self.packs[pack_id]
        muted = self.muted.get(p.id, set())
        rows: list[Row] = []
        if p.kind in ("phrases", "identity"):
            for raw in p.entries:
                text, weight, tags = _entry(raw)
                if text:
                    rows.append(Row(text, weight, tags, muted=text in muted))
            for text, weight in self.added.get(p.id, {}).items():
                rows.append(Row(text, weight, ["yours"], user=True, muted=text in muted))
        elif p.kind == "templates":
            for g in p.data.get("groups", []):
                rows.append(Row(str(g.get("title", g.get("id", ""))), int(g.get("w", 0)), ["strong"] if g.get("strong") else [], note=f"{len(g.get('patterns', []))} patterns. {g.get('note', '')}".strip()))
        elif p.kind == "linkrisk":
            d = p.data
            rows += [Row(x, 0, ["shortener"]) for x in d.get("shorteners", [])]
            rows += [Row(f".{x}", 0, ["risky ending", "high"]) for x in d.get("risky_tlds", {}).get("high", [])]
            rows += [Row(f".{x}", 0, ["risky ending", "medium"]) for x in d.get("risky_tlds", {}).get("medium", [])]
            rows += [Row(b, 0, ["guarded brand"], note=", ".join(ds)) for b, ds in d.get("brands", {}).items()]
            rows += [Row(x, 0, ["scam word"]) for x in d.get("scam_words", [])]
            rows += [Row(x, 0, ["always safe"]) for x in d.get("safe_domains", [])]
        elif p.kind == "confusables":
            rows += [Row(f"{k}  becomes  {v}", 0, ["letter"]) for k, v in p.data.get("map", {}).items()]
            rows += [Row(f"{k}  becomes  {v}", 0, ["pair"]) for k, v in p.data.get("multi", {}).items()]
        elif p.kind == "corpus":
            rows += [Row(str(e["t"]), 0, [e["l"]]) for e in p.entries]
        return rows

    def count(self, pack_id: str) -> int:
        return len(self.rows(pack_id))

    def summary(self) -> list[dict[str, Any]]:
        out = []
        for p in self.packs.values():
            rows = self.rows(p.id)
            out.append({
                "id": p.id, "title": p.title, "description": p.description, "category": p.category, "kind": p.kind,
                "kind_help": KINDS[p.kind], "language": p.language, "version": p.version, "updated": p.updated, "sources": p.sources,
                "enabled": p.id not in self.disabled, "entries": len(rows), "yours": sum(1 for r in rows if r.user),
                "muted": sum(1 for r in rows if r.muted), "editable": p.editable, "user_supplied": p.user_supplied,
            })
        return out
