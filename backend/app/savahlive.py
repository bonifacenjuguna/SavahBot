"""SavahLive: the backend side of the Android floating-overlay companion (1.5.0).

SavahBot does the work, SavahLive displays the results. This module only does three things:

  * Pairing. The dashboard makes a one-time code (QR + 8 letters, valid 5 minutes). The phone swaps it for its own long-lived device key.
    Only a hash of the key is stored. The key is never a dashboard sign-in: it opens exactly one door, the feed below, and the dashboard's
    own sign-in refuses it (different prefix).
  * Devices. Every paired phone is listed in Manage > SavahLive, with a name, last seen and an optional expiry. Revoking one cuts its feed
    on the spot. A phone is never asked to pair again unless you revoke it, an expiry you chose passes, or (optionally) it sits unused.
  * The feed. One Server-Sent Events stream per phone, built from what the backend already produces (chat, viewers, likes, stream state).
    Nothing is fetched from YouTube for it and nothing is moderated for it. Chat is trimmed to what an overlay shows and sent in small batches.

Existing behaviour is untouched: new tables, new routes, new settings, and a read-only listener on the event bus.
"""
from __future__ import annotations

import asyncio
import collections
import hashlib
import json
import logging
import re
import secrets
import time
from typing import Any, AsyncIterator, Callable

from .db import register_schema
from .security import SharedThrottle

logger = logging.getLogger("savahbot.savahlive")

PROTOCOL = 1                                    # the feed's version: a future server keeps answering old apps, a new app can tell an old server
KEY_PREFIX = "sld_"                              # device keys. The dashboard's sign-in only accepts "sbs_", so one can never stand in for the other
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"     # no I, L, O, 0 or 1: nothing to mix up when typing
CODE_LEN = 8
CODE_RE = re.compile(r"^[A-Z0-9]{8}$")
CODE_TTL = 300
EXPIRY_CHOICES = (0, 1, 7, 30)                   # days; 0 = until removed
PREV_KEY_GRACE = 86400                           # after a key swap the old key still works for a day, so a lost reply never locks a phone out
MAX_BATCH = 25                                   # chat lines in one message; a raid sends the newest ones and says how many were left out
FEED_TICK = 5.0
HEARTBEAT = 15.0
CHAT_MAX_AGE = 180                               # history found when the bot connects is not "new chat"; the overlay never replays it live
SEND_MAX = 200                                   # longest message a phone may send
SEND_GAP = 2.0                                   # seconds between two messages from one phone
SEND_PER_MINUTE = 12                             # and no more than this many in a minute
MOD_GAP = 1.0                                    # seconds between two moderation taps from one phone
MOD_PER_MINUTE = 20
MOD_TIMEOUT = 300                                # a phone times someone out for five minutes; bans stay on the dashboard

register_schema([
    """CREATE TABLE IF NOT EXISTS live_devices (
        id TEXT PRIMARY KEY, key_hash TEXT NOT NULL UNIQUE, prev_hash TEXT NOT NULL DEFAULT '', prev_until {REAL} NOT NULL DEFAULT 0,
        name TEXT NOT NULL, created {REAL} NOT NULL, last_seen {REAL} NOT NULL, key_issued {REAL} NOT NULL, expires {REAL},
        revoked_ts {REAL}, revoked_reason TEXT NOT NULL DEFAULT '', ip TEXT NOT NULL DEFAULT '', app_version TEXT NOT NULL DEFAULT '')""",
    "CREATE INDEX IF NOT EXISTS idx_live_devices_prev ON live_devices (prev_hash)",
    "CREATE TABLE IF NOT EXISTS live_pair_codes (code_hash TEXT PRIMARY KEY, created {REAL} NOT NULL, expires {REAL} NOT NULL, used_ts {REAL}, expiry_days INTEGER NOT NULL DEFAULT 0)",
], columns=[("live_devices", "can_send", "INTEGER NOT NULL DEFAULT 0"), ("live_devices", "can_mod", "INTEGER NOT NULL DEFAULT 0")])

