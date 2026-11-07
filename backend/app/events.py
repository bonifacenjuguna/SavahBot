"""Tiny in-process pub/sub that feeds the dashboard's live WebSocket."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._shared: Any = None

    def attach_shared(self, shared: Any, channel: str = "events") -> None:
        """1.1.8: with Redis on, every instance's events reach every instance's dashboards."""
        self._shared, self._channel = shared, channel
        shared.subscribe(channel, self._from_other_instance)

    def _from_other_instance(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if msg.get("origin") != self._shared.instance_id and isinstance(msg.get("event"), dict):
            self._deliver(msg["event"])

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
        self._deliver(event)
        if self._shared is not None and self._shared.active:
            try:
                payload = json.dumps({"origin": self._shared.instance_id, "event": event}, default=str)
                asyncio.get_running_loop().create_task(self._shared.publish(self._channel, payload))
            except (RuntimeError, TypeError, ValueError):
                pass   # no running loop (a sync test) or data that cannot be sent: local delivery already happened

    def _deliver(self, event: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
