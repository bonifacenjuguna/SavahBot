"""Stream sessions: every livestream is its own record, with its own chat.

A session starts when the bot attaches to a live stream (or when Demo mode starts) and ends when that stream ends. The Desk shows only the
chat of the stream that is running now, so a new stream always opens on a fresh, empty chat. Past streams stay here as a history: when they
happened, how long they ran, how many lines and chatters they had, what moderation did, and the busiest minute.

Rules that keep the history honest:
- A short drop (the stream flaps, YouTube hiccups, the backend restarts) RESUMES the same session if it is for the same video and ended
  less than `RESUME_WINDOW` seconds ago. One stream is one session, even when the bot reconnects in the middle.
- A session that never saw a chat line and lasted under `MIN_KEEP` seconds is dropped, so false starts leave no clutter.
- Chat lines keep their own retention (`chat_retention_days`); the session row (and its numbers) is tiny and kept.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from typing import Any

from .db import register_schema

logger = logging.getLogger("savahbot.sessions")

register_schema([
    """CREATE TABLE IF NOT EXISTS stream_sessions (
        id TEXT PRIMARY KEY, started {REAL} NOT NULL, ended {REAL}, title TEXT NOT NULL DEFAULT '', label TEXT NOT NULL DEFAULT '',
        video_id TEXT NOT NULL DEFAULT '', platform TEXT NOT NULL DEFAULT '', demo INTEGER NOT NULL DEFAULT 0,
        messages INTEGER NOT NULL DEFAULT 0, chatters INTEGER NOT NULL DEFAULT 0, flagged INTEGER NOT NULL DEFAULT 0,
        deleted INTEGER NOT NULL DEFAULT 0, timeouts INTEGER NOT NULL DEFAULT 0, bans INTEGER NOT NULL DEFAULT 0,
        peak_per_min INTEGER NOT NULL DEFAULT 0, top TEXT NOT NULL DEFAULT '[]', resumed INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS idx_sessions_started ON stream_sessions (demo, started)",
    "CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages (session_id, ts)",
], columns=[("chat_messages", "session_id", "TEXT NOT NULL DEFAULT ''")])

RESUME_WINDOW = 600.0     # seconds: a stream that comes back within this is the same stream
MIN_KEEP = 120.0          # seconds: an empty session shorter than this is not worth keeping
LIST_FIELDS = "id, started, ended, title, label, video_id, platform, demo, messages, chatters, flagged, deleted, timeouts, bans, peak_per_min, top, resumed"


def new_id(now: float) -> str:
    return f"s{int(now):x}{secrets.token_hex(2)}"


def _shape(r: dict[str, Any], now: float) -> dict[str, Any]:
    out = dict(r)
    if not isinstance(out.get("top"), list):       # stored as JSON text; a running session carries the freshly worked-out list
        try:
            out["top"] = json.loads(out.get("top") or "[]")
        except ValueError:
            out["top"] = []
    out["demo"], out["resumed"] = bool(out.get("demo")), bool(out.get("resumed"))
    out["live"] = out.get("ended") is None
    out["duration"] = max(0.0, (out["ended"] if out["ended"] is not None else now) - out["started"])
    return out


