"""Evasion tricks: text built to slip past a filter (mixed alphabets, stacked accents, hidden characters, spaced letters, leetspeak).

The bot's normaliser quietly undoes these disguises so banned words still match. This detector notices that someone
tried to hide the text, which is a reason to look harder.
"""
from __future__ import annotations

import re
import unicodedata

from ..text import combining_ratio, lerp, mixed_script_words, noisy_or
from .base import Ctx, Detector, Finding

_SPACED = re.compile(r"(?<!\w)(?:\w[\s.\-_*]+){5,}\w(?!\w)")
_LEET_WORD = re.compile(r"\b(?:[a-z]{2,}\d+[a-z]+|[a-z]+\d+[a-z]{2,})\b", re.I)
_INNER_SYMBOL = re.compile(r"(?<=[a-z])[@$!|](?=[a-z])", re.I)
_ALLOWED_LEET = re.compile(r"^(?:mp\d|ps\d|rtx\d+|gtx\d+|gen\d|top\d+|win\d+|h\d+|v\d+)$", re.I)


class EvasionDetector(Detector):
    id = "evasion"
    title = "Evasion tricks"
    signal = "evasion"
    description = "Notices text that is built to dodge filters: Latin mixed with Cyrillic, stacked accents, invisible characters, spaced-out letters and leetspeak."

    def analyze(self, ctx: Ctx) -> Finding | None:
        text = ctx.text
        found: list[tuple[float, str]] = []
        mixed = mixed_script_words(text)
        if mixed:
            found.append((0.6, "look-alike letters from another alphabet"))
        run = 0
        zalgo = combining_ratio(text) >= 0.25
        for ch in text:
            run = run + 1 if unicodedata.category(ch) == "Mn" else 0
            if run >= 3:
                zalgo = True
        if zalgo:
            found.append((0.5, "stacked accent marks"))
        hidden = sum(1 for ch in text if unicodedata.category(ch) == "Cf" and ch not in "\u200d\ufe0f")
        if hidden >= 2:
            found.append((0.45, "invisible characters"))
        if _SPACED.search(text):
            found.append((0.45, "letters spaced apart"))
        leet = [w for w in _LEET_WORD.findall(text) if not _ALLOWED_LEET.match(w)]
        if len(leet) >= 2:
            found.append((0.4, "numbers swapped for letters"))
        if len(_INNER_SYMBOL.findall(text)) >= 2:
            found.append((0.35, "symbols swapped for letters"))
        if not found:
            return None
        if self.sensitivity() < 0.3 and len(found) < 2:
            return None
        scale = lerp(0.75, 1.15, self.sensitivity())
        strength = min(1.0, noisy_or(s for s, _ in found) * scale)
        return Finding(strength, ", ".join(d for _, d in found), meta={"tricks": [d for _, d in found]})
