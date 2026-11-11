"""The activity log: what changed in SavahBot, by area and importance.

Never stores secrets, tokens, passwords or chat message text. Settings whose names look secret are recorded as "changed" with no values.
Sensitive entries cannot be deleted from the dashboard; they only leave when the retention period ends.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from .db import register_schema
from .runtime_config import is_secret

logger = logging.getLogger(__name__)

register_schema(["CREATE TABLE IF NOT EXISTS activity_log (id {PK}, ts {REAL} NOT NULL, area TEXT NOT NULL, importance TEXT NOT NULL, action TEXT NOT NULL, summary TEXT NOT NULL, before_v TEXT NOT NULL DEFAULT '', after_v TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL DEFAULT '')",
                 "CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_log (ts)",
                 "CREATE INDEX IF NOT EXISTS idx_activity_area ON activity_log (area, ts)"])

AREAS = {"security": "Security", "settings": "Settings", "moderation": "Moderation", "telegram": "Telegram", "notifications": "Notifications", "youtube": "YouTube",
         "data": "Data and backups", "chat": "Chat actions", "variables": "Variables", "weather": "Weather"}
IMPORTANCE = ("sensitive", "notable", "routine")
#: setting-name prefixes -> area, first match wins
_AREA_BY_PREFIX = (("telegram", "telegram"), ("notify", "notifications"), ("youtube", "youtube"), ("mod_", "moderation"), ("weather", "weather"), ("backup", "data"), ("security", "security"), ("access", "security"))
_SENSITIVE_HINTS = ("lockdown", "password", "totp", "passkey", "session", "auth", "secret", "token", "owner", "claim", "webhook")
_NOTABLE_HINTS = ("enabled", "mode", "auto", "ban", "timeout", "threshold", "level")


def area_of(name: str) -> str:
    return next((a for p, a in _AREA_BY_PREFIX if name.startswith(p)), "settings")


def importance_of(name: str) -> str:
    if any(h in name for h in _SENSITIVE_HINTS) or is_secret(name):
        return "sensitive"
    return "notable" if any(h in name for h in _NOTABLE_HINTS) else "routine"


def _show(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)[:120] if not isinstance(v, str) else v[:120]


class ActivityLog:
    def __init__(self, db: Any, cfg: Any, notify: Any = None) -> None:
        self.db, self.cfg, self.notify = db, cfg, notify

    async def record(self, area: str, action: str, summary: str, importance: str = "routine", before: Any = "", after: Any = "", actor: str = "owner") -> None:
        """Best effort: a failure to log must never break the action that was logged."""
        try:
            area = area if area in AREAS else "settings"
            importance = importance if importance in IMPORTANCE else "routine"
            await self.db.execute("INSERT INTO activity_log (ts, area, importance, action, summary, before_v, after_v, actor) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                  (time.time(), area, importance, action[:60], summary[:240], _show(before), _show(after), actor[:40]))
            if importance == "sensitive" and self.notify is not None and self.cfg.get("activity_notify_sensitive"):
                await self.notify.emit("security.alert", "Sensitive change", summary[:140], route="#/activity")
        except Exception:
            logger.exception("Could not write the activity log")

    async def setting(self, name: str, old: Any, new: Any) -> None:
        if old == new:
            return
        secret = is_secret(name)
        await self.record(area_of(name), "setting", f"Changed {name.replace('_', ' ')}" + (" (value hidden)" if secret else ""), importance_of(name),
                          "" if secret else old, "" if secret else new)

    async def query(self, area: str = "", importance: str = "", q: str = "", since: float = 0, until: float = 0, before_id: int = 0, limit: int = 30) -> dict[str, Any]:
        where, args = ["1=1"], []
        for col, val in (("area", area), ("importance", importance)):
            if val:
                where.append(f"{col} = ?"); args.append(val)
        if q:
            where.append("(LOWER(summary) LIKE ? OR LOWER(action) LIKE ?)"); args += [f"%{q.lower()}%"] * 2
        if since:
            where.append("ts >= ?"); args.append(since)
        if until:
            where.append("ts < ?"); args.append(until)
        if before_id:
            where.append("id < ?"); args.append(before_id)
        limit = max(1, min(limit, 200))
        rows = await self.db.fetchall(f"SELECT * FROM activity_log WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?", (*args, limit + 1))
        more = len(rows) > limit
        return {"items": rows[:limit], "more": more, "areas": AREAS}

    async def purge(self, now: float) -> None:
        days = int(self.cfg.get("activity_retention_days"))
        if days > 0:
            await self.db.execute("DELETE FROM activity_log WHERE ts < ?", (now - days * 86400,))

    # ------------------------------------------------------------------ wiring
    def attach(self, bus: Any) -> None:
        """Listen for things other parts of the bot already announce. Message text is never copied, only who and what kind."""
        bus.tap(self._tap)

    def _tap(self, ev: dict) -> None:
        t, d = ev.get("type"), ev.get("data") or {}
        job = None
        if t == "ban_made":
            job = self.record("moderation", "ban", f"{(d.get('kind') or 'action').capitalize()} for {d.get('author', 'someone')} ({d.get('source', 'bot')})", "notable", actor=str(d.get("source", "bot")))
        elif t == "ban_lifted":
            job = self.record("moderation", "unban", f"Lifted the ban on {d.get('author', 'someone')}", "notable", actor=str(d.get("by", "owner")))
        elif t == "backup":
            job = self.record("data", "backup", str(d.get("title", "Backup")) + ": " + str(d.get("text", "")), "sensitive")
        if job is not None:
            try:
                asyncio.get_running_loop().create_task(job)
            except RuntimeError:
                job.close()

    async def mirror_audit(self, action: str, detail: str) -> None:
        sensitive = any(h in action for h in ("password", "totp", "recovery", "lockdown", "passkey", "revoked", "new_device", "backup"))
        await self.record("data" if action.startswith("backup") else "security", action, action.replace("_", " ").capitalize() + (f": {detail}" if detail and "recovery" not in action else ""),
                          "sensitive" if sensitive else "notable")
