"""Long-term history: hourly and daily roll-ups of chat and moderation, kept forever.

Raw chat and action rows are pruned after their retention period (see `chat_retention_days`), but before that happens each
finished day is summed into `stats_hourly` and `stats_daily`. Those rows are tiny (a few per day), so the charts can look back
for years. Days are UTC days. The current, unfinished day is always computed live from the raw rows, so nothing is ever missing.
"""
from __future__ import annotations

import time
from typing import Any

from .db import register_schema

register_schema([
    """CREATE TABLE IF NOT EXISTS stats_hourly (
        hour INTEGER NOT NULL, demo INTEGER NOT NULL DEFAULT 0, messages INTEGER NOT NULL DEFAULT 0, flagged INTEGER NOT NULL DEFAULT 0,
        chatters INTEGER NOT NULL DEFAULT 0, deleted INTEGER NOT NULL DEFAULT 0, timeouts INTEGER NOT NULL DEFAULT 0, bans INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (hour, demo))""",
    """CREATE TABLE IF NOT EXISTS stats_daily (
        day INTEGER NOT NULL, demo INTEGER NOT NULL DEFAULT 0, messages INTEGER NOT NULL DEFAULT 0, flagged INTEGER NOT NULL DEFAULT 0,
        chatters INTEGER NOT NULL DEFAULT 0, deleted INTEGER NOT NULL DEFAULT 0, timeouts INTEGER NOT NULL DEFAULT 0, bans INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day, demo))""",
])

HOUR, DAY = 3600, 86400
FIELDS = ("messages", "flagged", "chatters", "deleted", "timeouts", "bans")
DONE = ("executed", "simulated")
KV_KEY = "history_rolled_until"


def _empty() -> dict[str, int]:
    return {f: 0 for f in FIELDS}


def aggregate(chat: list[dict[str, Any]], actions: list[dict[str, Any]], step: int) -> dict[tuple[int, int], dict[str, int]]:
    """Sum raw rows into buckets of `step` seconds, separately for real (demo=0) and demo (demo=1) data."""
    out: dict[tuple[int, int], dict[str, int]] = {}
    people: dict[tuple[int, int], set[str]] = {}
    for c in chat:
        if c.get("level") == "bot":
            continue
        k = (int(c["ts"] // step) * step, int(bool(c["demo"])))
        b = out.setdefault(k, _empty())
        b["messages"] += 1
        b["flagged"] += c["verdict"] != "allow"
        people.setdefault(k, set()).add(c["author_id"])
    for a in actions:
        if a["status"] not in DONE or a["action"] not in ("delete", "timeout", "ban"):
            continue
        k = (int(a["ts"] // step) * step, int(bool(a["demo"])))
        b = out.setdefault(k, _empty())
        b[{"delete": "deleted", "timeout": "timeouts", "ban": "bans"}[a["action"]]] += 1
    for k, s in people.items():
        out[k]["chatters"] = len(s)
    return out


class Rollups:
    def __init__(self, db: Any) -> None:
        self.db = db
        self.rolled_until = 0.0

    async def load(self) -> None:
        self.rolled_until = float(await self.db.kv_get(KV_KEY, "0") or 0)

    async def _raw(self, start: float, end: float) -> tuple[list[dict], list[dict]]:
        chat = await self.db.fetchall("SELECT ts, author_id, level, verdict, demo FROM chat_messages WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end))
        acts = await self.db.fetchall("SELECT ts, action, status, demo FROM mod_actions WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end))
        return chat, acts

    async def _save(self, table: str, col: str, rows: dict[tuple[int, int], dict[str, int]]) -> None:
        for (t, demo), v in rows.items():
            await self.db.execute(
                f"INSERT INTO {table} ({col}, demo, messages, flagged, chatters, deleted, timeouts, bans) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                f"ON CONFLICT ({col}, demo) DO UPDATE SET messages = excluded.messages, flagged = excluded.flagged, chatters = excluded.chatters, "
                f"deleted = excluded.deleted, timeouts = excluded.timeouts, bans = excluded.bans",
                (t, demo, *(v[f] for f in FIELDS)))

    async def run(self, now: float, max_days: int = 400) -> int:
        """Roll up every finished UTC day that has not been rolled yet (this is also the backfill for existing data). Returns days done."""
        today = int(now // DAY) * DAY
        start = self.rolled_until
        if start <= 0:
            first = await self.db.fetchone("SELECT MIN(ts) AS t FROM chat_messages")
            first_a = await self.db.fetchone("SELECT MIN(ts) AS t FROM mod_actions")
            candidates = [r["t"] for r in (first, first_a) if r and r["t"]]
            if not candidates:
                return 0
            start = int(min(candidates) // DAY) * DAY
        done = 0
        while start < today and done < max_days:
            chat, acts = await self._raw(start, start + DAY)
            await self._save("stats_hourly", "hour", aggregate(chat, acts, HOUR))
            await self._save("stats_daily", "day", aggregate(chat, acts, DAY))
            start += DAY
            done += 1
        if done:
            self.rolled_until = float(start)
            await self.db.kv_set(KV_KEY, str(int(start)))
        return done

    def safe_cutoff(self, wanted: float) -> float:
        """Raw rows older than this may be deleted: never past what has already been rolled up."""
        return min(wanted, self.rolled_until)

    async def series(self, since: float, until: float, res: str = "auto", demo: bool = False, now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.time()
        span = max(1.0, until - since)
        if res not in ("hour", "day"):
            res = "hour" if span <= 4 * DAY else "day"
        step = HOUR if res == "hour" else DAY
        table, col = ("stats_hourly", "hour") if res == "hour" else ("stats_daily", "day")
        first = int(since // step) * step
        rows = await self.db.fetchall(f"SELECT * FROM {table} WHERE {col} >= ? AND {col} < ? AND demo = ?", (first, until, int(demo)))
        have = {r[col]: r for r in rows}
        live_from = max(self.rolled_until, first)
        live: dict[tuple[int, int], dict[str, int]] = {}
        if until > live_from:
            chat, acts = await self._raw(live_from, until)
            live = aggregate(chat, acts, step)
        points = []
        t = first
        while t < until:
            src = have.get(t) if t < self.rolled_until else None
            if src is None:
                src = live.get((t, int(demo)))
            points.append({"t": t, **{f: int((src or {}).get(f, 0) or 0) for f in FIELDS}})
            t += step
        return {"res": res, "step": step, "since": first, "until": until, "points": points, "rolled_until": self.rolled_until}

    async def storage(self, now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.time()

        async def span(table: str, col: str) -> dict[str, Any]:
            r = await self.db.fetchone(f"SELECT COUNT(*) AS n, MIN({col}) AS first FROM {table}")
            return {"rows": r["n"], "oldest": r["first"]}
        return {"chat": await span("chat_messages", "ts"), "actions": await span("mod_actions", "ts"),
                "hourly": await span("stats_hourly", "hour"), "daily": await span("stats_daily", "day"), "rolled_until": self.rolled_until}
