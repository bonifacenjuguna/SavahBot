"""Viewer reputation: how a chatter has behaved before shapes how much a borderline message counts.

Trusted chatters (many clean messages over days) get a small discount, never more than 40% of the score and never when a
blocked phrase matched. Chatters who were punished before count extra when they trip another signal. A message that
repeats text that was already blocked from someone else (a banned user coming back on a new account) is flagged strongly.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass

from ..text import clamp, flat
from .base import Ctx, Detector, Finding

REPEAT_WINDOW = 6 * 3600


@dataclass
class Record:
    first: float
    last: float = 0.0
    msgs: int = 0
    flagged: int = 0
    punished: int = 0
    cleared: int = 0
    hydrated: bool = False


class ReputationDetector(Detector):
    id = "reputation"
    title = "Viewer reputation"
    signal = "reputation"
    description = "Remembers how each chatter behaved. Long-time clean chatters get benefit of the doubt on borderline messages; repeat offenders and 'new account, same blocked text' get extra attention."
    needs_history = True

    def __init__(self, svc) -> None:
        super().__init__(svc)
        self.records: "OrderedDict[str, Record]" = OrderedDict()
        self.blocked_text: "OrderedDict[int, float]" = OrderedDict()

    # ------------------------------------------------------------------ memory
    def record(self, key: str, now: float) -> Record:
        rec = self.records.get(key)
        if rec is None:
            rec = self.records[key] = Record(first=now)
            while len(self.records) > 5000:
                self.records.popitem(last=False)
        else:
            self.records.move_to_end(key)
        return rec

    def hydrate(self, key: str, hist: dict, now: float) -> None:
        rec = self.record(key, now)
        if rec.hydrated:
            return
        rec.hydrated = True
        if hist.get("first"):
            rec.first = min(rec.first, float(hist["first"]))
        rec.msgs = max(rec.msgs, int(hist.get("messages", 0)))
        rec.flagged = max(rec.flagged, int(hist.get("flagged", 0)))
        rec.punished = max(rec.punished, int(hist.get("punished", 0)))
        rec.cleared = max(rec.cleared, int(hist.get("cleared", 0)))

    def note_result(self, key: str, now: float, action: str) -> None:
        rec = self.record(key, now)
        rec.msgs += 1
        rec.last = now
        if action != "allow":
            rec.flagged += 1

    def note_punished(self, key: str, text: str, now: float) -> None:
        self.record(key, now).punished += 1
        f = flat(text)
        if len(f) >= 8:
            self.blocked_text[hash(f)] = now
            self.blocked_text.move_to_end(hash(f))
            while len(self.blocked_text) > 500:
                self.blocked_text.popitem(last=False)

    # ------------------------------------------------------------------ judging
    def analyze(self, ctx: Ctx) -> Finding | None:
        if ctx.stateless or not ctx.author_key:
            return None
        parts: list[tuple[float, str]] = []
        seen = self.blocked_text.get(hash(ctx.flat)) if len(ctx.flat) >= 8 else None
        if seen is not None and ctx.now - seen <= REPEAT_WINDOW:
            parts.append((0.9, "repeats a message that was already blocked"))
        rec = self.records.get(ctx.author_key)
        if rec is not None:
            if rec.punished:
                parts.append((clamp(0.35 * rec.punished, 0, 0.8), f"punished {rec.punished}x before"))
            if rec.msgs >= 5 and rec.flagged / rec.msgs >= 0.3:
                parts.append((0.3, "many of their messages were flagged"))
        if parts:
            s = max(p for p, _ in parts)
            return Finding(s, "; ".join(d for _, d in parts))
        if rec is not None and ctx.base_score > 0 and not ctx.exact and rec.punished == 0:
            age_days = max(0.0, (ctx.now - rec.first) / 86400)
            clean = 1 - (rec.flagged / rec.msgs if rec.msgs else 1)
            trust = clamp(min(rec.msgs, 200) / 200 * 0.6 + min(age_days, 30) / 30 * 0.4) * clean
            if rec.msgs >= 15 and age_days >= 1 and trust >= 0.3:
                return Finding(-trust * clamp(ctx.base_score / 60), f"{rec.msgs} clean messages over {age_days:.0f} days")
        return None
