"""Saves the bot's short-term memory to Redis and puts it back after a restart (1.1.8).

What is saved: who has been posting how fast, repeated and near-identical messages, repeat-offender strikes, how regular a
chatter's timing is, command and auto-reply cooldowns, and "just punished" markers. All of it is time-based, so a restart used
to wipe it and every chatter looked brand new. Only the leader writes; whichever instance becomes leader reads it first.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .shared import Shared

logger = logging.getLogger("savahbot.persist")
STATE_KEY = "state"


class StateKeeper:
    def __init__(self, shared: Shared, cfg: Any, engine: Any, commands: Any, hub: Any) -> None:
        self.shared = shared
        self.cfg = cfg
        self.engine = engine
        self.commands = commands
        self.hub = hub
        self._task: asyncio.Task | None = None
        self.last_saved = 0.0
        self.last_bytes = 0
        self.last_restored = 0.0

    @property
    def enabled(self) -> bool:
        return self.shared.configured and self.cfg.get("redis_snapshot_seconds") > 0

    def collect(self, now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.time()
        return {"v": 1, "ts": now, "engine": self.engine.export_state(now), "commands": self.commands.export_state(now), "hub": self.hub.export_state(now)}

    def apply(self, data: dict[str, Any]) -> None:
        self.engine.import_state(data.get("engine") or {})
        self.commands.import_state(data.get("commands") or {})
        self.hub.import_state(data.get("hub") or {})

    async def save(self) -> int:
        if not self.enabled:
            return 0
        self.last_bytes = await self.shared.set_blob(STATE_KEY, self.collect(), ex=6 * 3600)
        self.last_saved = time.time()
        return self.last_bytes

    async def restore(self) -> bool:
        if not self.enabled:
            return False
        data = await self.shared.get_blob(STATE_KEY)
        if not isinstance(data, dict) or data.get("v") != 1 or time.time() - float(data.get("ts", 0)) > 6 * 3600:
            return False
        try:
            self.apply(data)
        except Exception:    # a damaged snapshot must never stop the bot from starting
            logger.exception("Could not restore the saved moderation memory; starting fresh")
            return False
        self.last_restored = time.time()
        logger.info("Restored moderation memory from Redis (saved %ds ago).", int(time.time() - float(data["ts"])))
        return True

    async def start(self) -> None:
        if self.enabled and (self._task is None or self._task.done()):
            self._task = asyncio.ensure_future(self._loop())

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(max(2, self.cfg.get("redis_snapshot_seconds")))
            try:
                await self.save()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Saving the moderation memory failed")

    async def stop(self, final_save: bool = True) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if final_save:
            try:
                await self.save()
            except Exception:
                logger.exception("Final save of the moderation memory failed")

    def status(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "last_saved": self.last_saved or None, "bytes": self.last_bytes, "last_restored": self.last_restored or None}
