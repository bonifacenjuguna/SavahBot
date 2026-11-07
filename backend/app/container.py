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
from .intel import Intel
from .intel.feeds import FeedManager
from .intel.learning import Learning
from .intel.service import Knowledge
from .moderation import ModerationEngine, PermitStore
from .runtime_config import RuntimeConfig
from .security import OwnerAuth
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
        self.auth = OwnerAuth(self.settings, self.db)
        self.permits = PermitStore()
        self.engine = ModerationEngine(self.cfg, self.permits)
        self.renderer = Renderer(self.cfg, self.store, uptime_fn=lambda: self.hub.uptime())
        self.commands = CommandEngine(self.cfg, self.store, self.renderer, self.permits, uptime_fn=lambda: self.hub.uptime(),
                                      channel_fn=self._channel_name)
        self.hub = Hub(self.cfg, self.store, self.bus, self.engine, self.commands)
        self.demo = DemoSource(self.cfg, self.hub)
        self.google = GoogleAuth(self.cfg, self.db)
        self.quota = QuotaTracker(self.cfg, self.store)
        self.youtube = YouTubeSource(self)
        self.telegram = TelegramBot(self)
        self.scheduler = Scheduler(self.cfg, self.store, self.hub, self.bus)
        # 1.1.6 intelligence layer: knowledge packs, detectors, learning and live data. Purely additive to the engine.
        self.intel = Intel(self.cfg, names_fn=self._protected_names)
        self.engine.intel = self.intel
        self.knowledge = Knowledge(self.db, self.cfg, self.intel, self.store)
        self.learning = Learning(self.db, self.cfg, self.intel, self.knowledge)
        self.feeds = FeedManager(self.db, self.cfg, self.intel, self.knowledge)
        self.knowledge.learning, self.knowledge.feeds = self.learning, self.feeds
        self.hub.learning = self.learning
        self.scheduler.hooks.append(self.knowledge.tick)
        self.started_at = time.time()
        self._bg: set[asyncio.Task] = set()
        self.hub.register(self.demo)
        self.hub.register(self.youtube)
        self.hub.notify = self.telegram.notify
        self.cfg.on_change(self._on_setting)

    def _channel_name(self) -> str:
        return self.cfg.get("demo_channel_name") if self.cfg.get("bot_mode") == "demo" else (self.hub.stream_title or "")

    def _protected_names(self) -> list[str]:
        """Names the impersonation guard protects without being told: the demo channel while in demo mode."""
        return [self.cfg.get("demo_channel_name")] if self.cfg.get("bot_mode") == "demo" and self.cfg.get("demo_channel_name") else []

    def _on_setting(self, name: str, value: Any) -> None:
        if name in ("intel_languages", "intel_protected_domains", "mod_allowed_domains", "mod_blacklist_weight"):
            self.intel.rebuild()  # detector modes and strengths are read live; only these change what is compiled
        coro = None
        if name == "bot_mode":
            coro = self.hub.apply_mode()
        elif name == "telegram_mode":
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
        await self.knowledge.load()
        await self.feeds.load()
        await self.knowledge.load()  # again, now that the feed state is known
        await self.learning.load()
        await self.hub.reload_blacklist()
        await self.quota.sync()
        await self.hub.apply_mode()
        await self.scheduler.start()
        if wait_for_telegram:
            await self.telegram.start()
        else:  # never delay boot on Telegram
            task = asyncio.ensure_future(self.telegram.start())
            self._bg.add(task)
            task.add_done_callback(self._bg.discard)
        logger.info("SavahBot started in %s mode (database: %s)", self.cfg.get("bot_mode"), self.db.backend)

    async def stop(self) -> None:
        for t in list(self._bg):
            t.cancel()
        await self.scheduler.stop()
        try:
            await self.knowledge.flush()
            await self.learning.persist()
        except Exception:
            logger.exception("Could not save intelligence statistics on shutdown")
        await self.telegram.stop()
        await self.hub.shutdown()
        await self.db.close()
