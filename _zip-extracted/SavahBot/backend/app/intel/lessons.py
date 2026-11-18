"""The lesson ledger: every example the bot has been taught, kept in the database.

A "lesson" is one message with one label: `spam` (this was a problem) or `ham` (this was fine). Lessons come from
your Approve and Reject decisions, from "teach the bot" buttons, from trusted regulars chatting normally, and from imports.

Why a ledger instead of only a trained model:
  * you can see, search, relabel and forget any single lesson (the model is rebuilt from what is left),
  * snapshots can be taken before big changes and restored,
  * each lesson remembers what the model predicted BEFORE it learned it (`pred`), so accuracy is measured honestly on
    messages the model had not yet seen, never on its own training data.
"""
from __future__ import annotations

import json
import time
from typing import Any

from ..db import register_schema
from .textkit import flat

register_schema([
    """CREATE TABLE IF NOT EXISTS learning_lessons (
        id {PK}, ts {REAL} NOT NULL, label TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'teach', body TEXT NOT NULL,
        flat TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT '', action_id INTEGER, pred {REAL},
        active INTEGER NOT NULL DEFAULT 1, demo INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '')""",
    "CREATE INDEX IF NOT EXISTS idx_lessons_active ON learning_lessons (active, ts)",
    "CREATE INDEX IF NOT EXISTS idx_lessons_flat ON learning_lessons (flat)",
    """CREATE TABLE IF NOT EXISTS learning_snapshots (
        id {PK}, ts {REAL} NOT NULL, name TEXT NOT NULL, count INTEGER NOT NULL, payload TEXT NOT NULL)""",
])

LABELS = ("spam", "ham")
SOURCES = ("decision", "teach", "trusted", "import", "migrated", "queue")
MAX_TEXT = 300
MAX_SNAPSHOTS = 8


