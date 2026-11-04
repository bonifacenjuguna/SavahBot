"""Tiny in-process pub/sub that feeds the dashboard's live WebSocket."""
from __future__ import annotations

import asyncio
import time
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self, maxsize: int = 500) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def publish(self, type_: str, data: Any = None) -> None:
        """Non-blocking. Slow subscribers simply miss events instead of stalling the bot."""
        event = {"type": type_, "data": data if data is not None else {}, "ts": time.time()}
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
