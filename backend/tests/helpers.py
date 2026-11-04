import asyncio
import random

from app.analytics import summary  # noqa: F401  (re-exported for tests)
from app.commands import CommandEngine, Renderer
from app.config import StaticConfig
from app.db import Database
from app.events import EventBus
from app.hub import Hub
from app.moderation import ModerationEngine, PermitStore
from app.seed import seed_defaults
from app.services.demo import DemoSource
from app.services.scheduler import Scheduler
from app.store import Store


class VClock:
    """Virtual time: sleep() advances the clock instantly so scenarios run in milliseconds."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    async def sleep(self, d: float) -> None:
        self.t += d
        await asyncio.sleep(0)


class Stack:
    pass


async def build_stack(overrides=None, seed=True, seed_value=7):
    s = Stack()
    s.db = Database(":memory:")
    await s.db.connect()
    s.store = Store(s.db)
    s.cfg = StaticConfig({"demo_autostart": False, **(overrides or {})})
    s.bus = EventBus()
    s.permits = PermitStore()
    s.engine = ModerationEngine(s.cfg, s.permits)
    s.renderer = Renderer(s.cfg, s.store, uptime_fn=lambda: s.hub.uptime())
    s.commands = CommandEngine(s.cfg, s.store, s.renderer, s.permits, uptime_fn=lambda: s.hub.uptime(),
                               channel_fn=lambda: s.cfg.get("demo_channel_name"))
    s.hub = Hub(s.cfg, s.store, s.bus, s.engine, s.commands)
    s.clock = VClock()
    s.demo = DemoSource(s.cfg, s.hub, clock=s.clock.now, sleep=s.clock.sleep, rng=random.Random(seed_value))
    s.hub.register(s.demo)
    s.scheduler = Scheduler(s.cfg, s.store, s.hub, s.bus)
    s.notes = []

    async def notifier(text, buttons=None):
        s.notes.append((text, buttons))

    s.hub.notify = notifier
    if seed:
        await seed_defaults(s.db, s.store)
    await s.store.load_regulars()
    await s.hub.reload_blacklist()
    s.hub.cfg.set("bot_mode", "demo")
    await s.hub.apply_mode()
    return s


def events(stack):
    """Subscribe before acting; returns a function that drains collected events."""
    q = stack.bus.subscribe()

    def drain():
        out = []
        while not q.empty():
            out.append(q.get_nowait())
        return out

    return drain