class Ledger:
    def __init__(self, db: Any, cfg: Any) -> None:
        self.db, self.cfg = db, cfg

    # ------------------------------------------------------------------ reading
    async def active(self, limit: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM learning_lessons WHERE active = 1 ORDER BY ts DESC, id DESC"
        return await self.db.fetchall(sql + (f" LIMIT {int(limit)}" if limit else ""))

    async def get(self, lesson_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM learning_lessons WHERE id = ?", (lesson_id,))

    async def counts(self) -> dict[str, Any]:
        rows = await self.db.fetchall("SELECT label, source, COUNT(*) AS n FROM learning_lessons WHERE active = 1 GROUP BY label, source")
        by_label = {"spam": 0, "ham": 0}
        by_source: dict[str, int] = {}
        for r in rows:
            by_label[r["label"]] = by_label.get(r["label"], 0) + r["n"]
            by_source[r["source"]] = by_source.get(r["source"], 0) + r["n"]
        return {"total": sum(by_label.values()), "spam": by_label["spam"], "ham": by_label["ham"], "by_source": by_source}

    async def search(self, label: str = "", source: str = "", q: str = "", offset: int = 0, limit: int = 40) -> dict[str, Any]:
        where, params = ["active = 1"], []
        if label in LABELS:
            where.append("label = ?")
            params.append(label)
        if source in SOURCES:
            where.append("source = ?")
            params.append(source)
        if q.strip():
            where.append("LOWER(body) LIKE ?")
            params.append(f"%{q.strip().lower()[:80]}%")
        clause = " AND ".join(where)
        total = (await self.db.fetchone(f"SELECT COUNT(*) AS n FROM learning_lessons WHERE {clause}", params))["n"]
        rows = await self.db.fetchall(
            f"SELECT id, ts, label, source, body, author, pred, demo, note FROM learning_lessons WHERE {clause} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
            [*params, max(1, min(limit, 200)), max(0, offset)])
        return {"total": total, "offset": offset, "items": rows}

    # ------------------------------------------------------------------ writing
    async def add(self, body: str, label: str, source: str, *, author: str = "", action_id: int | None = None,
                  pred: float | None = None, demo: bool = False, ts: float | None = None) -> dict[str, Any]:
        """Add a lesson. Returns {"status": "added" | "duplicate" | "relabelled", "id": ...}. Never raises on bad input; the caller validates."""
        text = (body or "").strip()[:MAX_TEXT]
        key = flat(text)
        if label not in LABELS or not key:
            return {"status": "skipped", "id": None}
        existing = await self.db.fetchone("SELECT id, label FROM learning_lessons WHERE active = 1 AND flat = ? ORDER BY id DESC", (key,))
        status = "added"
        if existing:
            if existing["label"] == label:
                return {"status": "duplicate", "id": existing["id"]}
            await self.db.execute("UPDATE learning_lessons SET active = 0, note = 'replaced by a newer decision' WHERE id = ?", (existing["id"],))
            status = "relabelled"
        new_id = await self.db.insert(
            "INSERT INTO learning_lessons (ts, label, source, body, flat, author, action_id, pred, demo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts if ts is not None else time.time(), label, source if source in SOURCES else "teach", text, key, (author or "")[:60], action_id,
             pred, 1 if demo else 0))
        await self._enforce_cap()
        return {"status": status, "id": new_id}

    async def _enforce_cap(self) -> None:
        cap = max(100, int(self.cfg.get("intel_example_cap")))
        n = (await self.db.fetchone("SELECT COUNT(*) AS n FROM learning_lessons WHERE active = 1"))["n"]
        if n > cap:  # forget the oldest first; they stay in the table (inactive) until retention removes them
            await self.db.execute(
                "UPDATE learning_lessons SET active = 0, note = 'forgotten: over the example limit' WHERE id IN "
                "(SELECT id FROM learning_lessons WHERE active = 1 ORDER BY ts ASC, id ASC LIMIT ?)", (n - cap,))

    async def forget(self, lesson_id: int) -> bool:
        return (await self.db.execute("UPDATE learning_lessons SET active = 0, note = 'forgotten by you' WHERE id = ? AND active = 1", (lesson_id,))) > 0

    async def relabel(self, lesson_id: int) -> dict[str, Any] | None:
        row = await self.get(lesson_id)
        if not row or not row["active"]:
            return None
        new = "ham" if row["label"] == "spam" else "spam"
        await self.db.execute("UPDATE learning_lessons SET label = ?, note = 'relabelled by you', pred = NULL WHERE id = ?", (new, lesson_id))
        return await self.get(lesson_id)

    async def purge(self, now: float) -> int:
        """Delete forgotten lessons and, if a retention is set, active ones older than it. Returns how many were removed."""
        removed = await self.db.execute("DELETE FROM learning_lessons WHERE active = 0 AND ts < ?", (now - 30 * 86400,))
        days = int(self.cfg.get("intel_lesson_retention_days"))
        if days > 0:
            removed += await self.db.execute("DELETE FROM learning_lessons WHERE ts < ?", (now - days * 86400,))
        return removed

    # ------------------------------------------------------------------ analytics
    async def accuracy(self, since: float, until: float | None = None) -> dict[str, Any]:
        """Prequential accuracy: how often the model's guess, made BEFORE it learned a lesson, matched the label."""
        until = until if until is not None else time.time() + 1
        rows = await self.db.fetchall(
            "SELECT label, pred FROM learning_lessons WHERE pred IS NOT NULL AND demo = 0 AND ts >= ? AND ts < ?", (since, until))
        tp = fp = tn = fn = 0
        for r in rows:
            guess_spam = r["pred"] >= 0.5
            if r["label"] == "spam":
                tp, fn = tp + guess_spam, fn + (not guess_spam)
            else:
                fp, tn = fp + guess_spam, tn + (not guess_spam)
        n = tp + fp + tn + fn
        return {"n": n, "accuracy": round((tp + tn) / n, 3) if n else None,
                "precision": round(tp / (tp + fp), 3) if tp + fp else None, "recall": round(tp / (tp + fn), 3) if tp + fn else None,
                "false_alarms": fp, "missed": fn}

    async def timeline(self, days: int = 30, now: float | None = None) -> list[dict[str, Any]]:
        now = now if now is not None else time.time()
        since = now - days * 86400
        rows = await self.db.fetchall("SELECT ts, label FROM learning_lessons WHERE active = 1 AND ts >= ?", (since,))
        by_day: dict[int, dict[str, int]] = {}
        for r in rows:
            d = int((r["ts"] - since) // 86400)
            by_day.setdefault(d, {"spam": 0, "ham": 0})[r["label"]] += 1
        return [{"day": int(since + d * 86400), "spam": by_day.get(d, {}).get("spam", 0), "ham": by_day.get(d, {}).get("ham", 0)} for d in range(days)]

    # ------------------------------------------------------------------ snapshots
    async def snapshot(self, name: str, now: float | None = None) -> dict[str, Any]:
        rows = await self.active()
        payload = json.dumps([{"ts": r["ts"], "label": r["label"], "source": r["source"], "body": r["body"], "author": r["author"],
                               "demo": r["demo"]} for r in rows], separators=(",", ":"))
        sid = await self.db.insert("INSERT INTO learning_snapshots (ts, name, count, payload) VALUES (?, ?, ?, ?)",
                                   (now if now is not None else time.time(), (name or "Snapshot")[:60], len(rows), payload))
        old = await self.db.fetchall("SELECT id FROM learning_snapshots ORDER BY ts DESC, id DESC LIMIT -1 OFFSET ?", (MAX_SNAPSHOTS,)) \
            if self.db.backend == "sqlite" else await self.db.fetchall("SELECT id FROM learning_snapshots ORDER BY ts DESC, id DESC OFFSET ?", (MAX_SNAPSHOTS,))
        for r in old:
            await self.db.execute("DELETE FROM learning_snapshots WHERE id = ?", (r["id"],))
        return {"id": sid, "name": name, "count": len(rows)}

    async def snapshots(self) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT id, ts, name, count FROM learning_snapshots ORDER BY ts DESC, id DESC")

    async def restore(self, snapshot_id: int) -> int | None:
        snap = await self.db.fetchone("SELECT payload FROM learning_snapshots WHERE id = ?", (snapshot_id,))
        if not snap:
            return None
        items = json.loads(snap["payload"])
        await self.db.execute("UPDATE learning_lessons SET active = 0, note = 'replaced by a restored snapshot' WHERE active = 1")
        for it in items:
            await self.add(it["body"], it["label"], it.get("source", "teach"), author=it.get("author", ""), demo=bool(it.get("demo")), ts=it.get("ts"))
        return len(items)

    async def delete_snapshot(self, snapshot_id: int) -> bool:
        return (await self.db.execute("DELETE FROM learning_snapshots WHERE id = ?", (snapshot_id,))) > 0

    # ------------------------------------------------------------------ export / import
    async def export(self) -> dict[str, Any]:
        rows = await self.active()
        return {"format": "savahbot-lessons", "version": 1, "exported": int(time.time()),
                "lessons": [{"label": r["label"], "text": r["body"], "source": r["source"], "ts": r["ts"]} for r in reversed(rows)]}

    async def import_lessons(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict) or data.get("format") != "savahbot-lessons" or not isinstance(data.get("lessons"), list):
            raise ValueError("That file is not a SavahBot lessons export.")
        items = data["lessons"]
        if len(items) > 5000:
            raise ValueError("That file has more than 5000 lessons.")
        added = skipped = 0
        for it in items:
            if not isinstance(it, dict) or it.get("label") not in LABELS or not isinstance(it.get("text"), str):
                skipped += 1
                continue
            res = await self.add(it["text"], it["label"], "import")
            added += res["status"] in ("added", "relabelled")
            skipped += res["status"] not in ("added", "relabelled")
        return {"added": added, "skipped": skipped}
