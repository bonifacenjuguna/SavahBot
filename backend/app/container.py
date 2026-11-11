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
from .history import Rollups
from .hub import Hub
from .moderation import ModerationEngine, PermitStore
from .intel import Intel
from .intel.feeds import FeedManager
from .intel.learning import Learning
from .intel.service import Knowledge
from .runtime_config import RuntimeConfig
from .persist import StateKeeper
from .access.service import AccessService
from .backup.service import BackupService
from .notify import Notifier
from .weather import WeatherService
from .shared import Leader, Shared
from .seed import seed_defaults
from .services.demo import DemoSource
from .services.scheduler import Scheduler
from .services.telegram import TelegramBot
from .services.youtube import GoogleAuth, QuotaTracker, YouTubeSource
from .store import Store
from .variables import CustomVars
from .activity import ActivityLog
from .voices import VoiceStore
from .services.live_extras import LiveExtras

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
        self.auth = self.access = AccessService(self.settings, self.db, self.shared, self.cfg, self.bus)
        self.permits = PermitStore()
        self.engine = ModerationEngine(self.cfg, self.permits)
        # Knowledge: packs, detectors, learning and live data. Purely additive to the moderation engine.
        self.intel = Intel(self.cfg, names_fn=self._protected_names)
        self.engine.attach_intel(self.intel)
        self.knowledge = Knowledge(self.db, self.cfg, self.intel, self.store)
        self.learning = Learning(self.db, self.cfg, self.intel, self.knowledge)
        self.feeds = FeedManager(self.db, self.cfg, self.intel, self.knowledge)
        self.knowledge.learning, self.knowledge.feeds = self.learning, self.feeds
        self.renderer = Renderer(self.cfg, self.store, uptime_fn=lambda: self.hub.uptime())
        self.variables = CustomVars(self.db)
        self.activity = ActivityLog(self.db, self.cfg)
        self.cfg.activity = self.activity
        self.activity.attach(self.bus)
        self.renderer.custom = self.variables
        self.commands = CommandEngine(self.cfg, self.store, self.renderer, self.permits, uptime_fn=lambda: self.hub.uptime(),
                                      channel_fn=self._channel_name)
        self.hub = Hub(self.cfg, self.store, self.bus, self.engine, self.commands)
        self.hub.learning = self.learning
        self.demo = DemoSource(self.cfg, self.hub)
        self.google = GoogleAuth(self.cfg, self.db)
        self.quota = QuotaTracker(self.cfg, self.store)
        self.youtube = YouTubeSource(self)
        self.telegram = TelegramBot(self)
        self.scheduler = Scheduler(self.cfg, self.store, self.hub, self.bus, active=lambda: self.leader.is_leader)
        self.access.alert = self.hub._notify        # security alerts reach you on Telegram
        self.backup = BackupService(self)
        self.notifier = Notifier(self.db, self.cfg, self.settings, self.bus, secret_fn=lambda: getattr(self.access, "_secret", "") or "savahbot", telegram=self.hub._notify)
        self.notifier.container = self
        self.notifier.active = lambda: self.leader.is_leader
        self.weather = WeatherService(self.db, self.cfg, self.shared, self.notifier)
        self.rollups = Rollups(self.db)
        self.scheduler.rollups = self.rollups
        self.scheduler.hooks.append(self.hub.second_chance)
        self.scheduler.hooks.append(self.access.purge)    # lifts old automatic bans if you set a second-chance time
        self.scheduler.hooks.append(self.weather.tick)       # refresh + alert rules; the scheduler only calls hooks on the leader
        self.scheduler.hooks.append(self.notifier.tick)
        self.activity.notify = self.notifier
        self.notifier.activity = self.activity
        self.extras = LiveExtras(self)
        self.voices = VoiceStore(self.cfg.get("voice_dir"), int(self.cfg.get("voice_pack_max_mb")))
        self.renderer.live = self.extras
        self.access.activity = self.activity
        self.scheduler.hooks.append(self.extras.tick)
        self.scheduler.hooks.append(self.activity.purge)
        self.scheduler.hooks.append(self.knowledge.tick)        # live data refresh, learning review; runs on the leader only
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

    def _protected_names(self) -> list[str]:
        """Names the impersonation guard protects without being told: the demo channel while in demo mode."""
        return [self.cfg.get("demo_channel_name")] if self.cfg.get("bot_mode") == "demo" and self.cfg.get("demo_channel_name") else []

    def _on_setting(self, name: str, value: Any) -> None:
        if name in ("intel_languages", "intel_protected_domains", "mod_allowed_domains", "mod_blacklist_weight"):
            self.intel.rebuild()  # detector modes and strengths are read live; only these change what is compiled
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
            await self.knowledge.load()
            await self.feeds.load()
            await self.knowledge.load()  # again, now that the feed state is known
            await self.learning.load()
        except Exception:  # Knowledge must never stop the bot from booting
            logger.exception("Knowledge failed to start; continuing with the original moderation only")
        try:
            await self.rollups.load()
            await self.rollups.run(time.time())      # backfill: sum up every finished day before anything can be pruned
        except Exception:
            logger.exception("History roll-up failed; charts will use the raw rows")
        await self.backup.ensure_restore_token()
        self.notifier.start()
        try:
            await self.weather.load()
        except Exception:
            logger.exception("Weather failed to start; the rest of the bot is unaffected")
        try:
            await self.hub.sessions.close_orphans()      # a stream session left open by a crash is closed at its last chat line
        except Exception:
            logger.exception("Could not tidy stream sessions")
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
        try:
            await self.knowledge.flush()
            await self.learning.persist()
        except Exception:
            logger.exception("Could not save Knowledge statistics on shutdown")
        await self.notifier.stop()
        await self.leader.stop()
        await self.scheduler.stop()
        await self.telegram.stop()
        await self.hub.shutdown()
        await self.shared.stop()
        await self.db.close()
