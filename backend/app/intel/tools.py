"""Knowledge tools: pack health checks, hit analytics and the whole-Knowledge bundle (export / import).

Everything here is read-mostly and honest: health findings are computed from the packs as they are right now, hit counts come
from the real counters the engine keeps, and a bundle carries a checksum so a damaged or edited file is refused.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from ..store import ValidationFailed
from . import benchmark
from .packs import effective_entries
from .textkit import flat

BUNDLE_FORMAT = "savahbot-knowledge"
MAX_BUNDLE_ENTRIES = 20000


def _norm(p: str) -> str:
    return re.sub(r"\s+", " ", flat(p)).strip()


def pack_health(knowledge: Any) -> dict[str, Any]:
    """Look through every editable pack for things that usually cause trouble: repeats, one-word triggers, and phrases that
    show up inside the known-good benchmark messages (so they would flag normal chat)."""
    intel = knowledge.intel
    ham = [_norm(t) for t in benchmark.load_cases()["ham"]]
    seen_in: dict[str, list[str]] = {}
    findings: list[dict[str, Any]] = []
    packs_checked = 0
    for pack in intel.packs.values():
        if not pack.editable:
            continue
        packs_checked += 1
        local: set[str] = set()
        for e in effective_entries(pack, intel.rows.get(pack.id, [])):
            if e.regex or not e.enabled:
                continue
            key = _norm(e.phrase)
            if not key:
                continue
            if key in local:
                findings.append({"kind": "duplicate", "pack": pack.id, "phrase": e.phrase, "why": "Listed twice in this pack."})
            local.add(key)
            seen_in.setdefault(key, []).append(pack.id)
            if len(key.split()) == 1 and len(key) < 5:
                findings.append({"kind": "short", "pack": pack.id, "phrase": e.phrase,
                                 "why": "A very short single word matches inside many ordinary messages."})
            if any(re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", h) for h in ham):
                findings.append({"kind": "ham-hit", "pack": pack.id, "phrase": e.phrase,
                                 "why": "This phrase appears in a message that is known to be normal chat."})
    for key, packs in seen_in.items():
        if len(set(packs)) > 1:
            findings.append({"kind": "overlap", "pack": ", ".join(sorted(set(packs))), "phrase": key,
                             "why": "The same phrase sits in more than one pack, so it is counted twice."})
    order = {"ham-hit": 0, "short": 1, "duplicate": 2, "overlap": 3}
    findings.sort(key=lambda f: (order[f["kind"]], f["pack"], f["phrase"]))
    return {"checked": packs_checked, "total": len(findings), "findings": findings[:200],
            "by_kind": {k: sum(1 for f in findings if f["kind"] == k) for k in order}}


async def hit_stats(knowledge: Any) -> dict[str, Any]:
    """How often each detector has fired for real (saved counters plus what is waiting in memory)."""
    rows = await knowledge.db.fetchall("SELECT name, value FROM counters WHERE name LIKE 'intel:%'")
    totals = {r["name"][6:]: int(r["value"]) for r in rows}
    for name, n in knowledge.intel.pending.items():
        totals[name] = totals.get(name, 0) + int(n)
    ranked = sorted(({"name": k, "hits": v} for k, v in totals.items()), key=lambda d: -d["hits"])
    return {"total": sum(totals.values()), "detectors": ranked}


def _checksum(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def export_bundle(knowledge: Any, include_lessons: bool = True) -> dict[str, Any]:
    intel = knowledge.intel
    packs = {pid: {"mode": st.get("mode"), "scale": st.get("scale", 1.0)} for pid, st in intel.pack_state.items()}
    entries: list[dict[str, Any]] = []
    for pid, rows in intel.rows.items():
        for r in rows:
            if str(r.get("source", "")).startswith("feed:") or r.get("source") == "builtin":
                continue
            entries.append({"pack": pid, "phrase": r["phrase"], "regex": bool(r.get("is_regex")), "weight": int(r.get("weight") or 0),
                            "enabled": bool(r.get("enabled", 1))})
    lessons = (await knowledge.learning.ledger.export())["lessons"] if include_lessons and knowledge.learning else []
    body = {"packs": packs, "entries": entries, "lessons": lessons}
    return {"format": BUNDLE_FORMAT, "version": 1, "exported": int(time.time()), "sha256": _checksum(body), **body}


def check_bundle(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("format") != BUNDLE_FORMAT:
        raise ValidationFailed("That file is not a SavahBot Knowledge bundle.")
    body = {k: data.get(k) for k in ("packs", "entries", "lessons")}
    if not isinstance(body["packs"], dict) or not isinstance(body["entries"], list) or not isinstance(body["lessons"], list):
        raise ValidationFailed("The bundle is incomplete.")
    if data.get("sha256") != _checksum(body):
        raise ValidationFailed("The bundle's checksum does not match. The file was changed or damaged, so nothing was imported.")
    if len(body["entries"]) > MAX_BUNDLE_ENTRIES:
        raise ValidationFailed(f"The bundle has more than {MAX_BUNDLE_ENTRIES} entries.")
    return body


async def import_bundle(knowledge: Any, data: Any, dry_run: bool = False) -> dict[str, Any]:
    """Merge a bundle into this install. With dry_run it only reports what would change."""
    body = check_bundle(data)
    intel = knowledge.intel
    unknown = [p for p in body["packs"] if p not in intel.packs]
    by_pack: dict[str, list[dict[str, Any]]] = {}
    for e in body["entries"]:
        if isinstance(e, dict) and e.get("pack") in intel.packs and isinstance(e.get("phrase"), str):
            by_pack.setdefault(e["pack"], []).append(e)
    report = {"dry_run": dry_run, "pack_settings": len([p for p in body["packs"] if p in intel.packs]), "unknown_packs": unknown,
              "entries": sum(len(v) for v in by_pack.values()), "lessons": len(body["lessons"])}
    if dry_run:
        return report
    added = skipped = 0
    for pid, items in by_pack.items():
        # Entries of one pack and weight go together, so each distinct weight is one call
        groups: dict[int, list[str]] = {}
        for e in items:
            phrase = ("re:" + e["phrase"]) if e.get("regex") and not e["phrase"].startswith("re:") else e["phrase"]
            groups.setdefault(int(e.get("weight") or 0), []).append(phrase)
        for w, phrases in groups.items():
            try:
                res = await knowledge.add_entries(pid, phrases, w, source="import")
                added += res["added"]
                skipped += res["skipped"]
            except ValidationFailed:
                skipped += len(phrases)
    for pid, st in body["packs"].items():
        if pid in intel.packs and isinstance(st, dict):
            try:
                await knowledge.set_pack(pid, st.get("mode") or "", float(st.get("scale") or 1.0))
            except (ValidationFailed, ValueError):
                pass
    lessons = {"added": 0, "skipped": 0}
    if body["lessons"] and knowledge.learning:
        lessons = await knowledge.learning.ledger.import_lessons({"format": "savahbot-lessons", "lessons": body["lessons"]})
        await knowledge.learning.retrain()
    return {**report, "entries_added": added, "entries_skipped": skipped, "lessons_added": lessons["added"]}
