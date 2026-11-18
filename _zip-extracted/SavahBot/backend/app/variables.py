"""Your own variables: $(TikTok) becomes your TikTok link wherever the bot sends text (commands, timers, auto replies, messages you send as the bot).

Names are case-insensitive, 1 to 32 letters, digits, "_" or "-", starting with a letter. A name that is already a built-in ($(user), $(time) ...)
cannot be reused. A value may itself contain other variables, within the same depth and size limits as every other placeholder.
"""
from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse

from .db import register_schema

register_schema(["CREATE TABLE IF NOT EXISTS custom_vars (name TEXT PRIMARY KEY, value TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'text', note TEXT NOT NULL DEFAULT '', created {REAL} NOT NULL, updated {REAL} NOT NULL)"])

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
KINDS = ("text", "link", "number")
MAX_VALUE = 500
MAX_VARS = 200
#: built-ins (see commands/variables.py) plus names kept for the live stats variables
BUILTIN = {
    "user": "Who sent the message", "touser": "The first word after the command, or the sender", "userid": "The sender's ID", "userlevel": "everyone, regular, mod or owner",
    "channel": "Your channel's name", "botname": "The bot's name", "args": "Everything typed after the command", "query": "Same as args",
    "count": "A counter that goes up each use", "countdown": "Time until a date", "countup": "Time since a date", "time": "The time now", "date": "Today's date",
    "uptime": "How long the stream has been live", "random": "A random number, for example $(random 1-6)", "choose": "One of several, $(choose a|b|c)",
    "math": "A calculation, $(math 2*(3+4))", "quote": "A saved quote", "urlfetch": "Text from a web address you allow",
    "likes": "Likes on the live stream", "viewers": "People watching now", "subs": "Channel subscribers",
}
RESERVED = set(BUILTIN) | {str(i) for i in range(1, 10)}


class VariableError(ValueError):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.message, self.status = message, status


def clean(name: str, value: str, kind: str) -> tuple[str, str]:
    name = (name or "").strip().lstrip("$(").rstrip(")").strip()
    if not NAME_RE.match(name):
        raise VariableError("A name is 1 to 32 letters, digits, _ or -, and starts with a letter. For example TikTok or my_discord.")
    if name.lower() in RESERVED:
        raise VariableError(f"${{{name.lower()}}} is already a built-in variable, so pick another name.".replace("${", "$(").replace("}", ")"))
    value = (value or "").strip()
    if not value:
        raise VariableError("Give the variable a value.")
    if len(value) > MAX_VALUE:
        raise VariableError(f"A value can be at most {MAX_VALUE} characters.")
    if "\n" in value or "\r" in value:
        raise VariableError("A value must be one line, because chat messages are one line.")
    if kind not in KINDS:
        raise VariableError("The type must be text, link or number.")
    if kind == "link":
        p = urlparse(value)
        if p.scheme not in ("http", "https") or not p.hostname or "." not in p.hostname or " " in value:
            raise VariableError("A link must start with http:// or https:// and be a full address, for example https://tiktok.com/@you.")
    if kind == "number":
        try:
            float(value.replace(",", ""))
        except ValueError:
            raise VariableError("A number variable must be a number, for example 1500.") from None
    return name, value


class CustomVars:
    TTL = 20.0

    def __init__(self, db: Any) -> None:
        self.db = db
        self._cache: dict[str, str] | None = None
        self._at = 0.0

    def _drop(self) -> None:
        self._cache = None

    async def lookup(self, name: str) -> str | None:
        """Used while rendering. Cached for a few seconds, so a busy chat does not query the database for every placeholder."""
        if self._cache is None or time.monotonic() - self._at > self.TTL:
            rows = await self.db.fetchall("SELECT name, value FROM custom_vars")
            self._cache, self._at = {r["name"].lower(): r["value"] for r in rows}, time.monotonic()
        return self._cache.get(name.lower())

    async def usage(self, name: str) -> list[dict[str, str]]:
        like = f"%$({name.lower()}%"
        out: list[dict[str, str]] = []
        for table, col, label, ident in (("commands", "response", "Command", "name"), ("timers", "message", "Timer", "name"), ("triggers", "response", "Auto reply", "phrase")):
            rows = await self.db.fetchall(f"SELECT {ident} AS ident FROM {table} WHERE LOWER({col}) LIKE ?", (like,))
            out += [{"kind": label, "name": str(r["ident"])} for r in rows]
        other = await self.db.fetchall("SELECT name FROM custom_vars WHERE LOWER(value) LIKE ? AND LOWER(name) != ?", (like, name.lower()))
        out += [{"kind": "Variable", "name": r["name"]} for r in other]
        return out

    async def listing(self) -> list[dict[str, Any]]:
        rows = await self.db.fetchall("SELECT name, value, kind, note, created, updated FROM custom_vars ORDER BY LOWER(name)")
        return [{**r, "uses": len(await self.usage(r["name"]))} for r in rows]

    async def save(self, name: str, value: str, kind: str, note: str, now: float) -> dict[str, Any]:
        name, value = clean(name, value, kind)
        existing = await self.db.fetchone("SELECT name FROM custom_vars WHERE LOWER(name) = ?", (name.lower(),))
        if not existing and (await self.db.fetchone("SELECT COUNT(*) AS n FROM custom_vars"))["n"] >= MAX_VARS:
            raise VariableError(f"You can keep up to {MAX_VARS} variables.", 409)
        if existing:
            await self.db.execute("UPDATE custom_vars SET name = ?, value = ?, kind = ?, note = ?, updated = ? WHERE LOWER(name) = ?", (name, value, kind, note[:120], now, name.lower()))
        else:
            await self.db.execute("INSERT INTO custom_vars (name, value, kind, note, created, updated) VALUES (?, ?, ?, ?, ?, ?)", (name, value, kind, note[:120], now, now))
        self._drop()
        return {"name": name, "value": value, "kind": kind, "note": note[:120], "created": now, "updated": now, "uses": len(await self.usage(name)), "replaced": bool(existing)}

    async def delete(self, name: str, force: bool = False) -> list[dict[str, str]]:
        used = await self.usage(name)
        if used and not force:
            return used
        await self.db.execute("DELETE FROM custom_vars WHERE LOWER(name) = ?", (name.lower(),))
        self._drop()
        return []
