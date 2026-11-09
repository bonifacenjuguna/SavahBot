"""Knowledge management: everything the dashboard's Knowledge section does, on top of the database.

The Intel object is synchronous and database-free so it stays fast and testable. This service loads the owner's
changes from the database into it, applies edits (then rebuilds it), and builds the views the dashboard shows.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from ..store import ValidationFailed
from .bayes import BM25
from .core import DETECTORS, Intel
from .packs import CATEGORIES, KINDS, LISTED_KINDS, MODES, Pack, effective_entries, parse_entry

logger = logging.getLogger("savahbot.intel")

MAX_USER_ENTRIES = 5000
_HOST = re.compile(r"^[a-z0-9][a-z0-9\-\.]{0,251}\.[a-z0-9\-]{2,24}$")


def clean_entry(pack: Pack, raw: str) -> tuple[str, bool]:
    """Validate and normalise one entry for this kind of pack. Returns (phrase, is_regex)."""
    s = (raw or "").strip()
    if not s:
        raise ValidationFailed("Type something to add.")
    if len(s) > 200:
        raise ValidationFailed("Entries can be at most 200 characters.")
    if pack.kind == "domains":
        s = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", s.lower()).split("/")[0].split("?")[0].split(":")[0].strip(".")
        s = s[4:] if s.startswith("www.") else s
        if not _HOST.match(s):
            raise ValidationFailed("Enter a domain such as example.com.")
        return s, False
    if pack.kind == "tlds":
        s = s.lower().lstrip(".")
        if not re.fullmatch(r"[a-z]{2,24}", s):
            raise ValidationFailed("Enter an ending such as xyz (letters only).")
        return s, False
    if pack.kind == "words":
        s = s.lower()
        if not re.fullmatch(r"[a-z0-9]{2,30}", s):
            raise ValidationFailed("Enter one word, letters and digits only.")
        return s, False
    regex = s.startswith("re:") or pack.kind == "domain_regex"
    if regex:
        body = s[3:] if s.startswith("re:") else s
        try:
            re.compile(body)
        except re.error as exc:
            raise ValidationFailed(f"That pattern is not valid: {exc}") from exc
        return body, True
    return re.sub(r"\s+", " ", s), False


class Knowledge:
    def __init__(self, db: Any, cfg: Any, intel: Intel, store: Any = None) -> None:
        self.db, self.cfg, self.intel, self.store = db, cfg, intel, store
        self.learning: Any = None
        self.feeds: Any = None
        self._last_flush = 0.0
        self._last_purge = 0.0
        self._last_learn = 0.0

    # ------------------------------------------------------------------ loading
    async def load(self) -> None:
        state = {r["id"]: {"mode": r["mode"] or None, "scale": r["scale"] or 1.0}
                 for r in await self.db.fetchall("SELECT id, mode, scale FROM knowledge_packs")}
        rows = await self.db.fetchall(
            "SELECT e.id, e.pack_id, e.phrase, e.is_regex, e.weight, e.enabled, e.source FROM knowledge_entries e "
            "LEFT JOIN knowledge_feeds f ON e.source = 'feed:' || f.id "
            "WHERE e.source NOT LIKE 'feed:%' OR (f.enabled = 1 AND e.gen = f.gen)")
        self.intel.load_state(state, rows)

    # ------------------------------------------------------------------ packs
    def _pack(self, pack_id: str) -> Pack:
        pack = self.intel.packs.get(pack_id)
        if pack is None:
            raise KeyError(pack_id)
        return pack

    def pack_info(self, pack: Pack) -> dict[str, Any]:
        rows = self.intel.rows.get(pack.id, [])
        entries = effective_entries(pack, rows) if pack.editable else []
        mode = self.intel.pack_mode(pack)
        override = self.intel.pack_state.get(pack.id, {}).get("mode")
        n_user = sum(1 for r in rows if r.get("source") != "builtin")
        count = len(entries)
        if pack.kind == "facets":
            count = sum(len(v) for v in pack.payload["facets"].values())
        elif pack.kind == "corpus":
            count = len(pack.payload["examples"])
        elif pack.kind == "maps":
            count = len(pack.payload.get("letters", {})) + len(pack.payload.get("sequences", []))
        return {
            "id": pack.id, "category": pack.category, "title": pack.title, "description": pack.description, "kind": pack.kind,
            "lang": pack.lang, "signal": pack.signal, "role": pack.role, "version": pack.version, "source": pack.source,
            "license": pack.license, "weight": pack.weight, "fuzzy": pack.fuzzy, "needs_target": pack.needs_target,
            "mode": mode, "default_mode": pack.default_mode, "overridden": bool(override),
            "scale": self.intel.pack_scale(pack.id), "entries": count, "entries_builtin": len(pack.entries),
            "entries_added": n_user, "editable": pack.editable,
            "language_off": mode == "off" and (self.intel.pack_state.get(pack.id, {}).get("mode") or pack.default_mode) != "off",
        }

    def categories(self) -> list[dict[str, Any]]:
        out = []
        for cid, (title, about) in CATEGORIES.items():
            packs = [self.pack_info(p) for p in self.intel.packs.values() if p.category == cid]
            if packs:
                out.append({"id": cid, "title": title, "about": about, "packs": packs,
                            "entries": sum(p["entries"] for p in packs),
                            "active": sum(1 for p in packs if p["mode"] != "off")})
        return out

    async def set_pack(self, pack_id: str, mode: str | None = None, scale: float | None = None) -> dict[str, Any]:
        pack = self._pack(pack_id)
        cur = self.intel.pack_state.get(pack_id, {"mode": None, "scale": 1.0})
        new_mode = cur.get("mode") if mode is None else (mode or None)
        if new_mode is not None and new_mode not in MODES:
            raise ValidationFailed(f"Mode must be one of {', '.join(MODES)}.")
        new_scale = cur.get("scale", 1.0) if scale is None else float(scale)
        if not 0.1 <= new_scale <= 3.0:
            raise ValidationFailed("Strength must be between 0.1 and 3.")
        await self.db.execute(
            "INSERT INTO knowledge_packs (id, mode, scale, updated) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET mode = excluded.mode, scale = excluded.scale, updated = excluded.updated",
            (pack_id, new_mode or "", new_scale, time.time()))
        self.intel.pack_state[pack_id] = {"mode": new_mode, "scale": new_scale}
        self.intel.rebuild()
        return self.pack_info(pack)

    # ------------------------------------------------------------------ entries
    def entry_list(self, pack_id: str, q: str = "", offset: int = 0, limit: int = 60, only: str = "") -> dict[str, Any]:
        pack = self._pack(pack_id)
        if not pack.editable:
            raise ValidationFailed("This pack is not a list of entries.")
        rows = self.intel.rows.get(pack_id, [])
        overlay = {str(r["phrase"]).casefold(): r for r in rows if r.get("source") == "builtin"}
        items: list[dict[str, Any]] = []
        for e in pack.entries:
            o = overlay.get(e.phrase.casefold())
            items.append({"phrase": e.phrase, "regex": e.regex, "builtin": True, "source": "builtin",
                          "enabled": True if o is None else bool(o["enabled"]),
                          "weight": (int(o["weight"]) if o and o.get("weight") else e.weight) or pack.weight,
                          "default_weight": e.weight or pack.weight, "edited": o is not None})
        for r in rows:
            if r.get("source") != "builtin":
                items.append({"phrase": r["phrase"], "regex": bool(r.get("is_regex")), "builtin": False,
                              "source": r["source"], "enabled": bool(r["enabled"]),
                              "weight": int(r["weight"] or 0) or pack.weight, "default_weight": pack.weight, "edited": False})
        if only == "added":
            items = [i for i in items if not i["builtin"]]
        elif only == "off":
            items = [i for i in items if not i["enabled"]]
        elif only == "edited":
            items = [i for i in items if i["edited"]]
        q = (q or "").strip()
        if q:
            ql = q.casefold()
            if len(items) <= 2500:
                bm = BM25().build([(i, it["phrase"]) for i, it in enumerate(items)], tokenizer=lambda t: re.findall(r"\w+", t.casefold()))
                ranked = [k for _, k in bm.search(q, top=len(items))]
                seen = set(ranked)
                ranked += [i for i, it in enumerate(items) if i not in seen and ql in it["phrase"].casefold()]
                items = [items[i] for i in ranked]
            else:
                items = [it for it in items if ql in it["phrase"].casefold()]
        total = len(items)
        return {"pack": self.pack_info(pack), "total": total, "offset": offset, "items": items[offset:offset + limit]}

    async def add_entries(self, pack_id: str, phrases: list[str], weight: int = 0, source: str = "user") -> dict[str, Any]:
        pack = self._pack(pack_id)
        if not pack.editable:
            raise ValidationFailed("This pack is not a list of entries.")
        if not 0 <= weight <= 100:
            raise ValidationFailed("Weight must be between 0 and 100.")
        existing = {e.phrase.casefold() for e in effective_entries(pack, self.intel.rows.get(pack_id, []))}
        rows = self.intel.rows.get(pack_id, [])
        have = sum(1 for r in rows if r.get("source") != "builtin")
        added, skipped, bad = 0, 0, []
        for raw in phrases:
            if not (raw or "").strip():
                continue
            try:
                phrase, is_regex = clean_entry(pack, raw)
            except ValidationFailed as exc:
                bad.append(f"{raw[:30]}: {exc}")
                continue
            if phrase.casefold() in existing:
                skipped += 1
                continue
            if have + added >= MAX_USER_ENTRIES:
                raise ValidationFailed(f"A pack can hold at most {MAX_USER_ENTRIES} added entries.")
            await self.db.execute(
                "INSERT INTO knowledge_entries (pack_id, phrase, is_regex, weight, enabled, source, gen, created) "
                "VALUES (?, ?, ?, ?, 1, ?, 0, ?) ON CONFLICT (pack_id, phrase, source, gen) DO UPDATE SET enabled = 1, weight = excluded.weight",
                (pack_id, phrase, int(is_regex), weight, source, time.time()))
            existing.add(phrase.casefold())
            added += 1
        if added:
            await self.load()
        if not added and bad and not skipped:
            raise ValidationFailed(bad[0])
        return {"added": added, "skipped": skipped, "problems": bad[:5], "pack": self.pack_info(pack)}

    async def set_entry(self, pack_id: str, phrase: str, enabled: bool | None = None, weight: int | None = None) -> dict[str, Any]:
        pack = self._pack(pack_id)
        if weight is not None and not 0 <= weight <= 100:
            raise ValidationFailed("Weight must be between 0 and 100.")
        key = phrase.casefold()
        builtin = next((e for e in pack.entries if e.phrase.casefold() == key), None)
        if builtin is not None:
            cur = next((r for r in self.intel.rows.get(pack_id, []) if r.get("source") == "builtin" and str(r["phrase"]).casefold() == key), None)
            new_enabled = (bool(cur["enabled"]) if cur else True) if enabled is None else enabled
            new_weight = (int(cur["weight"]) if cur else 0) if weight is None else weight
            await self.db.execute(
                "INSERT INTO knowledge_entries (pack_id, phrase, is_regex, weight, enabled, source, gen, created) "
                "VALUES (?, ?, ?, ?, ?, 'builtin', 0, ?) ON CONFLICT (pack_id, phrase, source, gen) DO UPDATE SET "
                "enabled = excluded.enabled, weight = excluded.weight",
                (pack_id, builtin.phrase, int(builtin.regex), new_weight, int(new_enabled), time.time()))
        else:
            row = next((r for r in self.intel.rows.get(pack_id, []) if r.get("source") != "builtin" and str(r["phrase"]).casefold() == key), None)
            if row is None:
                raise KeyError(phrase)
            await self.db.execute(
                "UPDATE knowledge_entries SET enabled = ?, weight = ? WHERE id = ?",
                (int(bool(row["enabled"]) if enabled is None else enabled), int(row["weight"] or 0) if weight is None else weight, row["id"]))
        await self.load()
        return {"ok": True}

    async def remove_entry(self, pack_id: str, phrase: str) -> dict[str, Any]:
        """Added entries are deleted. A built-in entry cannot be deleted; this resets it to its default instead."""
        self._pack(pack_id)
        key = phrase.casefold()
        ids = [int(r["id"]) for r in self.intel.rows.get(pack_id, []) if str(r["phrase"]).casefold() == key]  # SQL lower() only folds ASCII
        for i in ids:
            await self.db.execute("DELETE FROM knowledge_entries WHERE id = ?", (i,))
        await self.load()
        return {"ok": True, "removed": len(ids)}

    def export_text(self, pack_id: str) -> str:
        pack = self._pack(pack_id)
        lines = [f"# {pack.title} ({pack.id}, v{pack.version})", f"# {pack.description}", ""]
        for e in effective_entries(pack, self.intel.rows.get(pack_id, [])):
            lines.append(("re:" if e.regex else "") + e.phrase + (f"\t{e.weight}" if e.weight else ""))
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ detectors
    async def counters(self) -> dict[str, int]:
        rows = await self.db.fetchall("SELECT name, value FROM counters WHERE name LIKE 'intel:%'")
        out = {r["name"]: int(r["value"]) for r in rows}
        for k, v in self.intel.pending.items():
            out[f"intel:{k}"] = out.get(f"intel:{k}", 0) + v
        return out

    async def detectors(self) -> list[dict[str, Any]]:
        counts = await self.counters()
        out = []
        for did, meta in DETECTORS.items():
            packs = [{"id": p.id, "title": p.title} for p in self.intel.packs.values() if p.signal == did and p.category != "safe"]
            out.append({
                "id": did, "title": meta["title"], "about": meta["about"], "example": meta["example"],
                "mode": str(self.cfg.get(f"intel_{did}_mode")), "scale": float(self.cfg.get(f"intel_{did}_scale")),
                "learned_scale": round(self.intel.learned_scale.get(did, 1.0), 2),
                "default_mode": self._default(f"intel_{did}_mode"), "packs": packs,
                "live_hits": counts.get(f"intel:live:{did}", 0), "shadow_hits": counts.get(f"intel:shadow:{did}", 0),
            })
        return out

    @staticmethod
    def _default(name: str) -> Any:
        from ..config import BY_NAME
        return BY_NAME[name].default

    async def set_detector(self, did: str, mode: str | None = None, scale: float | None = None) -> dict[str, Any]:
        if did not in DETECTORS:
            raise KeyError(did)
        if mode is not None:
            if mode not in MODES:
                raise ValidationFailed(f"Mode must be one of {', '.join(MODES)}.")
            await self.cfg.set(f"intel_{did}_mode", mode)
        if scale is not None:
            if not 0.1 <= float(scale) <= 3.0:
                raise ValidationFailed("Strength must be between 0.1 and 3.")
            await self.cfg.set(f"intel_{did}_scale", float(scale))
        return next(d for d in await self.detectors() if d["id"] == did)

    # ------------------------------------------------------------------ overview and test lab
    async def overview(self) -> dict[str, Any]:
        st = self.intel.status()
        dets = await self.detectors()
        pending = await self.db.fetchone("SELECT COUNT(*) AS n FROM knowledge_suggestions WHERE status = 'new'")
        feeds = self.feeds.summary() if self.feeds else {"enabled": 0, "total": 0}
        modes = {m: sum(1 for d in dets if d["mode"] == m) for m in MODES}
        nxt = None
        if pending and pending["n"]:
            nxt = {"kind": "suggestions", "text": f"{pending['n']} suggestion{'s' if pending['n'] != 1 else ''} from your decisions are waiting for a look."}
        else:
            shadow_busy = max(dets, key=lambda d: d["shadow_hits"], default=None)
            if shadow_busy and shadow_busy["mode"] == "shadow" and shadow_busy["shadow_hits"] >= 5:
                nxt = {"kind": "shadow", "text": f"{shadow_busy['title']} is in shadow mode and has noticed {shadow_busy['shadow_hits']} messages. Review them before switching it on."}
        return {"status": st, "detector_modes": modes, "detectors": dets, "next": nxt, "feeds": feeds,
                "recent_shadow": list(self.intel.recent_shadow)[:12], "categories": [
                    {"id": c["id"], "title": c["title"], "entries": c["entries"], "active": c["active"], "packs": len(c["packs"])}
                    for c in self.categories()], "version": 1}

    def test(self, text: str, author: str = "tester") -> dict[str, Any]:
        return self.intel.trace(text, author)

    # ------------------------------------------------------------------ background work
    async def tick(self, now: float) -> None:
        if now - self._last_flush >= 60:
            self._last_flush = now
            await self.flush()
        if self.feeds is not None:
            await self.feeds.tick(now)
        if self.learning is not None and now - self._last_purge >= 86400:
            self._last_purge = now
            await self.learning.ledger.purge(now)
        if self.learning is not None and self.cfg.get("intel_learning_mode") != "off" and now - self._last_learn >= 3600:
            self._last_learn = now
            await self.learning.refresh()

    async def flush(self) -> None:
        """Persist the detector hit counters gathered in memory."""
        if not self.intel.pending or self.store is None:
            return
        pending, self.intel.pending = self.intel.pending, type(self.intel.pending)()
        for name, n in pending.items():
            await self.store.counter_add(f"intel:{name}", n)
