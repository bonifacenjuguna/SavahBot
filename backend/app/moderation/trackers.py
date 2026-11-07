"""Stateful behaviour trackers (standard library only).

All of them take an explicit `now` so they are deterministic and easy to test.
"""
from __future__ import annotations

import hashlib
import statistics
from collections import deque
from dataclasses import dataclass

from .normalize import canon


class SlidingWindowCounter:
    """Sliding-window log: exact count of events per key within the last `window` seconds."""

    def __init__(self, max_keys: int = 20000) -> None:
        self._events: dict[str, deque[float]] = {}
        self.max_keys = max_keys

    def hit(self, key: str, now: float, window: float) -> int:
        dq = self._events.setdefault(key, deque())
        while dq and now - dq[0] > window:
            dq.popleft()
        dq.append(now)
        if len(self._events) > self.max_keys:
            self._gc(now, window)
        return len(dq)

    def _gc(self, now: float, window: float) -> None:
        for k in [k for k, dq in self._events.items() if not dq or now - dq[-1] > window]:
            del self._events[k]


class DuplicateTracker:
    """Counts how often the same user sent the same (canonical) text recently."""

    def __init__(self, max_keys: int = 20000) -> None:
        self._seen: dict[str, deque[tuple[float, str]]] = {}
        self.max_keys = max_keys

    def observe(self, key: str, text: str, now: float, window: float) -> int:
        h = hashlib.blake2b(canon(text).encode(), digest_size=8).hexdigest()
        dq = self._seen.setdefault(key, deque(maxlen=30))
        while dq and now - dq[0][0] > window:
            dq.popleft()
        dq.append((now, h))
        if len(self._seen) > self.max_keys:
            for k in [k for k, v in self._seen.items() if not v or now - v[-1][0] > window]:
                del self._seen[k]
        return sum(1 for _, x in dq if x == h)


def simhash(text: str, shingle: int = 3) -> int:
    """64-bit SimHash over character n-grams: similar texts give hashes with few differing bits."""
    t = canon(text)
    if not t:
        return 0
    grams = [t[i : i + shingle] for i in range(max(1, len(t) - shingle + 1))]
    vec = [0] * 64
    for g in grams:
        h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big")
        for bit in range(64):
            vec[bit] += 1 if (h >> bit) & 1 else -1
    out = 0
    for bit, v in enumerate(vec):
        if v > 0:
            out |= 1 << bit
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


class SimilarityTracker:
    """Detects copy-paste raids: how many distinct accounts posted near-identical text recently."""

    def __init__(self, maxlen: int = 1500) -> None:
        self._items: deque[tuple[float, str, int]] = deque(maxlen=maxlen)

    def observe(self, author: str, text: str, now: float, window: float, max_distance: int, min_length: int,
                record: bool = True) -> int:
        if len(canon(text)) < min_length:
            return 0
        h = simhash(text)
        while self._items and now - self._items[0][0] > window:
            self._items.popleft()
        authors = {a for _, a, hh in self._items if hamming(h, hh) <= max_distance}
        authors.add(author)
        if record:
            self._items.append((now, author, h))
        return len(authors)


@dataclass
class BehaviorInfo:
    is_new: bool
    count: int
    cv: float | None
    mean_gap: float | None
    regular_interval: bool


class BehaviorTracker:
    """Per-user timing: first sighting (new chatter) and machine-regular posting intervals."""

    def __init__(self, max_keys: int = 50000) -> None:
        self._state: dict[str, tuple[float, deque[float]]] = {}
        self.max_keys = max_keys

    def observe(self, key: str, now: float, *, new_window: float, min_messages: int, max_cv: float,
                max_mean_gap: float) -> BehaviorInfo:
        first, times = self._state.get(key) or (now, deque(maxlen=12))
        times.append(now)
        self._state[key] = (first, times)
        if len(self._state) > self.max_keys:
            for k in sorted(self._state, key=lambda k: self._state[k][1][-1])[: self.max_keys // 4]:
                del self._state[k]
        is_new = (now - first) < new_window
        cv = mean_gap = None
        regular = False
        if len(times) >= max(3, min_messages):
            ts = list(times)
            gaps = [b - a for a, b in zip(ts, ts[1:])]
            mean_gap = statistics.fmean(gaps)
            if mean_gap >= 0.5:  # faster than that is a flood; the rate limiter handles it
                cv = statistics.pstdev(gaps) / mean_gap
                regular = mean_gap <= max_mean_gap and cv <= max_cv
        return BehaviorInfo(is_new, len(times), cv, mean_gap, regular)
