"""Ban management: a ledger of every timeout and ban SavahBot makes, the rules that soften them, and lifting them again.

Why a ledger: YouTube has no call that lists a channel's bans, and lifting one needs the id YouTube gave when the ban was made.
So SavahBot writes that id down. Bans made before 1.2.0, or by hand in YouTube Studio, are not in the ledger and can only be
lifted in YouTube Studio.
"""
from __future__ import annotations

import time
from typing import Any

from ..db import register_schema
from ..utils import split_csv

register_schema([
    """CREATE TABLE IF NOT EXISTS bans (
        id {PK}, ts {REAL} NOT NULL, platform TEXT NOT NULL DEFAULT 'youtube', author_id TEXT NOT NULL, author_name TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL, duration INTEGER, ban_ref TEXT NOT NULL DEFAULT '', action_id INTEGER, source TEXT NOT NULL DEFAULT 'approved',
        reason TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active', expires_ts {REAL}, lifted_ts {REAL}, lifted_by TEXT NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT '', demo INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS idx_bans_status ON bans (status, ts)",
    "CREATE INDEX IF NOT EXISTS idx_bans_author ON bans (platform, author_id)",
])

RANK = {"allow": 0, "flag": 1, "delete": 2, "timeout": 3, "ban": 4}
STATUSES = ("active", "lifted", "expired", "failed")


def _cap_map(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in split_csv(text):
        name, _, cap = part.partition(":")
        if name.strip() and cap.strip() in ("delete", "timeout", "ban"):
            out[name.strip().lower()] = cap.strip()
    return out


class Bans:
    def __init__(self, db: Any, cfg: Any) -> None:
        self.db, self.cfg = db, cfg

    # ------------------------------------------------------------------ rules that soften an action
    async def limit(self, action: str, duration: int | None, signals: list[str], author_id: str, author_name: str,
                    auto: bool, now: float | None = None) -> tuple[str, int | None, str]:
        """Apply your softening rules. Returns (action, duration, note). Only ever lowers an action, never raises it."""
        if action not in ("timeout", "ban"):
            return action, duration, ""
        now = now if now is not None else time.time()
        notes: list[str] = []
        ceiling = self.cfg.get("mod_max_punishment")
        names = {author_id.lower(), author_name.lower()}
        if names & {x.lower() for x in split_csv(self.cfg.get("mod_never_punish"))}:
            ceiling = "delete"
            notes.append("on your never-punish list")
        caps = _cap_map(self.cfg.get("mod_reason_caps"))
        for sig in signals:
            cap = caps.get(sig.lower())
            if cap and RANK[cap] < RANK[ceiling]:
                ceiling = cap
                notes.append(f"'{sig}' is capped at {cap}")
        daily = int(self.cfg.get("mod_auto_punish_daily_cap"))
        if auto and daily > 0 and RANK[ceiling] >= RANK["timeout"] and await self.auto_count_today(now) >= daily:
            ceiling = "delete"
            notes.append(f"daily limit of {daily} automatic timeouts and bans reached")
        if RANK[action] > RANK[ceiling]:
            action = ceiling
            if action == "delete":
                duration = None
            elif action == "timeout" and not duration:
                ladder = [int(x) for x in split_csv(self.cfg.get("mod_timeout_ladder")) if x.isdigit()] or [300]
                duration = ladder[-1]
            return action, duration, "; ".join(notes) or f"limited to {ceiling}"
        return action, duration, ""

    @staticmethod
    def _day_start(now: float) -> float:
        return now - (now % 86400)

    async def auto_count_today(self, now: float) -> int:
        r = await self.db.fetchone("SELECT COUNT(*) AS n FROM bans WHERE source = 'auto' AND demo = 0 AND status != 'failed' AND ts >= ?", (self._day_start(now),))
        return int(r["n"])

    # ------------------------------------------------------------------ ledger
    async def record(self, *, author_id: str, author_name: str, kind: str, duration: int | None, ban_ref: str, action_id: int | None,
                     source: str, reason: str, platform: str = "youtube", demo: bool = False, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        expires = now + duration if kind == "timeout" and duration else None
        return await self.db.insert(
            "INSERT INTO bans (ts, platform, author_id, author_name, kind, duration, ban_ref, action_id, source, reason, status, expires_ts, demo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
            (now, platform, author_id, author_name[:100], kind, duration, ban_ref, action_id, source, reason[:300], expires, int(demo)))

    async def get(self, ban_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM bans WHERE id = ?", (ban_id,))

    async def expire_due(self, now: float) -> int:
        return await self.db.execute("UPDATE bans SET status = 'expired' WHERE status = 'active' AND kind = 'timeout' AND expires_ts IS NOT NULL AND expires_ts <= ?", (now,))

    async def search(self, status: str = "", q: str = "", offset: int = 0, limit: int = 40, now: float | None = None) -> dict[str, Any]:
        await self.expire_due(now if now is not None else time.time())
        where, params = ["1 = 1"], []
        if status in STATUSES:
            where.append("status = ?")
            params.append(status)
        if q.strip():
            where.append("(LOWER(author_name) LIKE ? OR author_id = ?)")
            params += [f"%{q.strip().lower()[:60]}%", q.strip()]
        clause = " AND ".join(where)
        total = (await self.db.fetchone(f"SELECT COUNT(*) AS n FROM bans WHERE {clause}", params))["n"]
        rows = await self.db.fetchall(f"SELECT * FROM bans WHERE {clause} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
                                      [*params, max(1, min(limit, 200)), max(0, offset)])
        for r in rows:
            r["can_lift"] = bool(r["status"] == "active" and (r["ban_ref"] or r["demo"]))
        return {"total": total, "offset": offset, "items": rows}

    async def counts(self) -> dict[str, int]:
        rows = await self.db.fetchall("SELECT status, COUNT(*) AS n FROM bans GROUP BY status")
        out = {s: 0 for s in STATUSES}
        out.update({r["status"]: r["n"] for r in rows})
        return out

    async def find_active(self, who: str) -> list[dict[str, Any]]:
        who = who.strip().lstrip("@")
        return await self.db.fetchall(
            "SELECT * FROM bans WHERE status = 'active' AND (author_id = ? OR LOWER(author_name) = ?) ORDER BY ts DESC", (who, who.lower()))

    async def mark_lifted(self, ban_id: int, by: str, now: float | None = None) -> None:
        await self.db.execute("UPDATE bans SET status = 'lifted', lifted_ts = ?, lifted_by = ?, error = '' WHERE id = ?",
                              (now if now is not None else time.time(), by[:40], ban_id))

    async def mark_error(self, ban_id: int, error: str) -> None:
        await self.db.execute("UPDATE bans SET error = ? WHERE id = ?", (error[:300], ban_id))

    async def due_second_chance(self, now: float) -> list[dict[str, Any]]:
        hours = float(self.cfg.get("mod_second_chance_hours"))
        if hours <= 0:
            return []
        return await self.db.fetchall(
            "SELECT * FROM bans WHERE status = 'active' AND kind = 'ban' AND source = 'auto' AND ban_ref != '' AND demo = 0 AND ts <= ? ORDER BY ts LIMIT 3",
            (now - hours * 3600,))
