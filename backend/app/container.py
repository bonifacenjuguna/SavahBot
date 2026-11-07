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
        self.scheduler = Scheduler(self.cfg, self.store, self.hub, self.bus)
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
        try:
            await self.intel.start()
        except Exception:  # the intelligence layer must never stop the bot from booting
            logger.exception("Intelligence failed to start; continuing with the original moderation only")
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
        await self.telegram.stop()
        await self.hub.shutdown()
        await self.db.close()
