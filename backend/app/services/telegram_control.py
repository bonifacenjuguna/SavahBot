"""Telegram control: the owner's switches for how much the bot may listen to, say and do.

Everything here is stored in the database (never in the page or the URL). The master switch, pause, read-only mode,
claim lock, owner unlink, secret rotation and a one-press "cut Telegram off" all work without touching the token,
so a suspected leak can be contained first and the token revoked in BotFather second.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from ..db import register_schema

logger = logging.getLogger("savahbot.telegram")

register_schema([
    "CREATE TABLE IF NOT EXISTS telegram_log (id {PK}, ts {REAL} NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '')",
    "CREATE INDEX IF NOT EXISTS idx_telegram_log_ts ON telegram_log (ts)",
])

DEFAULTS: dict[str, Any] = {
    "enabled": True,        # master switch: off = no listening, no sending, webhook removed, polling stopped
    "listen": True,         # obey commands and buttons
    "send": True,           # send anything at all (alerts, reminders, replies to the owner)
    "actions": True,        # off = read-only: the bot may show things but change nothing
    "claim_open": True,     # off = nobody can bind themselves as owner with /claim
    "pause_until": 0,       # temporary silence, in epoch seconds
}
#: commands that change something. Read-only mode blocks exactly these.
ACTION_COMMANDS = frozenset({"mode", "mod", "tgmode", "approve", "reject", "permit", "say", "demo", "note", "delnote", "remind", "delremind", "lockdown", "unban"})
BOOLS = ("enabled", "listen", "send", "actions", "claim_open")
LOG_KEEP = 300
LABELS = {"command": "Command", "button": "Button", "blocked": "Blocked", "stranger": "Stranger ignored", "claim_ok": "Owner claimed", "claim_failed": "Claim failed",
          "bad_secret": "Webhook rejected", "control": "Control changed", "unlink": "Owner unlinked", "rotate": "Secret rotated", "shutdown": "Telegram cut off"}


class TelegramControl:
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self._cache: dict[str, Any] | None = None
        self._last_logged: dict[str, float] = {}

    @property
    def db(self) -> Any:
        return self.bot.c.db

    # ------------------------------------------------------------------ state
    async def prefs(self) -> dict[str, Any]:
        if self._cache is None:
            try:
                raw = json.loads(await self.db.kv_get("telegram_control", "") or "{}")
            except ValueError:
                raw = {}
            out = dict(DEFAULTS)
            for k in BOOLS:
                if isinstance(raw.get(k), bool):
                    out[k] = raw[k]
            if isinstance(raw.get("pause_until"), (int, float)):
                out["pause_until"] = float(raw["pause_until"])
            self._cache = out
        return dict(self._cache)

    async def _save(self, p: dict[str, Any]) -> None:
        await self.db.kv_set("telegram_control", json.dumps(p))
        self._cache = dict(p)

    async def update(self, patch: dict[str, Any], now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.time()
        p = await self.prefs()
        before = dict(p)
        for k in BOOLS:
            if k in patch:
                if not isinstance(patch[k], bool):
                    raise ValueError(f"{k} must be true or false")
                p[k] = patch[k]
        if "pause_minutes" in patch:
            m = patch["pause_minutes"]
            if m is None or m == 0:
                p["pause_until"] = 0
            elif isinstance(m, (int, float)) and not isinstance(m, bool) and 1 <= m <= 7 * 24 * 60:
                p["pause_until"] = now + float(m) * 60
            else:
                raise ValueError("pause_minutes must be between 1 and 10080, or 0 to resume")
        await self._save(p)
        changed = [k for k in (*BOOLS, "pause_until") if p[k] != before[k]]
        if changed:
            await self.log("control", ", ".join(f"{k}={'on' if p[k] is True else 'off' if p[k] is False else 'set' if p[k] else 'cleared'}" for k in changed), now)
        if p["enabled"] != before["enabled"]:
            await self.bot.apply_mode()          # off removes the webhook / stops polling; on registers it again
        return p

    def is_paused(self, p: dict[str, Any], now: float | None = None) -> bool:
        return (now if now is not None else time.time()) < p["pause_until"]

    async def listening(self, now: float | None = None) -> bool:
        p = await self.prefs()
        return p["enabled"] and p["listen"] and not self.is_paused(p, now)

    async def sending(self, now: float | None = None) -> bool:
        p = await self.prefs()
        return p["enabled"] and p["send"] and not self.is_paused(p, now)

    async def allows_actions(self) -> bool:
        return (await self.prefs())["actions"]

    # ------------------------------------------------------------------ activity log
    async def log(self, kind: str, detail: str = "", now: float | None = None, *, throttle: float = 0) -> None:
        """A short trail you can read when something looks wrong. Never holds message text, tokens or passwords: only what kind of thing happened."""
        now = now if now is not None else time.time()
        if throttle:
            if now - self._last_logged.get(kind, 0) < throttle:
                return
            self._last_logged[kind] = now
        try:
            await self.db.execute("INSERT INTO telegram_log (ts, kind, detail) VALUES (?, ?, ?)", (now, kind, detail[:160]))
            await self.db.execute("DELETE FROM telegram_log WHERE id <= (SELECT MAX(id) FROM telegram_log) - ?", (LOG_KEEP,))
        except Exception:
            logger.debug("Telegram log write failed", exc_info=True)

    async def entries(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self.db.fetchall("SELECT ts, kind, detail FROM telegram_log ORDER BY id DESC LIMIT ?", (max(1, min(300, limit)),))
        return [{**r, "label": LABELS.get(r["kind"], r["kind"])} for r in rows]

    async def clear_log(self) -> int:
        return int(await self.db.execute("DELETE FROM telegram_log") or 0)

    # ------------------------------------------------------------------ owner and secrets
    async def unlink_owner(self, now: float | None = None) -> dict[str, Any]:
        """Forget who the owner is. The bot answers nobody until someone claims it again (if claiming is open)."""
        from_env = bool(self.bot.cfg.get("telegram_owner_id"))
        await self.db.kv_set("telegram_owner_id", "0")
        self.bot._owner = 0
        await self.log("unlink", "owner unlinked" + (" (TELEGRAM_OWNER_ID is set in the environment and still applies)" if from_env else ""), now)
        return {"ok": True, "env_owner_still_set": from_env}

    async def rotate_secret(self, now: float | None = None) -> dict[str, Any]:
        """New webhook secret: requests signed with the old one stop being accepted at once."""
        import secrets
        if self.bot.cfg.get("telegram_webhook_secret"):
            return {"ok": False, "error": "TELEGRAM_WEBHOOK_SECRET is set in the environment. Change it there and redeploy."}
        await self.db.kv_set("telegram_webhook_secret", secrets.token_urlsafe(24))
        await self.log("rotate", "webhook secret replaced", now)
        if self.bot.configured and self.bot.cfg.get("telegram_mode") == "webhook" and (await self.prefs())["enabled"]:
            await self.bot.apply_mode()
        return {"ok": True}

    async def shutdown(self, now: float | None = None) -> dict[str, Any]:
        """Contain a suspected leak in one step: off, owner forgotten, claiming closed, secret replaced, webhook removed."""
        p = await self.prefs()
        p.update(enabled=False, claim_open=False)
        await self._save(p)
        out = await self.unlink_owner(now)
        if not self.bot.cfg.get("telegram_webhook_secret"):
            await self.rotate_secret(now)
        await self.bot.apply_mode()
        await self.log("shutdown", "Telegram switched off and owner unlinked", now)
        return {"ok": True, "env_owner_still_set": out["env_owner_still_set"],
                "next": "Open @BotFather, send /revoke, pick this bot, then set the new token as TELEGRAM_BOT_TOKEN and redeploy. Until then the old token is the only thing left to protect."}

    # ------------------------------------------------------------------ view for the API
    async def view(self, now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.time()
        p = await self.prefs()
        cfg = self.bot.cfg
        return {
            **{k: p[k] for k in BOOLS}, "pause_until": p["pause_until"] if self.is_paused(p, now) else 0,
            "state": "off" if not p["enabled"] else "paused" if self.is_paused(p, now) else "read-only" if not p["actions"] else "on",
            "notify": {"pending": bool(cfg.get("telegram_notify_pending")), "reminders": bool(cfg.get("telegram_notify_reminders")), "stream_events": bool(cfg.get("telegram_notify_stream_events"))},
            "owner_from_env": bool(cfg.get("telegram_owner_id")), "secret_from_env": bool(cfg.get("telegram_webhook_secret")),
            "action_commands": sorted(ACTION_COMMANDS),
        }
