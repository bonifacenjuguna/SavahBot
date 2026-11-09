"""Bot shape: the statistics of how a message and its sender look, with no dictionary at all.

 * keyboard-mashing: long strings of consonants or random-looking letter soup
 * template spam: the same sender repeating one text with the words swapped (character-trigram overlap)
 * channel waves: a sudden burst of messages above the chat's own baseline, mostly from brand-new chatters
"""
from __future__ import annotations

import math
import re
from collections import OrderedDict, deque

from ..text import clamp, entropy, jaccard, lerp, longest_consonant_run, ngrams, noisy_or
from .base import Ctx, Detector, Finding

_WORD = re.compile(r"[^\W\d_]{7,}", re.UNICODE)
_SKIP = re.compile(r"(?i)https?://\S+|www\.\S+|\S+\.(?:com|net|org|xyz|top|ly)\S*|[@#!]\S+|:\w+:")
BUCKET = 10.0


class Pulse:
    """The chat's own rhythm: messages per 10 seconds against a slowly moving average."""

    def __init__(self) -> None:
        self.bucket = 0
        self.count = 0
        self.new = 0
        self.mean = 0.0
        self.var = 4.0
        self.warm = 0

    def tick(self, now: float, is_new: bool) -> tuple[int, float, float]:
        b = int(now // BUCKET)
        if b != self.bucket:
            if self.bucket:
                gaps = min(30, b - self.bucket - 1)           # quiet buckets between count as zeros
                for c in [self.count] + [0] * gaps:
                    d = c - self.mean
                    self.mean += 0.1 * d
                    self.var = 0.9 * (self.var + 0.1 * d * d)
                    self.warm += 1
            self.bucket, self.count, self.new = b, 0, 0
        self.count += 1
        self.new += 1 if is_new else 0
        return self.count, self.mean + 3 * math.sqrt(max(self.var, 1.0)), self.new / self.count


class ShapeDetector(Detector):
    id = "shape"
    title = "Bot shape"
    signal = "bot_shape"
    description = "Spots keyboard-mashing, one sender repeating a template with swapped words, and sudden waves of messages from brand-new accounts. Pure statistics, nothing to configure."

    def __init__(self, svc) -> None:
        super().__init__(svc)
        self.recent: "OrderedDict[str, deque]" = OrderedDict()
        self.pulse = Pulse()

    def analyze(self, ctx: Ctx) -> Finding | None:
        parts: list[tuple[float, str]] = []
        sens = self.sensitivity()
        body = _SKIP.sub(" ", ctx.text)
        toks = _WORD.findall(body)
        if toks:
            bad = [t for t in toks if self._mashed(t.lower())]
            if bad and len(bad) / len(toks) >= 0.5:
                parts.append((0.5 + 0.5 * len(bad) / len(toks), "looks like keyboard-mashing"))
        if not ctx.stateless and ctx.author_key and len(ctx.lite) >= 15:
            tri = ngrams(re.sub(r"\d+", "", ctx.lite))
            past = self.recent.get(ctx.author_key)
            if past:
                sims = [jaccard(tri, t) for t, ts in past if ctx.now - ts <= 600]
                limit = lerp(0.8, 0.55, sens)
                close = [s for s in sims if s >= limit]
                if len(close) >= (1 if sens >= 0.7 else 2):
                    parts.append((0.5 + 0.5 * sum(close) / len(close), f"sender repeats one template ({len(close) + 1} similar messages)"))
        if not ctx.stateless:
            count, ceiling, new_share = self.pulse.tick(ctx.now, ctx.is_new)
            if self.pulse.warm >= 12 and count >= max(8, ceiling) and new_share >= 0.5 and ctx.is_new:
                parts.append((0.5, f"channel wave: {count} messages in 10s, {new_share:.0%} from new chatters"))
        if not parts:
            return None
        return Finding(noisy_or(s for s, _ in parts), "; ".join(d for _, d in parts))

    def observe(self, ctx: Ctx) -> None:
        if ctx.stateless or not ctx.author_key or len(ctx.lite) < 15:
            return
        dq = self.recent.get(ctx.author_key)
        if dq is None:
            dq = self.recent[ctx.author_key] = deque(maxlen=6)
            while len(self.recent) > 3000:
                self.recent.popitem(last=False)
        else:
            self.recent.move_to_end(ctx.author_key)
        dq.append((ngrams(re.sub(r"\d+", "", ctx.lite)), ctx.now))

    @staticmethod
    def _mashed(w: str) -> bool:
        if longest_consonant_run(w) >= 6:
            return True
        vowels = sum(c in "aeiouy" for c in w) / len(w)
        if len(w) >= 8 and vowels < 0.10:
            return True
        return len(w) >= 10 and entropy(w) > 3.7 and len(set(w)) / len(w) > 0.8 and vowels < 0.25
