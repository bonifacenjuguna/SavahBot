"""Scam patterns: recognises the *shape* of a scam message rather than single words.

Each shape is a group (money doubling, prize announcement, urgency, contact lure, fake support, reversal trick...). One
group alone is weak evidence. Several together are combined as independent hints (noisy-or), so 'you have won' plus
'click the link' plus 'DM me' lands high, while an ordinary 'you won the match!' stays quiet. A few groups are strong
enough on their own (money doubling, asking for a PIN or seed phrase, the fake M-Pesa reversal).
"""
from __future__ import annotations

import re
from typing import Any

from ..text import noisy_or
from .base import Ctx, Detector, Finding


class ScamDetector(Detector):
    id = "scam"
    title = "Scam patterns"
    signal = "scam_pattern"
    description = "Recognises scam message shapes: money doubling, fake prizes, fake support, M-Pesa reversal tricks, job-group lures, pressure to act now. Several weak hints together count; a single one does not."

    def __init__(self, svc) -> None:
        super().__init__(svc)
        self._rev = -1
        self._groups: list[tuple[dict[str, Any], list[re.Pattern]]] = []

    def _ensure(self) -> None:
        if self._rev == self.registry.revision:
            return
        compiled = []
        for g in self.registry.template_groups():
            pats = []
            for p in g.get("patterns", []):
                try:
                    pats.append(re.compile(p, re.I))
                except re.error:
                    continue
            if pats:
                compiled.append((g, pats))
        self._groups, self._rev = compiled, self.registry.revision

    def analyze(self, ctx: Ctx) -> Finding | None:
        self._ensure()
        text = ctx.lite[:600]
        if len(text) < 8:
            return None
        hits = [g for g, pats in self._groups if any(p.search(text) for p in pats)]
        if not hits:
            return None
        strong = any(g.get("strong") for g in hits)
        if len(hits) == 1 and not strong:
            g = hits[0]
            if not (self.sensitivity() >= 0.8 and int(g.get("w", 0)) >= 40):
                return None
            strength = noisy_or([int(g.get("w", 0)) / 100]) * 0.6
        else:
            strength = noisy_or(int(g.get("w", 0)) / 100 for g in hits)
        titles = ", ".join(str(g.get("title", g.get("id"))) for g in sorted(hits, key=lambda g: -int(g.get("w", 0)))[:3])
        return Finding(min(1.0, strength), titles, meta={"groups": [g.get("id") for g in hits]})
