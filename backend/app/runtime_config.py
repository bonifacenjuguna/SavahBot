"""Runtime configuration: environment values plus changes made from the dashboard / Telegram.

Precedence (highest first):  value saved from the dashboard  >  environment variable  >  default.
`get()` is synchronous and cheap, so the hot path (moderation) can read settings on every message.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from . import config
from .config import BY_NAME, ENUMS, FIELDS, Settings, is_editable, validate_value

logger = logging.getLogger("savahbot.config")

_SECRET_HINTS = ("token", "secret", "password", "api_key", "dsn")
_SECRET_NAMES = {"database_url", "redis_url", "outbound_webhook_url", "discord_webhook_url", "smtp_user"}


def is_secret(name: str) -> bool:
    return name in _SECRET_NAMES or any(h in name for h in _SECRET_HINTS)


def _type_name(default: Any) -> str:
    if isinstance(default, bool):
        return "bool"
    if isinstance(default, int):
        return "int"
    if isinstance(default, float):
        return "float"
    return "string"


class RuntimeConfig:
    def __init__(self, settings: Settings, db: Any = None) -> None:
        self.settings = settings
        self.db = db
        self._overrides: dict[str, Any] = {}
        self._listeners: list[Callable[[str, Any], None]] = []

    def get(self, name: str) -> Any:
        if name in self._overrides:
            return self._overrides[name]
        return self.settings.get(name)

    @property
    def public_url(self) -> str:
        return self.settings.public_url

    async def load(self) -> None:
        if not self.db:
            return
        for row in await self.db.fetchall("SELECT key, value FROM settings"):
            name = row["key"]
            if name in BY_NAME and is_editable(name):
                try:
                    self._overrides[name] = validate_value(name, row["value"])
                except (ValueError, TypeError):
                    logger.warning("Ignoring invalid saved setting %s", name)

    def on_change(self, callback: Callable[[str, Any], None]) -> None:
        self._listeners.append(callback)

    def _notify(self, name: str, value: Any) -> None:
        for cb in self._listeners:
            try:
                cb(name, value)
            except Exception:  # a bad listener must never break a settings change
                logger.exception("Settings listener failed for %s", name)

    async def set(self, name: str, value: Any) -> Any:
        if name not in BY_NAME:
            raise KeyError(name)
        if not is_editable(name):
            raise PermissionError(f"{name} can only be changed with an environment variable.")
        coerced = validate_value(name, value)
        self._overrides[name] = coerced
        if self.db:
            await self.db.execute(
                "INSERT INTO settings (key, value, updated) VALUES (?, ?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated = excluded.updated",
                (name, str(coerced).lower() if isinstance(coerced, bool) else str(coerced), time.time()),
            )
        self._notify(name, coerced)
        return coerced

    async def reset(self, name: str) -> Any:
        if name not in BY_NAME:
            raise KeyError(name)
        self._overrides.pop(name, None)
        if self.db:
            await self.db.execute("DELETE FROM settings WHERE key = ?", (name,))
        value = self.settings.get(name)
        self._notify(name, value)
        return value

    # ---- views for the dashboard -------------------------------------------------------------
    def snapshot(self) -> list[dict[str, Any]]:
        out = []
        for f in FIELDS:
            secret = is_secret(f.name)
            env_value = self.settings.get(f.name)
            source = "dashboard" if f.name in self._overrides else ("env" if env_value != f.default else "default")
            value = self.get(f.name)
            out.append({
                "name": f.name,
                "env": config.env_name(f.name),
                "group": f.group,
                "description": f.description,
                "type": _type_name(f.default),
                "default": None if secret else f.default,
                "value": None if secret else value,
                "is_set": value not in ("", None, 0, False) if secret else source != "default",
                "secret": secret,
                "source": source,
                "editable": is_editable(f.name),
                "options": ENUMS.get(f.name),
                "reserved": f.group.startswith("Reserved"),
            })
        return out

    def requirements_status(self) -> dict[str, list[dict[str, Any]]]:
        status: dict[str, list[dict[str, Any]]] = {}
        for area, names in config.REQUIREMENTS.items():
            items = []
            for n in names:
                v = self.settings.get(n) if n != "public_base_url" else self.settings.public_url
                if n == "youtube_target_channel_id":
                    v = v or self.settings.get("youtube_channel_id")  # deprecated alias still counts
                items.append({"env": config.env_name(n), "set": v not in ("", None, 0)})
            status[area] = items
        return status
