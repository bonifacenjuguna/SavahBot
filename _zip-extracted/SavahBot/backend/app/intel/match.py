"""Matching engines: exact (Aho-Corasick), regex, and typo-tolerant (BK-tree over words)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

from ..moderation.ahocorasick import AhoCorasick
from .textkit import deep_normalize, flat, levenshtein


@dataclass
class Rule:
    """One compiled phrase: what it is, where it came from and how heavy it is."""
    pack: str
    signal: str
    phrase: str
    weight: int
    regex: bool = False
    fuzzy: bool = False
    needs_target: bool = False
    lang: str = "en"
    source: str = "builtin"
    mode: str = "live"          # the pack's own mode: live or shadow (off packs are never compiled)
    norm: str = ""              # normalised phrase


@dataclass
class Hit:
    rule: Rule
    kind: str                   # exact | squashed | regex | fuzzy
    matched: str = ""           # what in the message matched (for explanations)
    typos: int = 0


class PhraseIndex:
    """Every enabled phrase from every phrase pack, in one structure."""

    def __init__(self) -> None:
        self._spaced = AhoCorasick()
        self._squashed = AhoCorasick()
        self._regex: list[tuple[re.Pattern[str], Rule]] = []
        self.size = 0
        self.rules: list[Rule] = []

    def build(self, rules: Iterable[Rule]) -> "PhraseIndex":
        spaced, squashed = AhoCorasick(), AhoCorasick()
        regexes: list[tuple[re.Pattern[str], Rule]] = []
        kept: list[Rule] = []
        for r in rules:
            if r.regex:
                try:
                    regexes.append((re.compile(r.phrase, re.I), r))
                    kept.append(r)
                except re.error:
                    continue
                continue
            p = deep_normalize(r.phrase)
            if not p:
                continue
            r.norm = p
            kept.append(r)
            spaced.add(f" {p} " if len(p.replace(" ", "")) <= 4 else p, r)
            fl = flat(r.phrase)
            if len(fl) >= 8:  # spaced-out evasion ('f r e e r o b u x'); shorter phrases would cross word borders
                squashed.add(fl, r)
        spaced.build()
        squashed.build()
        self._spaced, self._squashed, self._regex, self.rules, self.size = spaced, squashed, regexes, kept, len(kept)
        return self

    def scan(self, text: str, folded: str | None = None) -> list[Hit]:
        if not self.size:
            return []
        norm = deep_normalize(text)
        padded = f" {norm} "
        hits: dict[int, Hit] = {}
        for _, pat, r in self._spaced.search(padded):
            hits.setdefault(id(r), Hit(r, "exact", pat.strip()))
        for _, pat, r in self._squashed.search(re.sub(r"(.)\1+", r"\1", padded.replace(" ", ""))):
            hits.setdefault(id(r), Hit(r, "squashed", pat))
        sample = (folded if folded is not None else text)[:500]
        for rx, r in self._regex:
            m = rx.search(sample)
            if m:
                hits.setdefault(id(r), Hit(r, "regex", m.group(0)[:60]))
        return list(hits.values())


# ---------------------------------------------------------------------------- typo tolerance
class BKTree:
    """Metric tree for 'which known words are within N edits of this word?' without comparing against all of them."""

    def __init__(self) -> None:
        self._root: tuple[str, dict[int, Any]] | None = None
        self.size = 0

    def add(self, word: str) -> None:
        if self._root is None:
            self._root = (word, {})
            self.size = 1
            return
        node = self._root
        while True:
            d = levenshtein(word, node[0])
            if d == 0:
                return
            child = node[1].get(d)
            if child is None:
                node[1][d] = (word, {})
                self.size += 1
                return
            node = child

    def query(self, word: str, max_dist: int) -> list[tuple[str, int]]:
        if self._root is None:
            return []
        out: list[tuple[str, int]] = []
        stack = [self._root]
        while stack:
            w, children = stack.pop()
            d = levenshtein(word, w)
            if d <= max_dist:
                out.append((w, d))
            for dist, child in children.items():
                if d - max_dist <= dist <= d + max_dist:
                    stack.append(child)
        return out


def tolerance(length: int) -> int:
    """How many typos a word of this length may contain. Short words must be exact: 'won' is not 'worn'."""
    if length <= 4:
        return 0
    return 1 if length <= 7 else 2


class FuzzyIndex:
    """Finds phrases that were typed with typos or stretched letters ('frree robus').

    Works word by word: long words may contain a typo, short words must match exactly, every word of the phrase
    must be present in order, and at least one word must actually differ (exact matches are the other index's job).
    """

    def __init__(self) -> None:
        self._tree = BKTree()
        self._by_anchor: dict[str, list[tuple[Rule, list[str], int]]] = {}
        self.size = 0
        self._correct = lru_cache(maxsize=30000)(self._correct_uncached)

    def build(self, rules: Iterable[Rule]) -> "FuzzyIndex":
        tree = BKTree()
        by_anchor: dict[str, list[tuple[Rule, list[str], int]]] = {}
        n = 0
        for r in rules:
            if r.regex or not r.fuzzy:
                continue
            words = (r.norm or deep_normalize(r.phrase)).split()
            long_idx = [i for i, w in enumerate(words) if len(w) >= 5]
            if not words or not long_idx:
                continue
            if len(words) == 1 and len(words[0]) < 8:
                continue  # a lone short word is too close to ordinary words ('double' vs 'doubler')
            anchor_i = max(long_idx, key=lambda i: len(words[i]))
            anchor = words[anchor_i]
            tree.add(anchor)
            by_anchor.setdefault(anchor, []).append((r, words, anchor_i))
            n += 1
        self._tree, self._by_anchor, self.size = tree, by_anchor, n
        self._correct.cache_clear()
        return self

    def _correct_uncached(self, token: str) -> tuple[tuple[str, int], ...]:
        if len(token) < 4:
            return ()
        near = self._tree.query(token, 2)
        return tuple((w, d) for w, d in near if d <= tolerance(len(w)) and w[0] == token[0])

    def _word_ok(self, want: str, have: str) -> int | None:
        if want == have:
            return 0
        t = tolerance(len(want))
        if not t or len(have) < 4 or want[0] != have[0]:
            return None
        d = levenshtein(want, have, t)
        return d if d <= t else None

    def scan(self, text: str, skip: set[int] | None = None) -> list[Hit]:
        if not self.size:
            return []
        words = deep_normalize(text).split()[:80]
        hits: dict[int, Hit] = {}
        for j, token in enumerate(words):
            for anchor, _d in self._correct(token):
                for rule, rwords, ai in self._by_anchor.get(anchor, ()):
                    if id(rule) in hits or (skip and id(rule) in skip):
                        continue
                    start = j - ai
                    if start < 0 or start + len(rwords) > len(words):
                        continue
                    typos, ok = 0, True
                    for k, want in enumerate(rwords):
                        d = self._word_ok(want, words[start + k])
                        if d is None:
                            ok = False
                            break
                        typos += d
                    if ok and typos:
                        hits[id(rule)] = Hit(rule, "fuzzy", " ".join(words[start:start + len(rwords)]), typos)
        return list(hits.values())