# overlay settings the phone receives: name in the feed -> (setting, kind, low, high)
OVERLAY: dict[str, tuple[str, str, int, int]] = {
    "chat_lines": ("savahlive_chat_lines", "int", 10, 100),
    "peek_seconds": ("savahlive_peek_seconds", "int", 2, 15),
    "font_size": ("savahlive_font_size", "int", 11, 22),
    "hide_seconds": ("savahlive_hide_seconds", "int", 0, 30),
    "hide_bots": ("savahlive_hide_bots", "bool", 0, 1),
    "hide_flagged": ("savahlive_hide_flagged", "bool", 0, 1),
    "only_special": ("savahlive_only_special", "bool", 0, 1),
}
SPECIAL_LEVELS = ("member", "regular", "mod", "owner")


class LiveError(Exception):
    """A refusal the routes turn into a JSON error. `code` lets the phone tell "forget this pairing" from "try again later"."""

    def __init__(self, message: str, status: int = 400, code: str | None = None) -> None:
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def clean_code(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()


def show_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'), default=str)}\n\n"


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


class SavahLive:
    def __init__(self, c: Any) -> None:
        self.c = c
        self.db = c.db
        self.cfg = c.cfg
        self.feeds: dict[str, asyncio.Queue] = {}                 # device id -> the queue of its open feed (one per phone)
        self.throttle = SharedThrottle(c.shared, 8, 900)          # per address
        self.global_throttle = SharedThrottle(c.shared, 30, 900)  # all addresses together: guessing codes from many places still hits a wall
        self._next_clean = 0.0
        self._modded: dict[str, collections.deque[float]] = {}   # same idea for moderation taps
        self._sent: dict[str, collections.deque[float]] = {}      # device id -> when its recent messages were sent (for the rate limit)

    # ------------------------------------------------------------------ settings
    def overlay_settings(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, (key, kind, low, high) in OVERLAY.items():
            raw = self.cfg.get(key)
            out[name] = bool(raw) if kind == "bool" else _clamp(raw, low, high, low)
        return out

    def limit(self, key: str, low: int, high: int) -> int:
        return _clamp(self.cfg.get(key), low, high, low)

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("savahlive_enabled"))

    def may_send(self, row: dict[str, Any] | None) -> bool:
        """Sending chat from a phone needs both: the master switch in Manage > SavahLive, and this phone's own permission (off until you give it)."""
        return bool(self.cfg.get("savahlive_send_enabled")) and bool(row and row.get("can_send"))

    def may_moderate(self, row: dict[str, Any] | None) -> bool:
        """Hiding messages and timing people out from a phone needs the master switch and this phone's own permission (both off until you turn them on)."""
        return bool(self.cfg.get("savahlive_mod_enabled")) and bool(row and row.get("can_mod"))

    def _feed_settings(self, row: dict[str, Any] | None) -> dict[str, Any]:
        return {**self.overlay_settings(), "can_send": self.may_send(row), "can_mod": self.may_moderate(row)}

    def update_info(self) -> dict[str, Any]:
        """What the app needs to say "a newer version exists": the server's own version (kept equal to the app's by the release script) and the download link."""
        from . import __version__
        return {"version": __version__, "url": str(self.cfg.get("savahlive_download_url") or "")}

    # ------------------------------------------------------------------ pairing
    async def new_code(self, expiry_days: int = 0) -> dict[str, Any]:
        if expiry_days not in EXPIRY_CHOICES:
            raise LiveError("Choose how long the pairing lasts: until removed, 30, 7 or 1 day.", 422)
        now = time.time()
        await self.db.execute("DELETE FROM live_pair_codes WHERE expires < ? OR used_ts IS NOT NULL", (now - 3600,))
        old = await self.db.fetchall("SELECT code_hash FROM live_pair_codes WHERE used_ts IS NULL AND expires > ? ORDER BY created DESC", (now,))
        for row in old[4:]:                                           # at most five waiting codes: asking again never leaves a pile of live ones
            await self.db.execute("DELETE FROM live_pair_codes WHERE code_hash = ?", (row["code_hash"],))
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
        await self.db.execute("INSERT INTO live_pair_codes (code_hash, created, expires, used_ts, expiry_days) VALUES (?, ?, ?, NULL, ?)",
                              (_h(code), now, now + CODE_TTL, expiry_days))
        return {"code": code, "shown": show_code(code), "expires": now + CODE_TTL, "expires_in": CODE_TTL, "expiry_days": expiry_days}

    async def active_count(self) -> int:
        row = await self.db.fetchone("SELECT COUNT(*) AS n FROM live_devices WHERE revoked_ts IS NULL AND (expires IS NULL OR expires > ?)", (time.time(),))
        return int(row["n"]) if row else 0

    async def redeem(self, code: str, name: str, app_version: str, ip: str) -> dict[str, Any]:
        if not self.enabled:
            raise LiveError("SavahLive is turned off in SavahBot (Manage > SavahLive).", 403, "disabled")
        keys = (f"pair:{ip}", "pair:all")
        wait = max(await self.throttle.retry_after(keys[0]), await self.global_throttle.retry_after(keys[1]))
        if wait:
            raise LiveError(f"Too many wrong codes. Try again in {max(1, wait // 60 + 1)} minutes.", 429, "throttled")
        now = time.time()
        norm = clean_code(code)
        row = await self.db.fetchone("SELECT * FROM live_pair_codes WHERE code_hash = ?", (_h(norm),)) if CODE_RE.match(norm) else None
        if not row or row["used_ts"] is not None or row["expires"] < now:
            await self.throttle.fail(keys[0])
            await self.global_throttle.fail(keys[1])
            raise LiveError("That code is not valid or has run out. Make a new one in SavahBot (Manage > SavahLive).", 400, "bad_code")
        cap = self.limit("savahlive_max_devices", 1, 20)
        if await self.active_count() >= cap:
            raise LiveError(f"{cap} phones are already paired. Remove one in SavahBot (Manage > SavahLive) first.", 409, "too_many")
        taken = await self.db.execute("UPDATE live_pair_codes SET used_ts = ? WHERE code_hash = ? AND used_ts IS NULL", (now, row["code_hash"]))
        if taken != 1:                                                # someone used it in the same instant: a code is good exactly once
            raise LiveError("That code was just used. Make a new one in SavahBot.", 400, "bad_code")
        days = int(row["expiry_days"] or 0)
        did = "d_" + secrets.token_hex(4)
        key = KEY_PREFIX + secrets.token_urlsafe(32)
        label = " ".join((name or "").split())[:40] or "Android phone"
        expires = now + days * 86400 if days else None
        await self.db.execute(
            "INSERT INTO live_devices (id, key_hash, prev_hash, prev_until, name, created, last_seen, key_issued, expires, revoked_ts, revoked_reason, ip, app_version) "
            "VALUES (?, ?, '', 0, ?, ?, ?, ?, ?, NULL, '', ?, ?)", (did, _h(key), label, now, now, now, expires, ip[:64], (app_version or "")[:20]))
        await self.throttle.success(keys[0])
        await self.c.access.audit("savahlive_paired", None, ip, f"{label} ({did})")
        await self.c.access._alert(f"📱 A phone was paired with SavahLive: {label}. If this was not you, open Manage > SavahLive and remove it.")
        return {"key": key, "device_id": did, "name": label, "expires": expires, "protocol": PROTOCOL}

    # ------------------------------------------------------------------ device keys
    async def _row(self, header: str) -> tuple[dict[str, Any], bool]:
        if not header.lower().startswith("bearer "):
            raise LiveError("Pair this phone with SavahBot first.", 401, "unpaired")
        token = header[7:].strip()
        if not token.startswith(KEY_PREFIX) or len(token) > 200:
            raise LiveError("Pair this phone with SavahBot first.", 401, "unpaired")
        h, now = _h(token), time.time()
        row = await self.db.fetchone("SELECT * FROM live_devices WHERE key_hash = ? OR (prev_hash = ? AND prev_until > ?)", (h, h, now))
        if not row:
            raise LiveError("SavahBot does not know this phone (any more). Pair it again.", 401, "unpaired")
        return row, row["key_hash"] != h

    async def check(self, row: dict[str, Any]) -> None:
        """The rules every request and every few seconds of an open feed obey. 401 = forget the pairing, 403 = keep it and retry later."""
        now = time.time()
        if row["revoked_ts"]:
            raise LiveError("This phone was unpaired from SavahBot. Pair it again to continue.", 401, "revoked")
        if row["expires"] is not None and row["expires"] < now:
            raise LiveError("The pairing for this phone has ended. Pair it again to continue.", 401, "expired")
        idle = self.limit("savahlive_idle_unpair_days", 0, 365)
        if idle and now - row["last_seen"] > idle * 86400:
            await self.revoke(row["id"], f"not used for {idle} days")
            raise LiveError("This phone was unpaired because it was not used for a while. Pair it again to continue.", 401, "idle")
        if not self.enabled:
            raise LiveError("SavahLive is switched off in SavahBot.", 403, "disabled")
        if self.c.access.lockdown:
            raise LiveError("SavahBot is in lockdown.", 403, "lockdown")

    async def device(self, header: str) -> dict[str, Any]:
        row, via_prev = await self._row(header)
        await self.check(row)
        row["via_prev"] = via_prev
        return row

    async def touch(self, did: str, app_version: str = "") -> None:
        if app_version:
            await self.db.execute("UPDATE live_devices SET last_seen = ?, app_version = ? WHERE id = ?", (time.time(), app_version[:20], did))
        else:
            await self.db.execute("UPDATE live_devices SET last_seen = ? WHERE id = ?", (time.time(), did))

    def wants_rotation(self, row: dict[str, Any]) -> bool:
        days = self.limit("savahlive_rotate_days", 0, 365)
        return bool(row.get("via_prev")) or bool(days and time.time() - row["key_issued"] > days * 86400)

    async def rotate(self, row: dict[str, Any], presented_hash: str) -> str:
        """A fresh key. The one the phone just used keeps working for a day, so a reply that never arrived costs nothing."""
        key = KEY_PREFIX + secrets.token_urlsafe(32)
        now = time.time()
        await self.db.execute("UPDATE live_devices SET key_hash = ?, prev_hash = ?, prev_until = ?, key_issued = ?, last_seen = ? WHERE id = ?",
                              (_h(key), presented_hash, now + PREV_KEY_GRACE, now, now, row["id"]))
        return key

    # ------------------------------------------------------------------ managing devices
    async def devices(self) -> list[dict[str, Any]]:
        now = time.time()
        rows = await self.db.fetchall("SELECT id, name, created, last_seen, expires, ip, app_version, can_send, can_mod FROM live_devices WHERE revoked_ts IS NULL ORDER BY created DESC")
        for r in rows:
            r["online"] = r["id"] in self.feeds
            r["status"] = "expired" if r["expires"] is not None and r["expires"] < now else "active"
            r["can_send"] = bool(r["can_send"])
            r["can_mod"] = bool(r["can_mod"])
        return rows

    async def revoke(self, did: str, reason: str = "removed by you") -> bool:
        n = await self.db.execute("UPDATE live_devices SET revoked_ts = ?, revoked_reason = ? WHERE id = ? AND revoked_ts IS NULL", (time.time(), reason[:100], did))
        self.kick(did, "revoked")
        return bool(n)

    async def revoke_all(self, reason: str = "all phones removed") -> int:
        rows = await self.db.fetchall("SELECT id FROM live_devices WHERE revoked_ts IS NULL")
        for r in rows:
            await self.revoke(r["id"], reason)
        return len(rows)

    async def edit(self, did: str, name: str | None, expiry_days: int | None, can_send: bool | None = None, can_mod: bool | None = None) -> bool:
        row = await self.db.fetchone("SELECT id FROM live_devices WHERE id = ? AND revoked_ts IS NULL", (did,))
        if not row:
            return False
        if name is not None:
            label = " ".join(name.split())[:40]
            if not label:
                raise LiveError("Give the phone a name.", 422)
            await self.db.execute("UPDATE live_devices SET name = ? WHERE id = ?", (label, did))
        if expiry_days is not None:
            if expiry_days not in EXPIRY_CHOICES:
                raise LiveError("Choose until removed, 30, 7 or 1 day.", 422)
            await self.db.execute("UPDATE live_devices SET expires = ? WHERE id = ?", (time.time() + expiry_days * 86400 if expiry_days else None, did))
        if can_send is not None:
            await self.db.execute("UPDATE live_devices SET can_send = ? WHERE id = ?", (1 if can_send else 0, did))
        if can_mod is not None:
            await self.db.execute("UPDATE live_devices SET can_mod = ? WHERE id = ?", (1 if can_mod else 0, did))
        return True

    def kick(self, did: str, reason: str) -> None:
        q = self.feeds.get(did)
        if q is not None:
            try:
                q.put_nowait({"type": "_kick", "data": {"code": reason}})
            except asyncio.QueueFull:
                pass

    # ------------------------------------------------------------------ sending chat from a phone
    async def send(self, dev: dict[str, Any], text: str, ip: str = "") -> None:
        """Post one chat message as SavahBot's own account (the one it is signed in to YouTube with). Off until you allow this phone."""
        if not self.cfg.get("savahlive_send_enabled"):
            raise LiveError("Sending chat from phones is switched off in SavahBot (Manage > SavahLive).", 403, "send_off")
        fresh = await self.db.fetchone("SELECT can_send FROM live_devices WHERE id = ?", (dev["id"],))        # read now: a change made a moment ago counts
        if not fresh or not fresh["can_send"]:
            raise LiveError("This phone is not allowed to send chat. Allow it in SavahBot (Manage > SavahLive).", 403, "send_denied")
        clean = " ".join((text or "").split())[:SEND_MAX]                                                       # one line, no control characters
        if not clean:
            raise LiveError("Type a message first.", 422, "empty")
        now = time.monotonic()
        recent = self._sent.setdefault(dev["id"], collections.deque())
        while recent and now - recent[0] > 60:
            recent.popleft()
        if recent and now - recent[-1] < SEND_GAP:
            raise LiveError("One message every couple of seconds, please.", 429, "slow")
        if len(recent) >= SEND_PER_MINUTE:
            raise LiveError("That is a lot of messages. Wait a moment.", 429, "slow")
        if not await self.c.hub.send_chat(clean):
            raise LiveError("SavahBot could not post that. Is it connected to your YouTube chat?", 502, "send_failed")
        recent.append(now)
        await self.c.access.audit("savahlive_sent", None, ip, f"{dev['name']}: {len(clean)} characters")
        q = self.feeds.get(dev["id"])
        if q is not None:      # SavahBot hides its own account's messages from the overlay; the sender should still see what they just said
            try:
                q.put_nowait({"type": "chat", "data": {"id": None, "ts": time.time(), "author_id": "self", "author_name": "You", "text": clean, "level": "owner", "verdict": "allow"}})
            except asyncio.QueueFull:
                pass

    # ------------------------------------------------------------------ moderating from a phone
    async def moderate(self, dev: dict[str, Any], chat_id: int, action: str, ip: str = "") -> None:
        """Hide one message ("delete") or time its author out for five minutes. Same checks as choosing it in the dashboard chat (the owner and the bot cannot be moderated)."""
        if not self.cfg.get("savahlive_mod_enabled"):
            raise LiveError("Moderating from phones is switched off in SavahBot (Manage > SavahLive).", 403, "mod_off")
        fresh = await self.db.fetchone("SELECT can_mod FROM live_devices WHERE id = ?", (dev["id"],))
        if not fresh or not fresh["can_mod"]:
            raise LiveError("This phone is not allowed to moderate. Allow it in SavahBot (Manage > SavahLive).", 403, "mod_denied")
        if action not in ("delete", "timeout"):
            raise LiveError("A phone can hide a message or time someone out.", 422, "bad_action")
        now = time.monotonic()
        recent = self._modded.setdefault(dev["id"], collections.deque())
        while recent and now - recent[0] > 60:
            recent.popleft()
        if (recent and now - recent[-1] < MOD_GAP) or len(recent) >= MOD_PER_MINUTE:
            raise LiveError("Slow down a little.", 429, "slow")
        result = await self.c.hub.manual(int(chat_id), action, MOD_TIMEOUT)
        if not result.get("ok"):
            raise LiveError(str(result.get("error") or "SavahBot could not do that."), int(result.get("code") or 502), "mod_failed")
        recent.append(now)
        await self.c.access.audit("savahlive_moderated", None, ip, f"{dev['name']}: {action}")

    # ------------------------------------------------------------------ housekeeping (leader, from the scheduler)
    async def tick(self, now: float) -> None:
        if now < self._next_clean:
            return
        self._next_clean = now + 3600
        await self.db.execute("DELETE FROM live_pair_codes WHERE expires < ?", (now - 3600,))
        await self.db.execute("DELETE FROM live_devices WHERE revoked_ts IS NOT NULL AND revoked_ts < ?", (now - 30 * 86400,))
        idle = self.limit("savahlive_idle_unpair_days", 0, 365)
        if idle:
            for r in await self.db.fetchall("SELECT id FROM live_devices WHERE revoked_ts IS NULL AND last_seen < ?", (now - idle * 86400,)):
                await self.revoke(r["id"], f"not used for {idle} days")

    # ------------------------------------------------------------------ what the overlay shows
    def state(self) -> dict[str, Any]:
        h = self.c.hub
        demo = h.mode == "demo"
        return {"mode": h.mode, "live": bool(h.stream_live) or demo, "title": (h.stream_title or ("Demo stream" if demo else ""))[:120]}

    def stats(self, state: dict[str, Any]) -> dict[str, Any]:
        if state["mode"] == "demo":
            from .api.routes import demo_live_stats
            d = demo_live_stats()
        elif state["live"]:
            d = self.c.extras.live
        else:
            d = {}
        return {"viewers": d.get("viewers"), "likes": d.get("likes"), "likes_hidden": bool(d.get("likes_hidden")), "peak": d.get("peak_viewers") or 0,
                "updated": d.get("updated") or 0, "note": (d.get("note") or "")[:160], "enabled": bool(self.cfg.get("yt_live_enabled")) or state["mode"] == "demo"}

    @staticmethod
    def visible(m: dict[str, Any], s: dict[str, Any]) -> bool:
        if s["hide_bots"] and (m.get("from_bot") or m.get("level") == "bot"):
            return False
        if s["hide_flagged"] and (m.get("verdict") or "allow") != "allow":
            return False
        if s["only_special"] and m.get("level") not in SPECIAL_LEVELS:
            return False
        return bool((m.get("text") or "").strip())

    @staticmethod
    def line(m: dict[str, Any]) -> dict[str, Any]:
        return {"id": m.get("id"), "uid": str(m.get("author_id") or "")[:64], "name": str(m.get("author_name") or "")[:40],
                "text": str(m.get("text") or "")[:300], "level": m.get("level") or "everyone", "ts": int(m.get("ts") or 0)}

    def recent(self, since: int, settings: dict[str, Any]) -> list[dict[str, Any]]:
        out = [self.line(m) for m in list(self.c.hub.buffer) if self.visible(m, settings) and (m.get("id") or 0) > since]
        return out[-settings["chat_lines"]:]

    def can_open(self, did: str) -> bool:
        return did in self.feeds or len(self.feeds) < self.limit("savahlive_max_feeds", 1, 20)

    # ------------------------------------------------------------------ the feed
    async def stream(self, dev: dict[str, Any], since: int, disconnected: Callable[[], Any]) -> AsyncIterator[str]:
        did = dev["id"]
        bus = self.c.bus
        q = bus.subscribe(maxsize=400, counted=False)      # a phone never uses up one of the dashboard's connection slots
        previous = self.feeds.get(did)
        self.feeds[did] = q
        if previous is not None:                                      # a reconnecting phone replaces its own half-dead old connection
            try:
                previous.put_nowait({"type": "_kick", "data": {"code": "replaced"}})
            except asyncio.QueueFull:
                pass
        try:
            await self.touch(did)
            settings = self._feed_settings(dev)
            state = self.state()
            stats = self.stats(state)
            yield "retry: 5000\n\n"
            yield sse("hello", {"v": PROTOCOL, "server_time": time.time(), "device": {"id": did, "name": dev["name"], "expires": dev["expires"]},
                                "rotate": self.wants_rotation(dev), "update": self.update_info(), "state": state, "stats": stats, "settings": settings,
                                "chat": self.recent(since, settings)})
            last = {"state": state, "stats": {k: v for k, v in stats.items() if k != "updated"}, "settings": settings}
            sent_at = checked = touched = time.monotonic()
            while True:
                try:
                    ev: dict[str, Any] | None = await asyncio.wait_for(q.get(), timeout=FEED_TICK)
                except asyncio.TimeoutError:
                    ev = None
                out: list[str] = []
                if ev is not None:
                    batch = [ev]
                    if ev.get("type") == "chat":
                        await asyncio.sleep(0.25)                     # a short pause lets a burst travel as one message
                    while len(batch) < 500:
                        try:
                            batch.append(q.get_nowait())
                        except asyncio.QueueEmpty:
                            break
                    lines: list[dict[str, Any]] = []
                    uids: list[str] = []
                    ids: list[int] = []
                    dirty = False
                    now = time.time()
                    for e in batch:
                        kind, data = e.get("type"), e.get("data") or {}
                        if kind == "_kick":
                            yield sse("unpaired", {"code": data.get("code", "revoked")})
                            return
                        if kind == "chat":
                            if now - float(data.get("ts") or now) <= CHAT_MAX_AGE and self.visible(data, settings):
                                lines.append(self.line(data))
                        elif kind == "ban_made" and data.get("author_id"):
                            uids.append(str(data["author_id"])[:64])
                        elif kind == "chat_deleted" and data.get("id"):
                            ids.append(int(data["id"]))
                        elif kind in ("stream", "session", "mode"):
                            dirty = True
                    if len(lines) > MAX_BATCH:
                        skipped, lines = len(lines) - MAX_BATCH, lines[-MAX_BATCH:]
                    else:
                        skipped = 0
                    if lines:
                        out.append(sse("chat", {"lines": lines, "skipped": skipped}))
                    if uids or ids:
                        out.append(sse("purge", {"uids": uids, "ids": ids}))
                    if dirty:
                        checked = 0.0                                 # look at the state right now, not at the next tick
                tnow = time.monotonic()
                if tnow - checked >= FEED_TICK:
                    checked = tnow
                    if await disconnected():
                        return
                    row = await self.db.fetchone("SELECT * FROM live_devices WHERE id = ?", (did,))
                    try:
                        if row is None:
                            raise LiveError("", 401, "revoked")
                        await self.check(row)
                    except LiveError as err:
                        yield sse("unpaired", {"code": err.code or "revoked"})
                        return
                    state = self.state()
                    settings = self._feed_settings(row)
                    stats = self.stats(state)
                    trimmed = {k: v for k, v in stats.items() if k != "updated"}
                    if state != last["state"]:
                        out.append(sse("state", state))
                    if trimmed != last["stats"]:
                        out.append(sse("stats", stats))
                    if settings != last["settings"]:
                        out.append(sse("settings", settings))
                    last = {"state": state, "stats": trimmed, "settings": settings}
                if tnow - touched >= 60:
                    touched = tnow
                    await self.touch(did)
                if out:
                    sent_at = tnow
                    for piece in out:
                        yield piece
                elif tnow - sent_at >= HEARTBEAT:
                    sent_at = tnow
                    yield ": ping\n\n"
        finally:
            if self.feeds.get(did) is q:
                del self.feeds[did]
            bus.unsubscribe(q)
