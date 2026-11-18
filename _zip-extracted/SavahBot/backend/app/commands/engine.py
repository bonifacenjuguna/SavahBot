"""Chat command dispatcher: custom commands from the database plus a few built-ins."""
from __future__ import annotations

import time
from typing import Any, Callable

from ..models import ChatMessage
from ..store import LEVELS, Store, ValidationFailed, clean_name
from ..utils import format_duration, truncate
from .triggers import matches
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
        self._trig_global: dict[int, float] = {}
        self._trig_user: dict[tuple[int, str], float] = {}

    # 1.1.8: cooldowns as plain data, so a restart does not let a command or auto-reply fire twice in a row
    def export_state(self, now: float, max_age: float = 86400.0, limit: int = 5000) -> dict[str, Any]:
        def recent(d: dict) -> list:
            items = [(k, t) for k, t in d.items() if now - t <= max_age]
            items.sort(key=lambda kv: kv[1], reverse=True)
            return items[:limit]
        return {"g": [[k, t] for k, t in recent(self._last_global)], "u": [[k[0], k[1], t] for k, t in recent(self._last_user)],
                "tg": [[k, t] for k, t in recent(self._trig_global)], "tu": [[k[0], k[1], t] for k, t in recent(self._trig_user)]}

    def import_state(self, data: dict[str, Any]) -> None:
        for k, t in data.get("g") or []:
            self._last_global[int(k)] = float(t)
        for k, a, t in data.get("u") or []:
            self._last_user[(int(k), str(a))] = float(t)
        for k, t in data.get("tg") or []:
            self._trig_global[int(k)] = float(t)
        for k, a, t in data.get("tu") or []:
            self._trig_user[(int(k), str(a))] = float(t)

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

    async def handle_triggers(self, msg: ChatMessage) -> list[str]:
        """Answer an exact phrase or word (see commands/triggers.py). Commands always win; at most one reply per message."""
        if not self.cfg.get("triggers_enabled") or msg.from_bot or msg.backfill:
            return []
        text = msg.text.strip()
        prefix = self.cfg.get("command_prefix")
        if not text or (prefix and text.startswith(prefix)):
            return []
        now = time.time()
        for t in await self.store.enabled_triggers():
            if rank(msg.level) < LEVELS[t["userlevel"]] or not matches(t, text):
                continue
            if msg.level != "owner":
                if now - self._trig_global.get(t["id"], 0) < t["cooldown"] or now - self._trig_user.get((t["id"], msg.author_id), 0) < t["user_cooldown"]:
                    continue
            self._trig_global[t["id"]] = now
            self._trig_user[(t["id"], msg.author_id)] = now
            reply = await self.renderer.render(t["response"], self.make_ctx(msg, "trigger", ""))
            if not reply:
                return []
            if t["mention"] and "$(user" not in t["response"].lower() and "$(touser" not in t["response"].lower():
                reply = truncate(f"@{msg.author_name} {reply}", self.cfg.get("command_max_response_length"))
            await self.store.bump_trigger(t["id"])
            return [reply]
        return []

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
