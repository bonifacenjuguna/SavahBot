"""Command variables: $(name args). Nested variables are expanded inside-out: $(urlfetch https://x/$(user)).

Our own safe vocabulary (no raw eval):
  $(user) $(touser) $(userid) $(userlevel) $(channel) $(botname) $(args) $(1)..$(9)
  $(count [name]) $(countdown <when>) $(countup <when>) $(time [tz]) $(date [tz]) $(uptime)
  $(random 1-100) $(choose a|b|c) $(math 2*(3+4)) $(quote [n]) $(urlfetch <url>)
Unknown variables are left as written so typos are easy to spot.
"""
from __future__ import annotations

import asyncio
import ipaddress
import random
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from ..http import NetworkError, request_raw
from ..utils import format_duration, split_csv, truncate
from .safe_math import MathError, calculate


@dataclass
class Ctx:
    platform: str = "demo"
    author_id: str = ""
    author_name: str = "someone"
    level: str = "everyone"
    args: list[str] = field(default_factory=list)
    raw_args: str = ""
    channel: str = ""
    command: str = ""
    now: float = field(default_factory=time.time)


class UrlBlocked(Exception):
    pass


async def check_url(url: str, cfg: Any) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UrlBlocked("only http(s) URLs are allowed")
    host = parsed.hostname.lower()
    allowed = [h.lower() for h in split_csv(cfg.get("urlfetch_allowed_hosts"))]
    if allowed and not any(host == a or host.endswith("." + a) for a in allowed):
        raise UrlBlocked("host is not on the allow-list")
    if cfg.get("urlfetch_block_private"):
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, parsed.port or 443, 0, socket.SOCK_STREAM)
        except OSError as exc:
            raise UrlBlocked("host could not be resolved") from exc
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if getattr(ip, "ipv4_mapped", None):
                ip = ip.ipv4_mapped
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                raise UrlBlocked("private or internal addresses are blocked")


async def safe_fetch(url: str, cfg: Any) -> str:
    if not cfg.get("urlfetch_enabled"):
        raise UrlBlocked("urlfetch is turned off")
    await check_url(url, cfg)
    try:
        status, raw, _ = await request_raw(
            "GET", url, timeout=cfg.get("urlfetch_timeout_seconds"), max_bytes=cfg.get("urlfetch_max_bytes"),
            follow_redirects=False, headers={"Accept": "text/plain, application/json;q=0.8, */*;q=0.5"},
        )
    except NetworkError as exc:
        raise UrlBlocked("request failed") from exc
    if status >= 300:
        raise UrlBlocked(f"server answered {status}")
    return " ".join(raw.decode("utf-8", "replace").split())


@dataclass
class _Budget:
    left: int


class Renderer:
    def __init__(self, cfg: Any, store: Any, uptime_fn: Callable[[], float | None] | None = None,
                 fetch: Callable[[str, Any], Awaitable[str]] | None = None) -> None:
        self.cfg = cfg
        self.store = store
        self.uptime_fn = uptime_fn or (lambda: None)
        self.fetch = fetch or safe_fetch
        self.live: Any = None            # live likes / viewers / subscribers (services/live_extras.py), set by the container
        self.custom: Any = None          # your own variables (app/variables.py), set by the container

    async def render(self, template: str, ctx: Ctx) -> str:
        budget = _Budget(self.cfg.get("command_max_expansions"))
        out = await self._render(template, ctx, 0, budget)
        return truncate(" ".join(out.split()), self.cfg.get("command_max_response_length"))

    @staticmethod
    def _match(text: str, start: int) -> int:
        depth = 1
        for i in range(start, len(text)):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    return i
        return -1

    async def _render(self, text: str, ctx: Ctx, depth: int, budget: _Budget) -> str:
        if depth > self.cfg.get("command_max_render_depth"):
            return text
        out: list[str] = []
        i = 0
        while i < len(text):
            j = text.find("$(", i)
            if j == -1:
                out.append(text[i:])
                break
            out.append(text[i:j])
            k = self._match(text, j + 2)
            if k == -1:
                out.append(text[j:])
                break
            if budget.left <= 0:
                out.append(text[j:k + 1])
            else:
                budget.left -= 1
                inner = await self._render(text[j + 2:k], ctx, depth + 1, budget)
                out.append(await self._call(inner, ctx, text[j:k + 1], depth, budget))
            i = k + 1
        return "".join(out)

    def _tz(self, name: str) -> ZoneInfo:
        return ZoneInfo(name.strip() or self.cfg.get("owner_timezone"))

    def _parse_when(self, raw: str) -> float:
        s = raw.strip().replace(" ", "T", 1).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self._tz(""))
        return dt.timestamp()

    async def _call(self, inner: str, ctx: Ctx, literal: str, depth: int = 0, budget: _Budget | None = None) -> str:
        name, _, rest = inner.strip().partition(" ")
        name, rest = name.lower(), rest.strip()
        try:
            if name == "user":
                return ctx.author_name
            if name == "touser":
                return ctx.args[0].lstrip("@") if ctx.args else ctx.author_name
            if name == "userid":
                return ctx.author_id
            if name == "userlevel":
                return ctx.level
            if name == "channel":
                return ctx.channel
            if name == "botname":
                return str(self.cfg.get("app_name"))
            if name in ("args", "query"):
                return ctx.raw_args
            if name.isdigit() and 1 <= int(name) <= 9:
                i = int(name) - 1
                return ctx.args[i] if i < len(ctx.args) else ""
            if name == "count":
                return str(await self.store.counter_add("cmd:" + (rest or ctx.command or "default")))
            if name in ("countdown", "countup"):
                delta = self._parse_when(rest) - ctx.now
                if name == "countup":
                    delta = -delta
                return format_duration(delta) if delta > 0 else ("now" if name == "countdown" else "just now")
            if name == "time":
                return datetime.now(self._tz(rest)).strftime("%H:%M")
            if name == "date":
                return datetime.now(self._tz(rest)).strftime("%Y-%m-%d")
            if name == "uptime":
                up = self.uptime_fn()
                return format_duration(up) if up is not None else "offline"
            if name == "random":
                lo, hi = 1, 100
                if rest:
                    a, _, b = rest.partition("-")
                    lo, hi = (int(a), int(b)) if b else (1, int(a))
                if lo > hi:
                    lo, hi = hi, lo
                return str(random.randint(lo, hi))
            if name == "choose":
                options = [o.strip() for o in rest.split("|") if o.strip()]
                return random.choice(options) if options else ""
            if name == "math":
                return calculate(rest)
            if name == "quote":
                q = await self.store.quote_number(int(rest)) if rest.isdigit() else await self.store.random_quote()
                return q["body"] if q else "no quotes yet"
            if name == "urlfetch":
                return await self.fetch(rest, self.cfg)
        except (MathError, UrlBlocked) as exc:
            return f"[{name}: {exc}]"
        except (ValueError, KeyError, OverflowError):
            return f"[{name}: invalid input]"
        if name in ("likes", "viewers", "subs") and self.live is not None:
            v = self.live.live.get(name) if name != "subs" else self.live.subs.get("count")
            return f"{v:,}" if isinstance(v, int) else "n/a"
        if self.custom is not None and not rest:
            value = await self.custom.lookup(name)
            if value is not None:
                return await self._render(value, ctx, depth + 1, budget or _Budget(self.cfg.get("command_max_expansions")))
        return literal
