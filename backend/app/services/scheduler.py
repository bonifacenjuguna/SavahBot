"""Background ticker: chat timers, reminders, expiring stale approvals and trimming old data."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..commands import Ctx
from ..timeparse import next_repeat
from ..utils import from_epoch, to_epoch

logger = logging.getLogger("savahbot.scheduler")


class Scheduler:
    def __init__(self, cfg: Any, store: Any, hub: Any, bus: Any) -> None:
        self.cfg = cfg
        self.store = store
        self.hub = hub
        self.bus = bus
        self._task: asyncio.Task | None = None
        self._started = time.time()
        self._lines_at: dict[int, int] = {}
        self._retry_at: dict[int, float] = {}
        self._last_housekeeping = 0.0
        self._last_expiry = 0.0

    async def start(self) -> None:
        if self._task is None:
            self._started = time.time()
            self._task = asyncio.ensure_future(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduler tick failed")
            await asyncio.sleep(max(1, self.cfg.get("scheduler_tick_seconds")))

    async def tick(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        if self.cfg.get("reminders_enabled"):
            await self._reminders(now)
        if self.cfg.get("timers_enabled"):
            await self._timers(now)
        if now - self._last_expiry >= 30:
            self._last_expiry = now
            n = await self.store.expire_pending(now - self.cfg.get("mod_pending_ttl_minutes") * 60)
            if n:
                self.bus.publish("mod_expired", {"count": n})
        if now - self._last_housekeeping >= 3600:
            self._last_housekeeping = now
            await self.store.purge(now - self.cfg.get("chat_retention_days") * 86400,
                                   now - self.cfg.get("action_retention_days") * 86400)

    async def _reminders(self, now: float) -> None:
        for r in await self.store.due_reminders(now):
            if r["repeat_kind"] != "none":
                nxt = next_repeat(from_epoch(r["due"]), r["repeat_kind"], r["interval_seconds"], from_epoch(now))
                await self.store.reschedule_reminder(r["id"], to_epoch(nxt), now)
            else:
                await self.store.finish_reminder(r["id"], now)
            self.bus.publish("reminder", {"id": r["id"], "text": r["body"]})
            await self.hub.notice("reminder", f"Reminder: {r['body']}")
            if self.cfg.get("telegram_notify_reminders"):
                await self.hub._notify(f"Reminder: {r['body']}")

    # ------------------------------------------------------------------ timers
    # Trigger semantics (one place, so the UI text and the behaviour cannot drift apart):
    #   recurring, time only      -> posts every N seconds
    #   recurring, lines only     -> posts after N new chat lines
    #   recurring, both, "all"    -> posts when BOTH are met (default, the behaviour before 1.1.1)
    #   recurring, both, "any"    -> posts when EITHER is met
    #   after any post, both the clock and the line counter restart
    #   no recurring timer posts more than once per MIN_GAP seconds, so a busy chat cannot make a lines-only timer spam
    #   once                      -> posts one time (at run_at if set), then switches itself off
    MIN_GAP = 60

    @staticmethod
    def timer_due(t: dict, now: float, last: float, lines_since: int) -> bool:
        if t["kind"] == "once":
            return not t.get("done") and (t.get("run_at") is None or now >= t["run_at"])
        if now - last < Scheduler.MIN_GAP:
            return False
        checks = []
        if t["interval_seconds"] > 0:
            checks.append(now - last >= t["interval_seconds"])
        if t["min_lines"] > 0:
            checks.append(lines_since >= t["min_lines"])
        if not checks:
            return False
        return any(checks) if t.get("trigger_mode") == "any" else all(checks)

    def progress(self, t: dict, now: float | None = None) -> dict[str, Any]:
        """What the dashboard shows for a timer: state, chat lines still needed, next time-based post."""
        now = now if now is not None else time.time()
        live = bool(self.hub.stream_live and self.hub.source is not None)
        out: dict[str, Any] = {"state": "off", "lines_since": 0, "lines_needed": 0, "next_run_at": None}
        if t.get("done"):
            out["state"] = "done"
            return out
        if not t["enabled"]:
            return out
        out["state"] = "waiting" if live else "paused"      # paused = armed, but nothing is posted until a stream is live
        last = max(t["last_fired"], self._started)
        if t["kind"] == "once":
            out["next_run_at"] = t.get("run_at")
            return out
        since = max(0, self.hub.lines - self._lines_at.get(t["id"], self.hub.lines))
        out["lines_since"] = since
        out["lines_needed"] = max(0, t["min_lines"] - since) if t["min_lines"] else 0
        if t["interval_seconds"]:
            out["next_run_at"] = last + max(t["interval_seconds"], 0)
        return out

    async def _timers(self, now: float) -> None:
        if not self.hub.stream_live or self.hub.source is None:
            return
        demo = self.hub.is_demo
        for t in await self.store.list_timers():
            if not t["enabled"] or t["done"]:
                continue
            if t["id"] not in self._lines_at or self.hub.lines < self._lines_at[t["id"]]:
                self._lines_at[t["id"]] = self.hub.lines          # first sight, or the session counter was reset by a mode switch
            last = max(t["last_fired"], self._started)
            if now < self._retry_at.get(t["id"], 0):
                continue
            if not self.timer_due(t, now, last, self.hub.lines - self._lines_at[t["id"]]):
                continue
            text = await self.hub.commands.renderer.render(t["message"], Ctx(channel=self.hub.commands.channel_fn(), now=now))
            if text and await self.hub.send_chat(text):
                await self.store.mark_timer_fired(t["id"], now, demo)
                self._lines_at[t["id"]] = self.hub.lines
                self._retry_at.pop(t["id"], None)
                if t["kind"] == "once":
                    await self.store.finish_once_timer(t["id"])
                    await self.hub.notice("timer", f"One-time message sent: {t['name']}")
                self.bus.publish("timer", {"id": t["id"], "name": t["name"], "ok": True})
            else:
                error = "The message came out empty." if not text else "The chat refused or could not receive the message."
                await self.store.mark_timer_failed(t["id"], now, error, demo)
                self._retry_at[t["id"]] = now + self.MIN_GAP * 5     # do not hammer a chat that is refusing posts
                await self.hub.notice("timer", f"Timer {t['name']} could not post", error, level="warning")
                self.bus.publish("timer", {"id": t["id"], "name": t["name"], "ok": False})
