"""Background ticker: chat timers, reminders, expiring stale approvals and trimming old data."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..commands import Ctx
from ..timeparse import next_repeat
from .telegram_ui import reminder_card
from ..utils import from_epoch, to_epoch

logger = logging.getLogger("savahbot.scheduler")


class Scheduler:
    def __init__(self, cfg: Any, store: Any, hub: Any, bus: Any, active: Any = None) -> None:
        self.rollups: Any = None      # history.Rollups, set by the container
        self.hooks: list[Any] = []   # extra async callables(now), e.g. the Knowledge refresh; a failing hook never stops the others
        self.active = active          # 1.1.8: returns False on a standby instance, so only the leader fires timers and reminders
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

    last_tick = 0.0

    async def tick(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        if self.active is not None and not self.active():
            return
        self.last_tick = now
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
            chat_cut, act_cut = now - self.cfg.get("chat_retention_days") * 86400, now - self.cfg.get("action_retention_days") * 86400
            if self.rollups is not None:   # sum finished days into the long-term tables first, and never delete past what was summed
                await self.rollups.run(now)
                chat_cut, act_cut = self.rollups.safe_cutoff(chat_cut), self.rollups.safe_cutoff(act_cut)
            await self.store.purge(chat_cut, act_cut)
        for hook in self.hooks:
            try:
                await hook(now)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduler hook failed")

    async def _reminders(self, now: float) -> None:
        for r in await self.store.due_reminders(now):
            if r["repeat_kind"] != "none":
                nxt = next_repeat(from_epoch(r["due"]), r["repeat_kind"], r["interval_seconds"], from_epoch(now))
                await self.store.reschedule_reminder(r["id"], to_epoch(nxt), now)
            else:
                await self.store.finish_reminder(r["id"], now)
            self.bus.publish("reminder", {"id": r["id"], "text": r["body"]})
            if self.cfg.get("telegram_notify_reminders"):
                await self.hub._notify(reminder_card(r["body"]))

    @staticmethod
    def timer_due(t: dict, now: float, started: float, lines_since: int) -> bool:
        """A timer waits for a time, for a number of chat lines, or both.

        With both, match_mode decides: 'all' needs both to be satisfied, 'any' fires on whichever comes first.
        """
        by_time = t["interval_seconds"] > 0
        by_lines = t["min_lines"] > 0
        time_ok = by_time and now - max(t["last_fired"], started) >= t["interval_seconds"]
        lines_ok = by_lines and lines_since >= t["min_lines"]
        if by_time and by_lines:
            return (time_ok or lines_ok) if t.get("match_mode") == "any" else (time_ok and lines_ok)
        return time_ok if by_time else lines_ok

    async def _timers(self, now: float) -> None:
        if not self.hub.stream_live or self.hub.source is None:
            return
        for t in await self.store.list_timers():
            if not t["enabled"]:
                self._lines_at.pop(t["id"], None)  # start counting chat lines afresh when it is switched on again
                continue
            if t["id"] not in self._lines_at or self.hub.lines < self._lines_at[t["id"]]:
                self._lines_at[t["id"]] = self.hub.lines  # first look, or the line counter was reset (mode change)
            if not self.timer_due(t, now, self._started, self.hub.lines - self._lines_at[t["id"]]):
                continue
            text = await self.hub.commands.renderer.render(t["message"], Ctx(channel=self.hub.commands.channel_fn(), now=now))
            if text and await self.hub.send_chat(text):
                await self.store.mark_timer_fired(t["id"], now)
                self._lines_at[t["id"]] = self.hub.lines
                if t.get("max_runs") and t.get("runs", 0) + 1 >= t["max_runs"]:
                    await self.store.switch_off_timer(t["id"])  # reached its number of posts (1 = post once)
                    self.bus.publish("timer_done", {"id": t["id"], "name": t["name"]})
