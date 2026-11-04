"""Chat command dispatcher: custom commands from the database plus a few built-ins."""
from __future__ import annotations

import time
from typing import Any, Callable

from ..models import ChatMessage
from ..store import LEVELS, Store, ValidationFailed, clean_name
from ..utils import format_duration, truncate
from .variables import Ctx, Renderer

BUILTIN_NAMES = {"commands", "addcom", "editcom", "delcom", "permit", "quote", "addquote", "uptime"}
_MOD_ONLY = {"addcom", "editcom", "delcom", "permit", "addquote"}


def rank(level: str) -> int:
    return LEVELS.get(level, 0)


class CommandEngine:
    def __init__(self, cfg: Any, store: Store, renderer: Renderer, permits: Any,
                 uptime_fn: Callable[[], float | None] | None = None, channel_fn: Callable[[], str] | None = None) -> None:
        self.cfg = cfg
        self.store = store
        self.renderer = renderer
        self.permits = permits
        self.uptime_fn = uptime_fn or (lambda: None)
        self.channel_fn = channel_fn or (lambda: "")
        self._last_global: dict[int, float] = {}
        self._last_user: dict[tuple[int, str], float] = {}

    def make_ctx(self, msg: ChatMessage, name: str, rest: str) -> Ctx:
        return Ctx(platform=msg.platform, author_id=msg.author_id, author_name=msg.author_name, level=msg.level,
                   args=rest.split(), raw_args=rest, channel=self.channel_fn(), command=name, now=msg.ts)

    async def handle(self, msg: ChatMessage) -> list[str]:
        """Return the replies (possibly none) for one chat message."""
        prefix = self.cfg.get("command_prefix")
        text = msg.text.strip()
        if not prefix or not text.startswith(prefix) or msg.from_bot or msg.backfill:
            return []
        name, _, rest = text[len(prefix):].partition(" ")
        name, rest = name.lower(), rest.strip()
        if not name:
            return []
        if name in BUILTIN_NAMES:
            if name in _MOD_ONLY and rank(msg.level) < LEVELS["mod"]:
                return []
            return [r for r in await self._builtin(name, rest, msg) if r]

        cmd = await self.store.find_command(name)
        if not cmd or not cmd["enabled"] or rank(msg.level) < LEVELS[cmd["userlevel"]]:
            return []
        now = time.time()
        if msg.level != "owner":
            if now - self._last_global.get(cmd["id"], 0) < cmd["cooldown"]:
                return []
            if now - self._last_user.get((cmd["id"], msg.author_id), 0) < cmd["user_cooldown"]:
                return []
        self._last_global[cmd["id"]] = now
        self._last_user[(cmd["id"], msg.author_id)] = now
        reply = await self.renderer.render(cmd["response"], self.make_ctx(msg, name, rest))
        await self.store.bump_command(cmd["id"])
        return [reply] if reply else []

    async def preview(self, template: str, msg: ChatMessage, rest: str = "") -> str:
        return await self.renderer.render(template, self.make_ctx(msg, "preview", rest))

    # ------------------------------------------------------------------ built-ins
    @staticmethod
    def _needs_owner(response: str, level: str) -> bool:
        return "$(urlfetch" in response.lower() and level != "owner"

    async def _builtin(self, name: str, rest: str, msg: ChatMessage) -> list[str]:
        p = self.cfg.get("command_prefix")
        limit = self.cfg.get("command_max_response_length")

        if name == "commands":
            visible = [f"{p}{c['name']}" for c in await self.store.list_commands()
                       if c["enabled"] and LEVELS[c["userlevel"]] <= rank(msg.level)]
            visible += [f"{p}{n}" for n in ("quote", "uptime")]
            return [truncate("Commands: " + " ".join(sorted(visible)), limit)]

        if name == "uptime":
            up = self.uptime_fn()
            return [f"Live for {format_duration(up)}." if up is not None else "The stream is offline."]

        if name == "quote":
            q = await self.store.quote_number(int(rest)) if rest.isdigit() else await self.store.random_quote()
            if not q:
                return ["No quotes yet. A mod can add one with " + f"{p}addquote."]
            return [truncate(f"“{q['body']}”" + (f" — {q['author']}" if q["author"] else ""), limit)]

        if name == "addquote":
            if not rest:
                return [f"Usage: {p}addquote <text>"]
            try:
                id_ = await self.store.add_quote(rest, author=msg.author_name)
            except ValidationFailed as exc:
                return [str(exc)]
            return [f"Quote #{id_} added."]

        if name == "permit":
            who, _, secs = rest.partition(" ")
            if not who:
                return [f"Usage: {p}permit <user> [seconds]"]
            seconds = int(secs) if secs.strip().isdigit() else self.cfg.get("mod_permit_seconds")
            seconds = max(5, min(seconds, 600))
            self.permits.permit(who, seconds)
            return [f"@{who.lstrip('@')} can post links for {seconds}s."]

        # addcom / editcom / delcom
        target, _, response = rest.partition(" ")
        if not target:
            return [f"Usage: {p}{name} <name>" + (" <response>" if name != "delcom" else "")]
        try:
            cname = clean_name(target, p)
        except ValidationFailed as exc:
            return [str(exc)]
        if cname in BUILTIN_NAMES:
            return [f"{p}{cname} is built in and cannot be changed."]
        response = response.strip()
        if name in ("addcom", "editcom") and not response:
            return [f"Usage: {p}{name} <name> <response>"]
        if name in ("addcom", "editcom") and self._needs_owner(response, msg.level):
            return ["Only the owner can use $(urlfetch) in a command."]
        try:
            if name == "addcom":
                await self.store.create_command(
                    cname, response, cooldown=self.cfg.get("command_default_cooldown"),
                    user_cooldown=self.cfg.get("command_user_cooldown"))
                return [f"Added {p}{cname}."]
            existing = await self.store.find_command(cname)
            if not existing:
                return [f"{p}{cname} does not exist."]
            if name == "editcom":
                await self.store.update_command(existing["id"], response=response)
                return [f"Updated {p}{cname}."]
            await self.store.delete_command(existing["id"])
            return [f"Removed {p}{cname}."]
        except ValidationFailed as exc:
            return [str(exc)]
