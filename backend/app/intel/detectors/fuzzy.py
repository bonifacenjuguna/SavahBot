"""Fuzzy matching: catches banned phrases that are misspelled, typo'd or disguised beyond what exact matching handles.

How it works (no AI): the message and every phrase are reduced to letters only. A trigram index narrows thousands of
phrases to a few candidates in one pass. Each candidate is compared with sliding windows of the message by edit
distance (a swap of two letters counts as one edit), and, as a second route, by consonant skeleton, which catches
dropped vowels ('frr rbx'). Phrases that already matched exactly are skipped so nothing is counted twice.
"""
from __future__ import annotations

import math
import re

from ...moderation.normalize import normalize
from ..text import damerau, flat, lerp, ngrams, skeleton
from .base import Ctx, Detector, Finding

_REPEAT = re.compile(r"(.)\1+")
MAX_CANDIDATES = 60
MAX_WORDS = 40


class FuzzyDetector(Detector):
    id = "fuzzy"
    title = "Fuzzy matching"
    signal = "fuzzy"
    description = "Catches blocked phrases with typos, swapped letters, dropped vowels or extra symbols, such as 'fre robxu' for 'free robux'. Uses your blocked phrases and every enabled knowledge pack."

    def __init__(self, svc) -> None:
        super().__init__(svc)
        self._rev = -1
        self._bl_rev = -1
        self._cands: list[dict] = []
        self._index: dict[str, list[int]] = {}

    # ------------------------------------------------------------------ index
    def _ensure(self) -> None:
        if self._rev == self.registry.revision and self._bl_rev == self.svc.blacklist_revision:
            return
        cands: dict[str, dict] = {}
        bl_default = int(self.svc.cfg.get("mod_blacklist_weight"))
        for pack, text, weight, _tags in self.registry.phrase_entries():
            self._add(cands, text, weight or 60, pack.title)
        for e in self.svc.blacklist:
            if e.get("enabled", True) and not e.get("is_regex") and e.get("phrase"):
                self._add(cands, e["phrase"], int(e.get("weight") or bl_default), "Blocked phrase")
        self._cands = list(cands.values())
        index: dict[str, list[int]] = {}
        for i, c in enumerate(self._cands):
            for g in c["tri"]:
                index.setdefault(g, []).append(i)
        self._index, self._rev, self._bl_rev = index, self.registry.revision, self.svc.blacklist_revision

    @staticmethod
    def _add(out: dict[str, dict], phrase: str, weight: int, source: str) -> None:
        pf = flat(phrase)
        if len(pf) < 6 or pf in out and out[pf]["w"] >= weight:
            return
        out[pf] = {"phrase": phrase, "flat": pf, "w": weight, "k": len(normalize(phrase).split()), "sk": skeleton(pf), "tri": ngrams(pf), "src": source}

    # ------------------------------------------------------------------ matching
    def analyze(self, ctx: Ctx) -> Finding | None:
        self._ensure()
        if ctx.exact or not self._cands or len(ctx.flat) < 5:
            return None            # something already matched exactly: nothing was missed
        text = self.svc.refold(ctx.text)
        words = normalize(text).split()[:MAX_WORDS]
        if not words:
            return None
        mf = _REPEAT.sub(r"\1", "".join(words))
        mtri = ngrams(mf)
        votes: dict[int, int] = {}
        for g in mtri:
            for i in self._index.get(g, ()):
                votes[i] = votes.get(i, 0) + 1
        sens = self.sensitivity()
        tol = lerp(0.10, 0.26, sens)
        best: tuple[float, dict, str, int] | None = None
        checked = 0
        for i, v in sorted(votes.items(), key=lambda kv: -kv[1]):
            c = self._cands[i]
            if c["flat"] in ctx.exact or v < max(2, math.ceil(0.45 * (len(c["flat"]) - 2))):
                continue
            checked += 1
            if checked > MAX_CANDIDATES:
                break
            pf, allowed = c["flat"], min(4, max(1, int(len(c["flat"]) * tol)))
            for size in range(max(1, c["k"] - 1), c["k"] + 2):
                for s in range(0, max(1, len(words) - size + 1)):
                    chunk = words[s:s + size]
                    wf = _REPEAT.sub(r"\1", "".join(chunk))
                    if abs(len(wf) - len(pf)) > allowed:
                        continue
                    if wf[:1] != pf[:1] and wf[-1:] != pf[-1:]:
                        continue                      # typos rarely change both ends of a word
                    d = damerau(wf, pf, allowed)
                    close = 0.0
                    if 0 < d <= allowed:
                        close = 1 - d / (allowed + 1)
                    elif d == 0:
                        continue                      # exact: the exact matchers own this one
                    elif (len(c["sk"]) >= 7 and wf[:1] == pf[:1] and wf[-1:] == pf[-1:] and abs(len(wf) - len(pf)) <= 3
                          and skeleton(wf) == c["sk"]):
                        close = 0.45                  # same consonants, vowels changed or dropped (long phrases only)
                    if close and (best is None or close * c["w"] > best[0]):
                        best = (close * c["w"], c, " ".join(chunk), d)
        if best is None:
            return None
        score, c, seen, d = best
        strength = min(1.0, (c["w"] / 100) * (0.55 + 0.45 * (score / max(1, c["w"]))))
        return Finding(strength, f'"{seen}" is close to "{c["phrase"]}" ({c["src"]})', [c["flat"]], {"edits": d})
