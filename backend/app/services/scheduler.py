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
            if self.cfg.get("telegram_notify_reminders"):
                await self.hub._notify(f"Reminder: {r['body']}")

    async def _timers(self, now: float) -> None:
        if not self.hub.stream_live or self.hub.source is None:
            return
        for t in await self.store.list_timers():
            if not t["enabled"]:
                continue
            if t["id"] not in self._lines_at:
                self._lines_at[t["id"]] = self.hub.lines
            last = max(t["last_fired"], self._started)
            if now - last < t["interval_seconds"] or self.hub.lines - self._lines_at[t["id"]] < t["min_lines"]:
                continue
            text = await self.hub.commands.renderer.render(t["message"], Ctx(channel=self.hub.commands.channel_fn(), now=now))
            if text and await self.hub.send_chat(text):
                await self.store.mark_timer_fired(t["id"], now)
                self._lines_at[t["id"]] = self.hub.lines
