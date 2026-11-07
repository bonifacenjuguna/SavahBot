"""Database access for the intelligence layer: learned examples, shadow findings, pack choices and reputation history."""
from __future__ import annotations

import time
from typing import Any


class IntelStore:
    def __init__(self, db: Any) -> None:
        self.db = db

    # ------------------------------------------------------------------ pack choices
    async def pack_state(self) -> tuple[set[str], list[dict[str, Any]], list[dict[str, Any]]]:
        off = {r["id"] for r in await self.db.fetchall("SELECT id FROM intel_packs WHERE enabled = 0")}
        rows = await self.db.fetchall("SELECT pack, kind, value, weight FROM intel_user")
        return off, [r for r in rows if r["kind"] == "add"], [r for r in rows if r["kind"] == "mute"]

    async def set_pack_enabled(self, pack_id: str, enabled: bool) -> None:
        await self.db.execute(
            "INSERT INTO intel_packs (id, enabled) VALUES (?, ?) ON CONFLICT (id) DO UPDATE SET enabled = excluded.enabled",
            (pack_id, int(enabled)))

    async def add_user_entry(self, pack: str, kind: str, value: str, weight: int = 0) -> None:
        await self.db.execute(
            "INSERT INTO intel_user (pack, kind, value, weight, created) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (pack, kind, value) DO UPDATE SET weight = excluded.weight",
            (pack, kind, value, int(weight), time.time()))

    async def remove_user_entry(self, pack: str, kind: str, value: str) -> int:
        return await self.db.execute("DELETE FROM intel_user WHERE pack = ? AND kind = ? AND value = ?", (pack, kind, value))

    # ------------------------------------------------------------------ learned examples
    async def add_example(self, label: str, body: str, *, source: str, author: str = "", pred: float | None = None,
                          weight: float = 1.0, demo: bool = False, ts: float | None = None) -> int:
        return await self.db.insert(
            "INSERT INTO intel_examples (ts, label, source, body, author, pred, weight, demo) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts if ts is not None else time.time(), label, source, body[:1000], author[:100], pred, float(weight), int(demo)))

    async def get_example(self, id_: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM intel_examples WHERE id = ?", (id_,))

    async def find_examples(self, body: str) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT id, label, body, weight FROM intel_examples WHERE body = ?", (body[:1000],))

    async def delete_example(self, id_: int) -> int:
        return await self.db.execute("DELETE FROM intel_examples WHERE id = ?", (id_,))

    async def clear_examples(self) -> int:
        return await self.db.execute("DELETE FROM intel_examples")

    async def all_examples(self, limit: int) -> list[dict[str, Any]]:
        rows = await self.db.fetchall("SELECT id, label, body, weight FROM intel_examples ORDER BY id DESC LIMIT ?", (limit,))
        return list(reversed(rows))

    async def list_examples(self, label: str = "", q: str = "", limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        where, params = ["1 = 1"], []
        if label in ("spam", "ham"):
            where.append("label = ?"); params.append(label)
        if q.strip():
            where.append("LOWER(body) LIKE ?"); params.append(f"%{q.strip().lower()}%")
        clause = " AND ".join(where)
        total = (await self.db.fetchone(f"SELECT COUNT(*) AS n FROM intel_examples WHERE {clause}", params))["n"]
        rows = await self.db.fetchall(f"SELECT * FROM intel_examples WHERE {clause} ORDER BY id DESC LIMIT ? OFFSET ?", [*params, limit, offset])
        return rows, int(total)

    async def example_counts(self) -> dict[str, int]:
        rows = await self.db.fetchall("SELECT label, COUNT(*) AS n FROM intel_examples GROUP BY label")
        out = {"spam": 0, "ham": 0}
        out.update({r["label"]: int(r["n"]) for r in rows})
        out["total"] = out["spam"] + out["ham"]
        return out

    async def prediction_rows(self, since: float) -> list[dict[str, Any]]:
        """(ts, label, pred) of examples the filter guessed at before learning them: an honest test-then-train record."""
        return await self.db.fetchall("SELECT ts, label, pred FROM intel_examples WHERE pred IS NOT NULL AND ts >= ? ORDER BY ts", (since,))

    async def trim_examples(self, cap: int) -> None:
        row = await self.db.fetchone("SELECT COUNT(*) AS n FROM intel_examples")
        extra = int(row["n"]) - cap if row else 0
        if extra > 0:
            await self.db.execute("DELETE FROM intel_examples WHERE id IN (SELECT id FROM intel_examples ORDER BY id LIMIT ?)", (extra,))

    # ------------------------------------------------------------------ shadow findings
    async def add_shadow(self, rows: list[dict[str, Any]]) -> None:
        for r in rows:
            await self.db.execute(
                "INSERT INTO intel_shadow (ts, platform, author_id, author_name, body, detector, signal, weight, detail, would, actual, demo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (r["ts"], r.get("platform", ""), r.get("author_id", ""), r.get("author_name", ""), r.get("body", "")[:500], r["detector"],
                 r["signal"], int(r["weight"]), r.get("detail", "")[:200], r.get("would", "allow"), r.get("actual", "allow"), int(r.get("demo", False))))

    async def label_shadow(self, author_id: str, body: str, label: str) -> int:
        """Record what you decided about a message, so the shadow report can tell which findings were right."""
        return await self.db.execute("UPDATE intel_shadow SET label = ? WHERE author_id = ? AND body = ? AND label = ''", (label, author_id, body[:500]))

    async def shadow_summary(self, since: float, demo: bool | None = None) -> list[dict[str, Any]]:
        extra, params = ("", [since])
        if demo is not None:
            extra, params = (" AND demo = ?", [since, int(demo)])
        return await self.db.fetchall(
            "SELECT detector, COUNT(*) AS hits, "
            "SUM(CASE WHEN would <> actual THEN 1 ELSE 0 END) AS differs, "
            "SUM(CASE WHEN label = 'spam' THEN 1 ELSE 0 END) AS spam, SUM(CASE WHEN label = 'ham' THEN 1 ELSE 0 END) AS ham, "
            "COUNT(DISTINCT author_id) AS authors, AVG(weight) AS avg_weight "
            f"FROM intel_shadow WHERE ts >= ?{extra} GROUP BY detector", params)

    async def shadow_recent(self, since: float, detector: str = "", limit: int = 50, offset: int = 0, only_differs: bool = False) -> tuple[list[dict[str, Any]], int]:
        where, params = ["ts >= ?"], [since]
        if detector:
            where.append("detector = ?"); params.append(detector)
        if only_differs:
            where.append("would <> actual")
        clause = " AND ".join(where)
        total = (await self.db.fetchone(f"SELECT COUNT(*) AS n FROM intel_shadow WHERE {clause}", params))["n"]
        rows = await self.db.fetchall(f"SELECT * FROM intel_shadow WHERE {clause} ORDER BY id DESC LIMIT ? OFFSET ?", [*params, limit, offset])
        return rows, int(total)

    async def shadow_series(self, since: float, bucket: int) -> list[dict[str, Any]]:
        rows = await self.db.fetchall("SELECT ts, would, actual FROM intel_shadow WHERE ts >= ?", (since,))
        out: dict[int, dict[str, int]] = {}
        for r in rows:
            b = int(r["ts"] // bucket) * bucket
            e = out.setdefault(b, {"t": b, "hits": 0, "differs": 0})
            e["hits"] += 1
            e["differs"] += 1 if r["would"] != r["actual"] else 0
        return [out[k] for k in sorted(out)]

    # ------------------------------------------------------------------ reputation history
    async def author_history(self, platform: str, author_id: str) -> dict[str, Any]:
        first = await self.db.fetchone("SELECT MIN(ts) AS first, COUNT(*) AS n, SUM(CASE WHEN verdict <> 'allow' THEN 1 ELSE 0 END) AS flagged "
                                       "FROM chat_messages WHERE platform = ? AND author_id = ? AND demo = 0", (platform, author_id))
        acts = await self.db.fetchall("SELECT status, COUNT(*) AS n FROM mod_actions WHERE platform = ? AND author_id = ? AND demo = 0 GROUP BY status", (platform, author_id))
        by = {r["status"]: int(r["n"]) for r in acts}
        return {"first": first["first"] if first and first["first"] else None, "messages": int(first["n"] or 0) if first else 0,
                "flagged": int(first["flagged"] or 0) if first else 0,
                "punished": by.get("executed", 0), "cleared": by.get("rejected", 0)}
