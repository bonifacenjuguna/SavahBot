"""Aho-Corasick multi-pattern string search (standard library only).

Finds every banned phrase in a message in a single pass, in time proportional to the message
length plus the number of matches, no matter how many phrases are on the list.
"""
from __future__ import annotations

from collections import deque
from typing import Any


class AhoCorasick:
    def __init__(self) -> None:
        self._next: list[dict[str, int]] = [{}]
        self._fail: list[int] = [0]
        self._out: list[list[tuple[str, Any]]] = [[]]
        self._built = False
        self.pattern_count = 0

    def add(self, pattern: str, payload: Any = None) -> None:
        if not pattern:
            return
        node = 0
        for ch in pattern:
            nxt = self._next[node].get(ch)
            if nxt is None:
                self._next.append({})
                self._fail.append(0)
                self._out.append([])
                nxt = len(self._next) - 1
                self._next[node][ch] = nxt
            node = nxt
        self._out[node].append((pattern, payload))
        self.pattern_count += 1
        self._built = False

    def build(self) -> "AhoCorasick":
        queue: deque[int] = deque()
        for child in self._next[0].values():
            self._fail[child] = 0
            queue.append(child)
        while queue:
            node = queue.popleft()
            for ch, child in self._next[node].items():
                queue.append(child)
                f = self._fail[node]
                while f and ch not in self._next[f]:
                    f = self._fail[f]
                self._fail[child] = self._next[f].get(ch, 0)
                self._out[child] = self._out[child] + self._out[self._fail[child]]
        self._built = True
        return self

    def search(self, text: str) -> list[tuple[int, str, Any]]:
        """Return (end_index_exclusive, pattern, payload) for every occurrence."""
        if not self._built:
            self.build()
        node = 0
        found: list[tuple[int, str, Any]] = []
        for i, ch in enumerate(text):
            while node and ch not in self._next[node]:
                node = self._fail[node]
            node = self._next[node].get(ch, 0)
            for pattern, payload in self._out[node]:
                found.append((i + 1, pattern, payload))
        return found