class Sessions:
    def __init__(self, db: Any) -> None:
        self.db = db

    # ------------------------------------------------------------------ lifecycle
    async def close_orphans(self) -> int:
        """After a crash or a hard kill a session can be left open. Close each one at its last chat line (or its start), so nothing is "live" forever.
        A restart within RESUME_WINDOW still resumes it."""
        n = 0
        for r in await self.db.fetchall("SELECT id, started FROM stream_sessions WHERE ended IS NULL"):
            last = await self.db.fetchone("SELECT MAX(ts) AS t FROM chat_messages WHERE session_id = ?", (r["id"],))
            await self.db.execute("UPDATE stream_sessions SET ended = ? WHERE id = ?", (max(r["started"], float((last or {}).get("t") or 0)), r["id"]))
            n += 1
        return n

    async def begin(self, now: float, title: str, video_id: str, platform: str, demo: bool) -> tuple[dict[str, Any], bool]:
        """Start a session, or resume the one for this video that ended a moment ago. Returns (row, resumed)."""
        prev = await self.db.fetchone(
            f"SELECT {LIST_FIELDS} FROM stream_sessions WHERE demo = ? AND video_id = ? AND (ended IS NULL OR ended >= ?) ORDER BY started DESC LIMIT 1",
            (int(demo), video_id, now - RESUME_WINDOW))
        if prev:
            await self.db.execute("UPDATE stream_sessions SET ended = NULL, resumed = 1, title = ? WHERE id = ?", (title or prev["title"], prev["id"]))
            prev["ended"], prev["resumed"], prev["title"] = None, 1, title or prev["title"]
            return _shape(prev, now), True
        sid = new_id(now)
        await self.db.execute(
            "INSERT INTO stream_sessions (id, started, ended, title, video_id, platform, demo) VALUES (?, ?, NULL, ?, ?, ?, ?)",
            (sid, now, title, video_id, platform, int(demo)))
        row = await self.db.fetchone(f"SELECT {LIST_FIELDS} FROM stream_sessions WHERE id = ?", (sid,))
        return _shape(row or {"id": sid, "started": now, "ended": None, "title": title}, now), False

    async def set_title(self, sid: str, title: str) -> None:
        if title:
            await self.db.execute("UPDATE stream_sessions SET title = ? WHERE id = ?", (title, sid))

    async def finish(self, sid: str, now: float) -> dict[str, Any] | None:
        """Close the session and store its numbers. Returns the finished row, or None when it was empty and dropped."""
        row = await self.db.fetchone(f"SELECT {LIST_FIELDS} FROM stream_sessions WHERE id = ?", (sid,))
        if not row:
            return None
        stats = await self.compute(row, now)
        if stats["messages"] == 0 and now - row["started"] < MIN_KEEP:
            await self.db.execute("DELETE FROM stream_sessions WHERE id = ?", (sid,))
            return None
        await self.db.execute(
            "UPDATE stream_sessions SET ended = ?, messages = ?, chatters = ?, flagged = ?, deleted = ?, timeouts = ?, bans = ?, peak_per_min = ?, top = ? WHERE id = ?",
            (now, stats["messages"], stats["chatters"], stats["flagged"], stats["deleted"], stats["timeouts"], stats["bans"], stats["peak_per_min"],
             json.dumps(stats["top"]), sid))
        row.update(stats, ended=now, top=json.dumps(stats["top"]))
        return _shape(row, now)

    # ------------------------------------------------------------------ numbers
    async def compute(self, row: dict[str, Any], now: float) -> dict[str, Any]:
        """Everything the history shows about one session, worked out from the stored chat and moderation rows."""
        sid, start, end = row["id"], row["started"], row.get("ended") if row.get("ended") is not None else now
        t = await self.db.fetchone(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT author_id) AS who, "
            "COALESCE(SUM(CASE WHEN verdict <> 'allow' THEN 1 ELSE 0 END), 0) AS flagged "
            "FROM chat_messages WHERE session_id = ? AND level <> 'bot'", (sid,)) or {}
        acts = {"deleted": 0, "timeouts": 0, "bans": 0}
        key = {"delete": "deleted", "timeout": "timeouts", "ban": "bans"}
        for a in await self.db.fetchall("SELECT action, COUNT(*) AS n FROM mod_actions WHERE ts >= ? AND ts <= ? AND demo = ? AND status IN ('executed', 'simulated') "
                                        "AND action IN ('delete', 'timeout', 'ban') GROUP BY action", (start, end, int(bool(row.get("demo"))))):
            acts[key[a["action"]]] = int(a["n"])
        per_min: dict[int, int] = {}
        for r in await self.db.fetchall("SELECT ts FROM chat_messages WHERE session_id = ? AND level <> 'bot' ORDER BY ts LIMIT 200000", (sid,)):
            m = int(r["ts"] // 60)
            per_min[m] = per_min.get(m, 0) + 1
        top = [{"name": r["name"], "lines": int(r["n"])} for r in await self.db.fetchall(
            "SELECT MAX(author_name) AS name, COUNT(*) AS n FROM chat_messages WHERE session_id = ? AND level <> 'bot' GROUP BY author_id ORDER BY n DESC LIMIT 5", (sid,))]
        return {"messages": int(t.get("n") or 0), "chatters": int(t.get("who") or 0), "flagged": int(t.get("flagged") or 0), **acts,
                "peak_per_min": max(per_min.values(), default=0), "top": top}

    # ------------------------------------------------------------------ reading
    async def get(self, sid: str, now: float | None = None) -> dict[str, Any] | None:
        now = now if now is not None else time.time()
        row = await self.db.fetchone(f"SELECT {LIST_FIELDS} FROM stream_sessions WHERE id = ?", (sid,))
        if not row:
            return None
        if row["ended"] is None:       # still running: the stored numbers are not written yet, work them out now
            row.update(await self.compute(row, now))
        return _shape(row, now)

    async def search(self, demo: bool, q: str = "", since: float | None = None, until: float | None = None,
                     limit: int = 30, offset: int = 0, now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.time()
        where, params = ["demo = ?"], [int(demo)]
        if q:
            where.append("(lower(title) LIKE ? ESCAPE '\\' OR lower(label) LIKE ? ESCAPE '\\')")
            like = "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params += [like, like]
        if since is not None:
            where.append("started >= ?")
            params.append(since)
        if until is not None:
            where.append("started < ?")
            params.append(until)
        cond = " AND ".join(where)
        total = (await self.db.fetchone(f"SELECT COUNT(*) AS n FROM stream_sessions WHERE {cond}", params) or {"n": 0})["n"]
        rows = await self.db.fetchall(f"SELECT {LIST_FIELDS} FROM stream_sessions WHERE {cond} ORDER BY started DESC LIMIT ? OFFSET ?", (*params, limit, max(0, offset)))
        items = []
        for r in rows:
            if r["ended"] is None:
                r.update(await self.compute(r, now))
            items.append(_shape(r, now))
        return {"items": items, "total": int(total)}

    async def chat(self, sid: str, q: str = "", verdict: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        where, params = ["session_id = ?"], [sid]
        if q:
            where.append("(lower(body) LIKE ? ESCAPE '\\' OR lower(author_name) LIKE ? ESCAPE '\\')")
            like = "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params += [like, like]
        if verdict == "flagged":
            where.append("verdict IS NOT NULL AND verdict <> 'allow'")
        elif verdict == "blocked":
            where.append("verdict IS NOT NULL AND verdict NOT IN ('allow', 'flag')")
        rows = await self.db.fetchall(f"SELECT * FROM chat_messages WHERE {' AND '.join(where)} ORDER BY ts DESC, id DESC LIMIT ?", (*params, limit))
        out = []
        for m in reversed(rows):
            m["text"], m["demo"] = m.pop("body"), bool(m["demo"])
            out.append(m | {"from_bot": m["level"] == "bot", "reasons": []})
        return out

    async def rename(self, sid: str, label: str) -> bool:
        return (await self.db.execute("UPDATE stream_sessions SET label = ? WHERE id = ?", (label.strip()[:80], sid))) > 0

    async def delete(self, sid: str) -> bool:
        await self.db.execute("DELETE FROM chat_messages WHERE session_id = ?", (sid,))
        return (await self.db.execute("DELETE FROM stream_sessions WHERE id = ?", (sid,))) > 0

    async def purge_demo(self) -> None:
        await self.db.execute("DELETE FROM stream_sessions WHERE demo = 1 AND ended IS NOT NULL")

    async def last_finished(self, demo: bool, now: float | None = None) -> dict[str, Any] | None:
        now = now if now is not None else time.time()
        r = await self.db.fetchone(f"SELECT {LIST_FIELDS} FROM stream_sessions WHERE demo = ? AND ended IS NOT NULL ORDER BY started DESC LIMIT 1", (int(demo),))
        return _shape(r, now) if r else None
