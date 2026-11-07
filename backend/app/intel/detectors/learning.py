"""Learning filter: a Naive Bayes text classifier that learns what spam looks like in YOUR chat.

No AI service and no downloaded model: it counts, for every word, word pair and word fragment, how often it showed up in
messages you called spam and in messages you called fine. A new message is scored by adding up those clues. Word
fragments (4-letter pieces) let it cope with typos and with Swahili word endings. It starts with the training
examples from the knowledge packs, then learns from your Approve and Reject decisions and from the 'Teach the bot'
button. Every decision is stored, so any one of them can be forgotten later.
"""
from __future__ import annotations

import math
import re
from typing import Iterable

from ...moderation.normalize import normalize
from ..text import clamp, lerp, lite, sigmoid
from .base import Ctx, Detector, Finding

_TOKEN = re.compile(r"[a-z0-9']+")
_URL = re.compile(r"(?i)https?://|www\.|\b[a-z0-9\-]+\.(?:com|net|org|xyz|top|click|link|me|gg|ly)\b")
_PHONE = re.compile(r"\+?\d[\d\s-]{8,}\d")
MAX_VOCAB = 150_000
# Fragments and pairs overlap the words they come from, so each counts for less than a whole word.
FEATURE_WEIGHT = {"w": 1.0, "n": 1.0, "b": 0.7, "c": 0.3, "m": 0.8}


def features(text: str) -> set[str]:
    """The clues one message offers: words, word pairs, word fragments and a few shape hints."""
    lt = lite(text)[:600]
    toks = _TOKEN.findall(lt)
    plain = [("<n>" if t.isdigit() else t.strip("'")) for t in toks if t.strip("'")]
    feats: set[str] = {f"w:{t}" for t in plain if len(t) <= 30}
    norm_words = normalize(text[:600]).split()
    for t in norm_words:                      # the undisguised form: 'fr33' also teaches 'free'
        if t not in plain:
            feats.add(f"n:{t}")
    for a, b in zip(plain, plain[1:]):
        feats.add(f"b:{a}_{b}")
    for w in norm_words[:14]:
        if len(w) >= 5:
            p = f"^{w}$"
            feats.update(f"c:{p[i:i + 4]}" for i in range(len(p) - 3))
    letters = [c for c in text if c.isalpha()]
    if _URL.search(text):
        feats.add("m:link")
    if len(letters) >= 8 and sum(c.isupper() for c in letters) / len(letters) >= 0.6:
        feats.add("m:caps")
    if re.search(r"\d{3,}", text):
        feats.add("m:num")
    if _PHONE.search(text):
        feats.add("m:phone")
    if len(text) > 120:
        feats.add("m:long")
    if len(text) <= 12:
        feats.add("m:short")
    if text.count("!") >= 3:
        feats.add("m:exclaim")
    if "@" in text:
        feats.add("m:at")
    return feats


class NBModel:
    """Counts only: easy to add to, easy to take away from, easy to explain."""

    def __init__(self, prior: float = 0.15, alpha: float = 0.5) -> None:
        self.prior = prior
        self.alpha = alpha
        self.counts: dict[str, list[float]] = {}     # feature -> [weight in spam, weight in ham]
        self.docs = [0.0, 0.0]
        self.total = [0.0, 0.0]

    def _apply(self, text: str, label: str, weight: float, sign: int) -> None:
        i = 0 if label == "spam" else 1
        self.docs[i] = max(0.0, self.docs[i] + sign * weight)
        for f in features(text):
            row = self.counts.get(f)
            if row is None:
                if sign < 0 or len(self.counts) >= MAX_VOCAB:
                    continue
                row = self.counts[f] = [0.0, 0.0]
            row[i] = max(0.0, row[i] + sign * weight)
            self.total[i] = max(0.0, self.total[i] + sign * weight)
            if sign < 0 and row[0] <= 0 and row[1] <= 0:
                del self.counts[f]

    def add(self, text: str, label: str, weight: float = 1.0) -> None:
        self._apply(text, label, weight, +1)

    def remove(self, text: str, label: str, weight: float = 1.0) -> None:
        self._apply(text, label, weight, -1)

    @property
    def ready(self) -> bool:
        return self.docs[0] >= 3 and self.docs[1] >= 3

    def score(self, text: str) -> tuple[float, list[tuple[str, float]]]:
        """(chance it is spam 0-1, the strongest clues as (feature, push towards spam))."""
        if not self.ready:
            return self.prior, []
        feats = features(text)
        v = len(self.counts) + 1
        ds, dh = self.total[0] + self.alpha * v, self.total[1] + self.alpha * v
        known, llr_sum, clues = 0.0, 0.0, []
        for f in feats:
            row = self.counts.get(f)
            if row is None:
                continue
            fw = FEATURE_WEIGHT.get(f[0], 1.0)
            known += fw
            llr = math.log((row[0] + self.alpha) / ds) - math.log((row[1] + self.alpha) / dh)
            llr_sum += llr * fw
            clues.append((f, llr))
        if not known:
            return self.prior, []
        temper = max(1.0, math.sqrt(known / 8))                       # many overlapping clues must not shout
        p = sigmoid(math.log(self.prior / (1 - self.prior)) + llr_sum / temper)
        trust = clamp(len(clues) / max(1, len(feats)) * 1.5)               # mostly-unfamiliar text stays near the prior
        p = self.prior + (p - self.prior) * trust
        clues.sort(key=lambda c: -c[1])
        return p, clues

    def distrust(self, limit: int = 25, want: str = "spam", min_seen: float = 2.0) -> list[dict]:
        out = []
        v = len(self.counts) + 1
        ds, dh = self.total[0] + self.alpha * v, self.total[1] + self.alpha * v
        for f, (s, h) in self.counts.items():
            if f[:2] not in ("w:", "n:") or s + h < min_seen or len(f) <= 3:
                continue
            llr = math.log((s + self.alpha) / ds) - math.log((h + self.alpha) / dh)
            out.append({"token": f[2:], "score": round(llr, 2), "spam": round(s, 1), "ham": round(h, 1)})
        out.sort(key=lambda r: -r["score"] if want == "spam" else r["score"])
        return out[:limit]


def readable(feature: str) -> str:
    kind, _, body = feature.partition(":")
    return body.replace("_", " ") if kind in ("w", "n", "b") else ("shape: " + body if kind == "m" else f"…{body.strip('^$')}…")


class LearningDetector(Detector):
    id = "learning"
    title = "Learning filter"
    signal = "learned"
    description = "A statistical filter that learns from your own Approve and Reject decisions what spam looks like in your chat, in English, Swahili and Sheng. It improves the more you moderate and shows the words it relies on."

    def analyze(self, ctx: Ctx) -> Finding | None:
        model: NBModel = self.svc.model
        if not model.ready or len(ctx.text.strip()) < 4:
            return None
        p, clues = model.score(ctx.text)
        lo = lerp(0.93, 0.68, self.sensitivity())
        if p < lo:
            return None
        strength = clamp((p - lo) / (1 - lo))
        top = [readable(f) for f, llr in clues if llr > 0 and not f.startswith(("c:", "m:"))][:3]
        return Finding(strength, f"{p:.0%} like messages you called spam" + (f" ({', '.join(top)})" if top else ""), meta={"p": round(p, 3)})
