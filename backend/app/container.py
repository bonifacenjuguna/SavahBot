"""Wires every part of SavahBot together. `main.py` and the tests both build the app through here."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .commands import CommandEngine, Renderer
from .config import Settings
from .db import Database
from .events import EventBus
from .hub import Hub
from .moderation import ModerationEngine, PermitStore
from .intel import Intelligence
from .runtime_config import RuntimeConfig
from .persist import StateKeeper
from .security import OwnerAuth
from .shared import Leader, Shared
from .seed import seed_defaults
from .services.demo import DemoSource
from .services.scheduler import Scheduler
from .services.telegram import TelegramBot
from .services.youtube import GoogleAuth, QuotaTracker, YouTubeSource
from .store import Store

logger = logging.getLogger("savahbot")


class Container:
    def __init__(self, settings: Settings | None = None, db: Database | None = None) -> None:
        self.settings = settings or Settings()
        self.db = db or Database(self.settings.database_url, self.settings.db_pool_size, self.settings.db_echo)
        self.cfg = RuntimeConfig(self.settings, self.db)
        self.store = Store(self.db)
        self.bus = EventBus()
        # 1.1.8: optional Redis. With REDIS_URL empty this is all in memory and nothing changes.
        self.shared = Shared(self.settings.redis_url, self.settings.redis_prefix, float(self.settings.redis_timeout_seconds))
        self.auth = OwnerAuth(self.settings, self.db, self.shared)
        self.permits = PermitStore()
        self.engine = ModerationEngine(self.cfg, self.permits)
        self.intel = Intelligence(self.cfg, self.db)       # 1.1.6: knowledge packs and detectors
        self.engine.attach_intel(self.intel)
        self.renderer = Renderer(self.cfg, self.store, uptime_fn=lambda: self.hub.uptime())
        self.commands = CommandEngine(self.cfg, self.store, self.renderer, self.permits, uptime_fn=lambda: self.hub.uptime(),
                                      channel_fn=self._channel_name)
        self.hub = Hub(self.cfg, self.store, self.bus, self.engine, self.commands)
        self.demo = DemoSource(self.cfg, self.hub)
        self.google = GoogleAuth(self.cfg, self.db)
        self.quota = QuotaTracker(self.cfg, self.store)
        self.youtube = YouTubeSource(self)
        self.telegram = TelegramBot(self)
        self.scheduler = Scheduler(self.cfg, self.store, self.hub, self.bus, active=lambda: self.leader.is_leader)
        self.keeper = StateKeeper(self.shared, self.cfg, self.engine, self.commands, self.hub)
        self.leader = Leader(self.shared, "leader", float(self.settings.redis_leader_ttl_seconds), on_gain=self._lead, on_lose=self._follow)
        self.hub.shared = self.shared
        self.hub.active = lambda: self.leader.is_leader
        if self.shared.configured:
            self.bus.attach_shared(self.shared)
        self._wait_for_telegram = False
        self.started_at = time.time()
        self._bg: set[asyncio.Task] = set()
        self.hub.register(self.demo)
        self.hub.register(self.youtube)
        self.hub.notify = self.telegram.notify
        self.cfg.on_change(self._on_setting)

    def _channel_name(self) -> str:
        return self.cfg.get("demo_channel_name") if self.cfg.get("bot_mode") == "demo" else (self.hub.stream_title or "")

    def _on_setting(self, name: str, value: Any) -> None:
        coro = None
        if name == "bot_mode":
            coro = self.hub.apply_mode()
        elif name == "telegram_mode" and self.leader.is_leader:
            coro = self.telegram.apply_mode()
        if coro is not None:
            task = asyncio.ensure_future(coro)
            self._bg.add(task)
            task.add_done_callback(self._bg.discard)

    async def start(self, wait_for_telegram: bool = False) -> None:
        await self.db.connect()
        await self.cfg.load()
        await self.auth.init()
        await self.store.load_regulars()
        if self.cfg.get("command_seed_defaults"):
            await seed_defaults(self.db, self.store)
        try:
            await self.intel.start()
        except Exception:  # the intelligence layer must never stop the bot from booting
            logger.exception("Intelligence failed to start; continuing with the original moderation only")
        await self.hub.reload_blacklist()
        await self.quota.sync()
        self._wait_for_telegram = wait_for_telegram
        await self.shared.start()
        await self.leader.start()     # without Redis this instance is the leader at once and _lead() runs right here
        logger.info("SavahBot started in %s mode (database: %s, redis: %s, %s)", self.cfg.get("bot_mode"), self.db.backend, self.shared.mode,
                    "leader" if self.leader.is_leader else "standby")

    async def _lead(self) -> None:
        """This instance became the leader: bring back the saved memory, then start chat, timers and Telegram."""
        await self.cfg.load()          # a new leader starts from the latest saved settings
        await self.keeper.restore()
        await self.hub.apply_mode()
        await self.scheduler.start()
        await self.keeper.start()
        if self._wait_for_telegram:
            await self.telegram.start()
        else:  # never delay boot on Telegram
            task = asyncio.ensure_future(self.telegram.start())
            self._bg.add(task)
            task.add_done_callback(self._bg.discard)

    async def _follow(self) -> None:
        """Another instance took over: stop everything only the leader may do."""
        await self.keeper.stop(final_save=False)
        await self.scheduler.stop()
        await self.telegram.stop()
        await self.hub.shutdown()

    async def stop(self) -> None:
        for t in list(self._bg):
            t.cancel()
        await self.keeper.stop(final_save=self.leader.is_leader)   # last save before the process exits
        await self.leader.stop()
        await self.scheduler.stop()
        await self.telegram.stop()
        await self.hub.shutdown()
        await self.shared.stop()
        await self.db.close()
