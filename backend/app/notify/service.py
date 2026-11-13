"""The Notification Centre: preferences, the inbox, devices, the delivery pipeline and the retry worker.

An event goes through one pipeline (`emit`): known category -> master switch -> category switch -> duplicate folding ->
inbox row -> per channel (in-app, push, Telegram) -> quiet hours / pause / hourly cap -> delivery rows. A worker (`tick`,
leader only) sends the rows with retries and clears dead device tokens. The database is the source of truth; Redis is
only used elsewhere for speed.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..db import register_schema
from ..utils import truncate
from . import categories as cats
from .fcm import Fcm

logger = logging.getLogger("savahbot.notify")

register_schema([
    """CREATE TABLE IF NOT EXISTS notifications (
        id {PK}, ts {REAL} NOT NULL, category TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', route TEXT NOT NULL DEFAULT '',
        priority TEXT NOT NULL DEFAULT 'normal', kind TEXT NOT NULL DEFAULT 'info', icon TEXT NOT NULL DEFAULT 'bell', dedupe_key TEXT NOT NULL DEFAULT '',
        count INTEGER NOT NULL DEFAULT 1, read_ts {REAL}, data TEXT NOT NULL DEFAULT '', ack_ts {REAL})""",
    "CREATE INDEX IF NOT EXISTS idx_notifications_ts ON notifications (ts)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_key ON notifications (dedupe_key, ts)",
    """CREATE TABLE IF NOT EXISTS notify_deliveries (
        id {PK}, notification_id INTEGER, channel TEXT NOT NULL, device_id INTEGER, status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
        next_try {REAL} NOT NULL, created {REAL} NOT NULL, done_ts {REAL}, error TEXT NOT NULL DEFAULT '', idem TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '',
        priority TEXT NOT NULL DEFAULT 'normal', note TEXT NOT NULL DEFAULT '')""",
    "CREATE INDEX IF NOT EXISTS idx_notify_deliveries_due ON notify_deliveries (status, next_try)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_notify_deliveries_idem ON notify_deliveries (idem)",
    """CREATE TABLE IF NOT EXISTS notify_devices (
        id {PK}, token_hash TEXT NOT NULL UNIQUE, token_enc TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', platform TEXT NOT NULL DEFAULT '', browser TEXT NOT NULL DEFAULT '',
        installed INTEGER NOT NULL DEFAULT 0, created {REAL} NOT NULL, last_seen {REAL} NOT NULL, last_ok {REAL}, last_error TEXT NOT NULL DEFAULT '', fail_count INTEGER NOT NULL DEFAULT 0,
        enabled INTEGER NOT NULL DEFAULT 1)""",
], columns=[
    # a table left behind by an earlier build is topped up with whatever it lacks
    ("notifications", "ts", "DOUBLE PRECISION NOT NULL DEFAULT 0"), ("notifications", "category", "TEXT NOT NULL DEFAULT ''"), ("notifications", "title", "TEXT NOT NULL DEFAULT ''"),
    ("notifications", "body", "TEXT NOT NULL DEFAULT ''"), ("notifications", "route", "TEXT NOT NULL DEFAULT ''"), ("notifications", "priority", "TEXT NOT NULL DEFAULT 'normal'"),
    ("notifications", "kind", "TEXT NOT NULL DEFAULT 'info'"), ("notifications", "icon", "TEXT NOT NULL DEFAULT 'bell'"), ("notifications", "dedupe_key", "TEXT NOT NULL DEFAULT ''"),
    ("notifications", "count", "INTEGER NOT NULL DEFAULT 1"), ("notifications", "read_ts", "DOUBLE PRECISION"), ("notifications", "data", "TEXT NOT NULL DEFAULT ''"), ("notifications", "ack_ts", "DOUBLE PRECISION"),
])

DEFAULT_PREFS: dict[str, Any] = {
    "enabled": True, "push": True, "inapp": True, "telegram": True, "categories": {},
    "quiet": {"enabled": False, "start": "22:00", "end": "07:00", "mode": "hold", "critical_breaks": True},
    "pause_until": 0, "hide_body_locked": False,
}
BACKOFF = (30, 120, 600, 3600, 6 * 3600)
ROUTE_RE = re.compile(r"^#/[A-Za-z0-9_\-/]{0,60}(\?[A-Za-z0-9_=&.\-%]{0,120})?$")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def safe_route(route: str, fallback: str = "#/notifications") -> str:
    """Only in-app hash routes may be opened by a tap. Anything else (other sites, javascript:, data:) becomes the fallback."""
    route = (route or "").strip()
    return route if ROUTE_RE.match(route) else fallback


class NotifyError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message, self.status = message, status


class Notifier:
    def __init__(self, db: Any, cfg: Any, settings: Any, bus: Any, secret_fn: Any = None, telegram: Any = None) -> None:
        self.db, self.cfg, self.settings, self.bus = db, cfg, settings, bus
        self._secret_fn = secret_fn or (lambda: "savahbot-test-secret")
        self.telegram = telegram            # async callable(text) -> None, the hub's _notify
        self._drain_lock = asyncio.Lock()
        self.fcm = Fcm(settings.firebase_project_id, settings.firebase_client_email, settings.firebase_private_key, settings.firebase_service_account_json)
        self.active: Any = None             # leader check; only the leader listens to events and sends
        self._prefs: dict[str, Any] | None = None
        self._unsub: Any = None
        self._q: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None
        self._last_purge = 0.0
        self._quota_level = 0
        self._quota_day = ""
        self._seen_errors: dict[str, str] = {}
        self._hourly: list[float] = []
        self._tg_fail_streak = 0
        self.container: Any = None

    # ------------------------------------------------------------------ secrets and tokens
    def _key(self) -> bytes:
        return hashlib.sha256(b"savahbot-fcm|" + str(self._secret_fn()).encode()).digest()

    def seal(self, token: str) -> str:
        nonce = secrets.token_bytes(12)
        return base64.b64encode(nonce + AESGCM(self._key()).encrypt(nonce, token.encode(), b"fcm")).decode()

    def unseal(self, blob: str) -> str:
        raw = base64.b64decode(blob)
        return AESGCM(self._key()).decrypt(raw[:12], raw[12:], b"fcm").decode()

    @staticmethod
    def thash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    # ------------------------------------------------------------------ public config (safe to show)
    def web_config(self) -> dict[str, Any]:
        s = self.settings
        cfg = {"apiKey": s.firebase_web_api_key, "projectId": self.fcm.project or s.firebase_project_id, "appId": s.firebase_web_app_id,
               "messagingSenderId": s.firebase_messaging_sender_id}
        if s.firebase_auth_domain:
            cfg["authDomain"] = s.firebase_auth_domain
        return cfg

    def web_ready(self) -> bool:
        c = self.web_config()
        return all(c[k] for k in ("apiKey", "projectId", "appId", "messagingSenderId")) and bool(self.settings.firebase_vapid_key)

    def checklist(self) -> list[dict[str, Any]]:
        s = self.settings
        rows = [("FIREBASE_PROJECT_ID", bool(self.fcm.project)), ("FIREBASE_CLIENT_EMAIL", bool(self.fcm.email)), ("FIREBASE_PRIVATE_KEY", bool(self.fcm._pem)),
                ("FIREBASE_WEB_API_KEY", bool(s.firebase_web_api_key)), ("FIREBASE_WEB_APP_ID", bool(s.firebase_web_app_id)),
                ("FIREBASE_MESSAGING_SENDER_ID", bool(s.firebase_messaging_sender_id)), ("FIREBASE_VAPID_KEY", bool(s.firebase_vapid_key))]
        return [{"name": n, "set": ok} for n, ok in rows]

    # ------------------------------------------------------------------ preferences
    async def prefs(self) -> dict[str, Any]:
        if self._prefs is None:
            raw = await self.db.kv_get("notify_prefs")
            try:
                saved = json.loads(raw) if raw else {}
            except ValueError:
                saved = {}
            self._prefs = self._merge(saved)
        return self._prefs

    @staticmethod
    def _merge(saved: dict[str, Any]) -> dict[str, Any]:
        out = json.loads(json.dumps(DEFAULT_PREFS))
        for k in ("enabled", "push", "inapp", "telegram", "hide_body_locked"):
            if isinstance(saved.get(k), bool):
                out[k] = saved[k]
        if isinstance(saved.get("pause_until"), (int, float)):
            out["pause_until"] = float(saved["pause_until"])
        q = saved.get("quiet")
        if isinstance(q, dict):
            if isinstance(q.get("enabled"), bool):
                out["quiet"]["enabled"] = q["enabled"]
            for k in ("start", "end"):
                if isinstance(q.get(k), str) and HHMM.match(q[k]):
                    out["quiet"][k] = q[k]
            if q.get("mode") in ("hold", "silent"):
                out["quiet"]["mode"] = q["mode"]
            if isinstance(q.get("critical_breaks"), bool):
                out["quiet"]["critical_breaks"] = q["critical_breaks"]
        for cid, v in (saved.get("categories") or {}).items():
            if cid in cats.REGISTRY and isinstance(v, dict):
                clean = {k: v[k] for k in ("enabled", "push", "inapp", "telegram") if isinstance(v.get(k), bool)}
                if v.get("priority") in cats.PRIORITIES:
                    clean["priority"] = v["priority"]
                if clean:
                    out["categories"][cid] = clean
        return out

    async def set_prefs(self, patch: dict[str, Any]) -> dict[str, Any]:
        cur = json.loads(json.dumps(await self.prefs()))
        for k, v in patch.items():
            if k == "categories" and isinstance(v, dict):
                for cid, cv in v.items():
                    if cid not in cats.REGISTRY:
                        raise NotifyError(f"Unknown category {cid}")
                    cur["categories"].setdefault(cid, {}).update(cv)
            elif k == "quiet" and isinstance(v, dict):
                if "start" in v and not HHMM.match(str(v["start"])) or "end" in v and not HHMM.match(str(v["end"])):
                    raise NotifyError("Quiet hours must look like 22:00")
                cur["quiet"].update(v)
            elif k in DEFAULT_PREFS:
                cur[k] = v
        self._prefs = self._merge(cur)
        await self.db.kv_set("notify_prefs", json.dumps(self._prefs))
        act = getattr(self, "activity", None)
        if act is not None and patch.get("pause_until") is None:
            # `[x] * bool(...)` built x first and raised KeyError("categories") on every toggle that did not touch categories (1.3.2): the API then answered "Unknown item: categories"
            what = [k for k in patch if k != "categories"]
            if patch.get("categories"):
                what.append(f"{len(patch['categories'])} kind(s)")
            await act.record("notifications", "prefs", "Changed notification settings: " + ", ".join(what).replace("_", " ")[:150], "notable" if "categories" in patch or "enabled" in patch else "routine")
        return self._prefs

    def effective(self, prefs: dict[str, Any], cid: str) -> dict[str, Any]:
        c = cats.REGISTRY[cid]
        o = prefs["categories"].get(cid, {})
        return {"enabled": o.get("enabled", True), "push": o.get("push", c.push), "inapp": o.get("inapp", c.inapp),
                "telegram": o.get("telegram", c.telegram) and not c.telegram_native, "priority": o.get("priority", c.priority)}

    def quiet_now(self, prefs: dict[str, Any], now: float) -> tuple[bool, float]:
        """(inside quiet hours, when they end as epoch seconds)."""
        q = prefs["quiet"]
        if not q["enabled"]:
            return False, 0.0
        try:
            tz = ZoneInfo(self.cfg.get("owner_timezone") or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo("UTC")
        local = datetime.fromtimestamp(now, tz)
        sh, sm = map(int, q["start"].split(":"))
        eh, em = map(int, q["end"].split(":"))
        start = local.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = local.replace(hour=eh, minute=em, second=0, microsecond=0)
        if start == end:
            return False, 0.0
        if start < end:
            inside = start <= local < end
        else:                                   # overnight window such as 22:00 to 07:00
            inside = local >= start or local < end
            if local >= start:
                end += timedelta(days=1)
        return inside, end.timestamp() if inside else 0.0

    # ------------------------------------------------------------------ emit
    async def emit(self, cid: str, title: str, body: str = "", *, route: str = "", key: str = "", data: dict[str, Any] | None = None,
                   priority: str | None = None, now: float | None = None) -> int | None:
        c = cats.REGISTRY.get(cid)
        if c is None:
            logger.warning("Unknown notification category %s", cid)
            return None
        now = now if now is not None else time.time()
        prefs = await self.prefs()
        eff = self.effective(prefs, cid)
        if not prefs["enabled"] or not eff["enabled"]:
            return None
        prio = priority if priority in cats.PRIORITIES else eff["priority"]
        route = safe_route(route or c.route, c.route)
        title, body = truncate(title, 120), truncate(body or "", 400)
        nid: int | None = None
        folded = False
        if prefs["inapp"] and eff["inapp"]:
            dk = f"{cid}:{key}" if key else ""
            if dk and c.dedupe_seconds:
                prev = await self.db.fetchone("SELECT id, count FROM notifications WHERE dedupe_key = ? AND read_ts IS NULL AND ts > ? ORDER BY ts DESC LIMIT 1", (dk, now - c.dedupe_seconds))
                if prev:
                    await self.db.execute("UPDATE notifications SET count = count + 1, ts = ?, body = ?, title = ? WHERE id = ?", (now, body, title, prev["id"]))
                    nid, folded = prev["id"], True
            if nid is None:
                nid = await self.db.insert("INSERT INTO notifications (ts, category, title, body, route, priority, kind, icon, dedupe_key, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                           (now, cid, title, body, route, prio, c.kind, c.icon, f"{cid}:{key}" if key else "", json.dumps(data or {})[:2000]))
            if nid and route == "#/notifications":
                route = f"#/notifications?open={nid}"      # a tap on a notification with no page of its own shows that notification
                await self.db.execute("UPDATE notifications SET route = ? WHERE id = ?", (route, nid))
            self.bus.publish("notify", {"id": nid, "category": cid, "title": title, "body": body, "route": route, "kind": c.kind, "icon": c.icon, "priority": prio, "folded": folded})
        if folded:
            return nid                           # one push per burst: later copies only raise the count in the inbox
        if eff["telegram"] and prefs["telegram"] and self.telegram is not None:
            self._spawn(self._telegram(c, title, body))
        if eff["push"] and prefs["push"]:
            await self._queue_push(c, prefs, prio, nid, title, body, route, now)
            self._spawn(self.drain(now))                 # send now instead of waiting for the next scheduler tick
        return nid

    def _spawn(self, coro: Any) -> None:
        t = asyncio.ensure_future(coro)
        t.add_done_callback(lambda f: f.cancelled() or f.exception() is None or logger.error("Notification task failed: %s", f.exception()))

    async def _telegram(self, c: cats.Category, title: str, body: str) -> None:
        from ..services.telegram_ui import esc
        try:
            await self.telegram(f"<b>{esc(title)}</b>" + (f"\n{esc(body)}" if body else ""))
        except Exception:
            logger.exception("Telegram notification failed")

    async def _queue_push(self, c: cats.Category, prefs: dict[str, Any], prio: str, nid: int | None, title: str, body: str, route: str, now: float) -> None:
        devices = await self.db.fetchall("SELECT id FROM notify_devices WHERE enabled = 1")
        if not devices:
            return
        critical = prio == "critical"
        status, next_try = "queued", now
        if now < prefs["pause_until"] and not critical:
            return                                       # paused: the inbox still has it
        inside, ends = self.quiet_now(prefs, now)
        if inside and not (critical and prefs["quiet"]["critical_breaks"] and c.can_override_quiet):
            if prefs["quiet"]["mode"] == "silent":
                return
            status, next_try = "held", ends
        self._hourly = [t for t in self._hourly if now - t < 3600]
        if status == "queued" and not critical and len(self._hourly) >= int(self.cfg.get("notify_max_push_per_hour")):
            status, next_try = "held", now + 900          # over the hourly cap: gather into a summary in a few minutes
        if status == "queued":
            self._hourly.append(now)
        note = "" if nid else json.dumps({"title": title, "body": body, "route": route})   # no inbox row: keep the text with the delivery
        for d in devices:
            idem = f"{nid or 'x'}:{c.id}:{d['id']}:{int(now * 1000)}"
            try:
                await self.db.insert("INSERT INTO notify_deliveries (notification_id, channel, device_id, status, next_try, created, idem, category, priority, note) VALUES (?, 'push', ?, ?, ?, ?, ?, ?, ?, ?)",
                                     (nid, d["id"], status, next_try, now, idem, c.id, prio, note))
            except Exception:
                logger.debug("Duplicate delivery skipped", exc_info=True)

    # ------------------------------------------------------------------ worker
    async def tick(self, now: float) -> None:
        if self.active is not None and not self.active():
            return
        await self._watch_status(now)
        await self._release_held(now)
        await self.drain(now)
        if now - self._last_purge >= 3600:
            self._last_purge = now
            await self.purge(now)

    async def _release_held(self, now: float) -> None:
        held = await self.db.fetchall("SELECT * FROM notify_deliveries WHERE status = 'held' AND next_try <= ? ORDER BY device_id, created", (now,))
        by_dev: dict[int, list[dict]] = {}
        for r in held:
            by_dev.setdefault(r["device_id"], []).append(r)
        for dev, rows in by_dev.items():
            if len(rows) == 1:
                await self.db.execute("UPDATE notify_deliveries SET status = 'queued' WHERE id = ?", (rows[0]["id"],))
                continue
            # many things piled up: send ONE summary push for them all
            ids = [r["id"] for r in rows]
            marks = ",".join("?" for _ in ids)
            await self.db.execute(f"UPDATE notify_deliveries SET status = 'summarised', done_ts = ? WHERE id IN ({marks})", (now, *ids))
            quiet_cats = {k for k, v in cats.REGISTRY.items() if v.sensitive}
            titles = [t["title"] for t in await self.db.fetchall(f"SELECT title, category FROM notifications WHERE id IN ({','.join('?' for _ in rows)})", tuple(r["notification_id"] or 0 for r in rows)) if t["category"] not in quiet_cats]
            if any(r["category"] in quiet_cats for r in rows):
                titles.append("security alerts")
            note = json.dumps({"title": f"{len(rows)} notifications while you were away", "body": "; ".join(dict.fromkeys(titles))[:200]})
            await self.db.insert("INSERT INTO notify_deliveries (notification_id, channel, device_id, status, next_try, created, idem, category, priority, note) VALUES (NULL, 'push', ?, 'queued', ?, ?, ?, 'summary', 'normal', ?)",
                                 (dev, now, now, f"summary:{dev}:{int(now)}:{secrets.token_hex(3)}", note))

    async def _send_one(self, row: dict[str, Any], now: float) -> None:
        dev = await self.db.fetchone("SELECT * FROM notify_devices WHERE id = ?", (row["device_id"],))
        if not dev or not dev["enabled"]:
            await self.db.execute("UPDATE notify_deliveries SET status = 'cancelled', done_ts = ? WHERE id = ?", (now, row["id"]))
            return
        if not self.fcm.configured:
            await self.db.execute("UPDATE notify_deliveries SET status = 'failed', done_ts = ?, error = 'Firebase is not configured' WHERE id = ?", (now, row["id"]))
            return
        payload = await self._payload(row)
        if payload is None:
            await self.db.execute("UPDATE notify_deliveries SET status = 'cancelled', done_ts = ?, error = 'notification was deleted' WHERE id = ?", (now, row["id"]))
            return
        try:
            token = self.unseal(dev["token_enc"])
        except Exception:
            await self.db.execute("UPDATE notify_devices SET enabled = 0, last_error = 'token could not be decrypted' WHERE id = ?", (dev["id"],))
            await self.db.execute("UPDATE notify_deliveries SET status = 'failed', done_ts = ?, error = 'token unreadable' WHERE id = ?", (now, row["id"]))
            return
        res = await self.fcm.send(token, payload)
        attempts = row["attempts"] + 1
        if res.ok:
            await self.db.execute("UPDATE notify_deliveries SET status = 'sent', attempts = ?, done_ts = ?, error = '' WHERE id = ?", (attempts, now, row["id"]))
            await self.db.execute("UPDATE notify_devices SET last_ok = ?, last_error = '', fail_count = 0 WHERE id = ?", (now, dev["id"]))
        elif res.dead_token:
            await self.db.execute("UPDATE notify_deliveries SET status = 'dead', attempts = ?, done_ts = ?, error = ? WHERE id = ?", (attempts, now, res.error, row["id"]))
            await self.db.execute("DELETE FROM notify_devices WHERE id = ?", (dev["id"],))   # a token Firebase rejects will never work again
            await self.db.execute("UPDATE notify_deliveries SET status = 'cancelled', done_ts = ? WHERE device_id = ? AND status IN ('queued', 'held')", (now, dev["id"]))
        elif res.retry and attempts < int(self.cfg.get("notify_max_attempts")):
            wait = BACKOFF[min(attempts - 1, len(BACKOFF) - 1)]
            await self.db.execute("UPDATE notify_deliveries SET attempts = ?, next_try = ?, error = ? WHERE id = ?", (attempts, now + wait, res.error[:200], row["id"]))
        else:
            await self.db.execute("UPDATE notify_deliveries SET status = 'failed', attempts = ?, done_ts = ?, error = ? WHERE id = ?", (attempts, now, res.error[:200], row["id"]))
            await self.db.execute("UPDATE notify_devices SET last_error = ?, fail_count = fail_count + 1 WHERE id = ?", (res.error[:200], dev["id"]))
            if self.fcm.last_error and row["category"] != "system.firebase":
                await self.emit("system.firebase", "Push messages are failing", res.error[:200], key="firebase", now=now)

    async def _payload(self, row: dict[str, Any]) -> dict[str, Any] | None:
        prefs = await self.prefs()
        if row["category"] == "summary":
            try:
                s = json.loads(row.get("note") or "{}") or {"title": "Notifications", "body": ""}
            except ValueError:
                s = {"title": "Notifications", "body": ""}
            return {"title": s["title"], "body": "" if prefs["hide_body_locked"] else s["body"], "route": "#/notifications", "category": "summary", "tag": "summary", "priority": "normal", "nid": ""}
        n = await self.db.fetchone("SELECT * FROM notifications WHERE id = ?", (row["notification_id"],)) if row["notification_id"] else None
        if n is None and not row["notification_id"] and row.get("note"):
            try:
                s = json.loads(row["note"])
                c0 = cats.REGISTRY.get(row["category"])
                hide0 = prefs["hide_body_locked"] or bool(c0 and c0.sensitive)
                return {"title": s["title"], "body": "" if hide0 else s.get("body", ""), "route": safe_route(s.get("route", "")), "category": row["category"], "tag": f"x{row['id']}",
                        "priority": row["priority"], "nid": "", "kind": c0.kind if c0 else "info"}
            except (ValueError, KeyError, TypeError):
                return None
        if n is None:
            return None
        c = cats.REGISTRY.get(n["category"])
        hide = prefs["hide_body_locked"] or bool(c and c.sensitive)
        return {"title": n["title"], "body": "" if hide else n["body"], "route": safe_route(n["route"]), "category": n["category"], "tag": n["dedupe_key"] or f"n{n['id']}",
                "priority": row["priority"], "nid": str(n["id"]), "kind": n["kind"]}

    async def purge(self, now: float) -> None:
        cut = now - int(self.cfg.get("notify_retention_days")) * 86400
        await self.db.execute("DELETE FROM notifications WHERE ts < ?", (cut,))
        await self.db.execute("DELETE FROM notify_deliveries WHERE created < ? AND status NOT IN ('queued', 'held')", (cut,))
        await self.db.execute("DELETE FROM notify_devices WHERE last_seen < ? AND (last_ok IS NULL OR last_ok < ?)", (now - 90 * 86400, now - 90 * 86400))

    async def drain(self, now: float | None = None) -> None:
        """Sends every queued push that is due, all devices at the same moment. Called right after a notification is queued (so a phone
        is not left waiting for the next scheduler tick) and again by the scheduler for retries and released held messages. Passes never
        overlap: a second caller waits its turn and then finds what the first one already sent marked as sent, so nothing goes out twice."""
        if self.active is not None and not self.active():
            return
        async with self._drain_lock:
            t = time.time() if now is None else now
            due = await self.db.fetchall("SELECT * FROM notify_deliveries WHERE status = 'queued' AND next_try <= ? ORDER BY next_try LIMIT 40", (t,))
            await asyncio.gather(*(self._send_safe(row, t) for row in due))

    async def _send_safe(self, row: dict[str, Any], now: float) -> None:
        try:
            await self._send_one(row, now)
        except Exception as e:
            logger.exception("Push delivery %s crashed", row["id"])
            att = row["attempts"] + 1
            st = "queued" if att < int(self.cfg.get("notify_max_attempts")) else "failed"
            await self.db.execute("UPDATE notify_deliveries SET status = ?, attempts = ?, next_try = ?, error = ? WHERE id = ?", (st, att, now + BACKOFF[min(att - 1, len(BACKOFF) - 1)], f"internal error: {type(e).__name__}", row["id"]))

    # ------------------------------------------------------------------ listening to the rest of the bot
    def start(self) -> None:
        if self._task is not None:
            return
        self._q = asyncio.Queue(maxsize=1000)
        self._tap = lambda ev: ev.get("type") != "notify" and self._q.put_nowait(ev) if not self._q.full() else None
        self.bus.tap(self._tap)
        self._task = asyncio.ensure_future(self._listen())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._q is not None:
            self.bus.untap(self._tap)
            self._q = None

    async def _listen(self) -> None:
        assert self._q is not None
        while True:
            ev = await self._q.get()
            if self.active is not None and not self.active():
                continue
            try:
                await self.handle(ev)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Notification event failed")

    SECURITY = {
        "recovery_code_used": ("A recovery code was used", "Someone signed in with a recovery code."),
        "new_device_signed_in": ("New device signed in", ""),
        "password_changed": ("Dashboard password changed", "Other devices were signed out."),
        "totp_enabled": ("Authenticator app turned on", ""), "totp_removed": ("Authenticator app removed", ""),
        "passkey_added": ("Passkey added", ""), "passkey_removed": ("Passkey removed", ""),
        "recovery_codes_regenerated": ("Recovery codes regenerated", "The old codes no longer work."),
        "lockdown_on": ("Lockdown is on", "All other sessions were closed."), "lockdown_off": ("Lockdown lifted", ""),
    }

    async def handle(self, ev: dict[str, Any]) -> None:
        t, d = ev.get("type"), ev.get("data") or {}
        if t == "mod_pending" and not d.get("merged"):
            await self.emit("moderation.approval", "Approval needed", f"{d.get('author', 'Someone')}: {d.get('action', 'action')}" + (f" (score {d['score']})" if d.get("score") else ""), key="pending")
        elif t == "mod_resolved" and d.get("status") == "failed":
            await self.emit("moderation.failed", "Moderation action failed", f"{d.get('action', 'Action')} for {d.get('author', 'a chatter')} did not go through.")
        elif t == "mod_expired":
            n = int(d.get("count", 1))
            await self.emit("moderation.expired", "Approval requests expired", f"{n} request{'s' if n != 1 else ''} timed out without a decision.", key="expired")
        elif t == "intel_wave" and not d.get("demo"):
            await self.emit("moderation.raid", "Raid wave detected", "Many brand-new accounts started chatting within seconds.", key="raid")
        elif t == "stream":
            if self.container is not None and self.container.hub.mode != "live":
                return
            if d.get("live"):
                await self.emit("stream.live", "Stream is live", d.get("title") or "The bot is attached to the chat.")
            else:
                await self.emit("stream.ended", "Stream ended", "The bot is waiting for the next stream.")
        elif t == "mode":
            live = d.get("mode") == "live"
            await self.emit("stream.mode", "Switched to Live" if live else "Switched to Demo", "Real YouTube chat." if live else "Simulated chat. Nothing is sent.", key="mode")
        elif t == "reminder":
            await self.emit("reminders.reminder", "Reminder", str(d.get("text", "")))
        elif t == "timer_done":
            await self.emit("reminders.timer", "Timer finished", f"\"{d.get('name', 'A timer')}\" posted its last message and switched itself off.")
        elif t == "security_audit" and d.get("action") in self.SECURITY:
            title, body = self.SECURITY[d["action"]]
            await self.emit("security.alert", title, body or d.get("detail", ""), key=d["action"])
        elif t == "backup":
            await self.emit("backup.done", str(d.get("title", "Backup")), str(d.get("text", "")))

    async def _watch_status(self, now: float) -> None:
        """Problems that show up in a service's status rather than as events."""
        c = self.container
        if c is None:
            return
        try:
            yt, tg = c.youtube.status(), c.telegram.status() if hasattr(c.telegram, "status") else {}
        except Exception:
            return
        live = c.hub.mode == "live"
        for name, text, cid, title in (("yt", yt.get("last_error") or "", "system.youtube", "YouTube problem"), ("yta", yt.get("last_action_error") or "", "moderation.failed", "YouTube refused an action"),
                                       ("tg", tg.get("last_error") or "", "system.telegram", "Telegram problem")):
            if text and text != self._seen_errors.get(name) and (live or name == "tg"):
                await self.emit(cid, title, text, key=name, now=now)
            self._seen_errors[name] = text
        q = yt.get("quota") or {}
        if q and live:
            day, frac = q.get("day", ""), float(q.get("fraction", 0))
            lvl = 90 if frac >= 0.9 else 75 if frac >= 0.75 else 0
            if day != self._quota_day:
                self._quota_day, self._quota_level = day, lvl
            elif lvl > self._quota_level:
                self._quota_level = lvl
                await self.emit("system.quota", f"YouTube quota at {lvl}%", f"{q.get('used')} of {q.get('daily')} units used today.", key=str(lvl), priority="high" if lvl >= 90 else None, now=now)

    # ------------------------------------------------------------------ inbox
    async def inbox(self, *, limit: int = 50, before: float | None = None, unread: bool = False, category: str = "", since: float | None = None, until: float | None = None, nid: int | None = None) -> dict[str, Any]:
        where, args = ["1=1"], []
        if nid:
            where.append("id = ?"); args.append(nid)
        if before:
            where.append("ts < ?"); args.append(before)
        if unread:
            where.append("read_ts IS NULL")
        if category:
            where.append("(category = ? OR category LIKE ?)"); args += [category, category + ".%"]
        if since is not None:
            where.append("ts >= ?"); args.append(since)
        if until is not None:
            where.append("ts < ?"); args.append(until)
        limit = max(1, min(int(limit), 200))
        rows = await self.db.fetchall(f"SELECT id, ts, category, title, body, route, priority, kind, icon, count, read_ts FROM notifications WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT ?", (*args, limit + 1))
        more = len(rows) > limit
        unread_n = (await self.db.fetchone("SELECT COUNT(*) AS n FROM notifications WHERE read_ts IS NULL"))["n"]
        return {"items": [self._row(r) for r in rows[:limit]], "more": more, "unread": unread_n}

    @staticmethod
    def _row(r: dict[str, Any]) -> dict[str, Any]:
        c = cats.REGISTRY.get(r["category"])
        return {"id": r["id"], "ts": r["ts"], "category": r["category"], "group": c.group if c else "", "label": c.label if c else r["category"], "title": r["title"], "body": r["body"],
                "route": safe_route(r["route"]), "priority": r["priority"], "kind": r["kind"], "icon": r["icon"], "count": r["count"], "read": r["read_ts"] is not None}

    async def mark_read(self, ids: list[int] | None, now: float) -> int:
        if ids is None:
            return await self.db.execute("UPDATE notifications SET read_ts = ? WHERE read_ts IS NULL", (now,))
        n = 0
        for i in ids[:200]:
            n += await self.db.execute("UPDATE notifications SET read_ts = ? WHERE id = ? AND read_ts IS NULL", (now, int(i)))
        return n

    async def delete(self, ids: list[int] | None) -> int:
        if ids is None:
            return await self.db.execute("DELETE FROM notifications")
        n = 0
        for i in ids[:200]:
            n += await self.db.execute("DELETE FROM notifications WHERE id = ?", (int(i),))
        return n

    # ------------------------------------------------------------------ devices
    @staticmethod
    def _describe(ua: str) -> tuple[str, str]:
        u = ua.lower()
        plat = "iOS" if "iphone" in u or "ipad" in u else "Android" if "android" in u else "Windows" if "windows" in u else "macOS" if "mac os" in u else "Linux" if "linux" in u else "Unknown"
        br = "Edge" if "edg/" in u else "Opera" if "opr/" in u else "Firefox" if "firefox" in u else "Chrome" if "chrome" in u or "crios" in u else "Safari" if "safari" in u else "Browser"
        return plat, br

    async def register_device(self, token: str, ua: str, installed: bool, now: float, label: str = "") -> dict[str, Any]:
        token = token.strip()
        if not 20 <= len(token) <= 4096 or not re.fullmatch(r"[A-Za-z0-9_:\-\.]+", token):
            raise NotifyError("That does not look like a push token.")
        plat, br = self._describe(ua)
        h = self.thash(token)
        row = await self.db.fetchone("SELECT id FROM notify_devices WHERE token_hash = ?", (h,))
        if row:
            await self.db.execute("UPDATE notify_devices SET last_seen = ?, installed = ?, platform = ?, browser = ?, token_enc = ? WHERE id = ?", (now, int(installed), plat, br, self.seal(token), row["id"]))
            return {"id": row["id"], "new": False}
        label = (label or f"{br} on {plat}")[:60]
        did = await self.db.insert("INSERT INTO notify_devices (token_hash, token_enc, label, platform, browser, installed, created, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (h, self.seal(token), label, plat, br, int(installed), now, now))
        return {"id": did, "new": True}

    async def devices(self) -> list[dict[str, Any]]:
        rows = await self.db.fetchall("SELECT id, label, platform, browser, installed, created, last_seen, last_ok, last_error, fail_count, enabled FROM notify_devices ORDER BY last_seen DESC")
        return [{**r, "installed": bool(r["installed"]), "enabled": bool(r["enabled"])} for r in rows]       # token_enc and token_hash never leave the server

    async def forget_device(self, device_id: int) -> bool:
        await self.db.execute("UPDATE notify_deliveries SET status = 'cancelled' WHERE device_id = ? AND status IN ('queued', 'held')", (device_id,))
        return bool(await self.db.execute("DELETE FROM notify_devices WHERE id = ?", (device_id,)))

    async def rename_device(self, device_id: int, label: str) -> bool:
        return bool(await self.db.execute("UPDATE notify_devices SET label = ? WHERE id = ?", (label.strip()[:60] or "Device", device_id)))

    async def set_device_enabled(self, device_id: int, on: bool) -> bool:
        return bool(await self.db.execute("UPDATE notify_devices SET enabled = ? WHERE id = ?", (int(on), device_id)))

    async def unregister_token(self, token: str) -> bool:
        return bool(await self.db.execute("DELETE FROM notify_devices WHERE token_hash = ?", (self.thash(token.strip()),)))

    # ------------------------------------------------------------------ stats
    async def stats(self, now: float, days: int = 7) -> dict[str, Any]:
        days = max(1, min(int(days), 90))
        since = now - days * 86400
        by_cat = await self.db.fetchall("SELECT category, COUNT(*) AS n, SUM(CASE WHEN read_ts IS NULL THEN 0 ELSE 1 END) AS read FROM notifications WHERE ts >= ? GROUP BY category ORDER BY n DESC", (since,))
        dl = await self.db.fetchall("SELECT status, COUNT(*) AS n FROM notify_deliveries WHERE created >= ? GROUP BY status", (since,))
        per_day: dict[str, int] = {}
        try:
            tz = ZoneInfo(self.cfg.get("owner_timezone") or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo("UTC")
        for r in await self.db.fetchall("SELECT ts FROM notifications WHERE ts >= ?", (since,)):
            k = datetime.fromtimestamp(r["ts"], tz).strftime("%Y-%m-%d")
            per_day[k] = per_day.get(k, 0) + 1
        today = datetime.fromtimestamp(now, tz).date()
        series = [{"day": (today - timedelta(days=i)).isoformat(), "count": per_day.get((today - timedelta(days=i)).isoformat(), 0)} for i in range(days - 1, -1, -1)]
        status = {r["status"]: r["n"] for r in dl}
        sent, failed = status.get("sent", 0), status.get("failed", 0) + status.get("dead", 0)
        return {"days": days, "total": sum(r["n"] for r in by_cat), "by_category": [{"category": r["category"], "label": cats.REGISTRY[r["category"]].label if r["category"] in cats.REGISTRY else r["category"], "count": r["n"], "read": r["read"] or 0} for r in by_cat],
                "per_day": series, "deliveries": status, "success_rate": round(sent / (sent + failed), 3) if sent + failed else None}

    async def delivery_log(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self.db.fetchall("""SELECT d.id, d.created, d.status, d.attempts, d.error, d.category, d.priority, d.done_ts, v.label AS device, n.title
                                         FROM notify_deliveries d LEFT JOIN notify_devices v ON v.id = d.device_id LEFT JOIN notifications n ON n.id = d.notification_id
                                         ORDER BY d.created DESC LIMIT ?""", (max(1, min(limit, 200)),))
        return rows

    async def unread(self) -> int:
        return (await self.db.fetchone("SELECT COUNT(*) AS n FROM notifications WHERE read_ts IS NULL"))["n"]

    # ------------------------------------------------------------------ test and pause
    async def send_test(self, now: float, device_id: int | None = None) -> dict[str, Any]:
        """Sends a test straight to the device(s), skipping quiet hours and pause, and says exactly what happened."""
        if not self.fcm.configured:
            return {"ok": False, "results": [], "problems": self.fcm.problems()}
        q = "SELECT * FROM notify_devices WHERE enabled = 1" + (" AND id = ?" if device_id else "")
        devs = await self.db.fetchall(q, (device_id,) if device_id else ())
        if not devs:
            return {"ok": False, "results": [], "problems": ["No device is registered yet. Turn on push on this device first."]}
        title, body = "SavahBot test", "If you can read this, push notifications work on this device."
        nid = await self.db.insert("INSERT INTO notifications (ts, category, title, body, route, priority, kind, icon, dedupe_key) VALUES (?, 'test.test', ?, ?, '#/notifications', 'normal', 'info', 'bell', '')", (now, title, body))
        await self.db.execute("UPDATE notifications SET route = ? WHERE id = ?", (f"#/notifications?open={nid}", nid))
        self.bus.publish("notify", {"id": nid, "category": "test.test", "title": title, "body": body, "route": f"#/notifications?open={nid}", "kind": "info", "icon": "bell", "priority": "normal", "folded": False})
        results = []
        for d in devs:
            idem = f"test:{nid}:{d['id']}"
            did = await self.db.insert("INSERT INTO notify_deliveries (notification_id, channel, device_id, status, next_try, created, idem, category, priority) VALUES (?, 'push', ?, 'queued', ?, ?, ?, 'test.test', 'normal')", (nid, d["id"], now, now, idem))
            row = await self.db.fetchone("SELECT * FROM notify_deliveries WHERE id = ?", (did,))
            await self._send_one(row, now)
            after = await self.db.fetchone("SELECT status, error FROM notify_deliveries WHERE id = ?", (did,)) or {"status": "dead", "error": "device token was rejected and removed"}
            results.append({"device": d["label"], "status": after["status"], "error": after["error"]})
        return {"ok": all(r["status"] == "sent" for r in results), "results": results, "problems": []}

    async def pause(self, minutes: int | None, now: float) -> float:
        until = 0.0 if not minutes else now + max(1, min(int(minutes), 7 * 1440)) * 60
        await self.set_prefs({"pause_until": until})
        return until
