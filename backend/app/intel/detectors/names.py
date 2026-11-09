"""Lookalike names: a chatter whose name sounds official, copies yours or a mod's, or carries contact details."""
from __future__ import annotations

import re

from ..text import damerau, flat, noisy_or
from .base import Ctx, Detector, Finding
from ...moderation.normalize import normalize

_CONTACT = re.compile(r"(?i)(?:https?://|www\.|t\.me/|wa\.me/|@[a-z0-9_]{3,}|\b[a-z0-9\-]+\.(?:com|net|xyz|top|link|me|gg)\b|\+?\d[\d\s-]{8,})")


class NameDetector(Detector):
    id = "names"
    title = "Lookalike names"
    signal = "lookalike_name"
    description = "Flags chat names that claim to be staff ('YouTube Support'), copy the channel owner or a moderator (even with look-alike letters), or contain a link or phone number."

    def analyze(self, ctx: Ctx) -> Finding | None:
        name = (ctx.author_name or "").strip()
        if len(name) < 3:
            return None
        parts: list[tuple[float, str]] = []
        words = set(normalize(name).split())
        joined = " " + normalize(name) + " "
        hit = [(t, w) for t, w in self.registry.identity_entries() if f" {normalize(t)} " in joined or normalize(t) in words]
        if hit:
            hit.sort(key=lambda x: -x[1])
            parts.append((hit[0][1] / 100 * 0.9, f'name says "{hit[0][0]}"'))
        nf = flat(name)
        for p in self.svc.protected_names():
            pf = flat(p)
            if len(pf) < 4:
                continue
            same_text = name.casefold().strip() == p.casefold().strip()
            if same_text:
                continue                      # that is the real person, not a copy
            if nf == pf:
                parts.append((0.9, f'looks the same as "{p}" with different letters'))
            elif len(pf) >= 5 and damerau(nf, pf, 1) == 1:
                parts.append((0.75, f'one letter away from "{p}"'))
            elif pf in nf and 0 < len(nf) - len(pf) <= 12:
                parts.append((0.55, f'contains "{p}" plus extra words'))
        if _CONTACT.search(name):
            parts.append((0.6, "contact details in the name"))
        if not parts:
            return None
        strength = noisy_or(s for s, _ in parts)
        if self.sensitivity() < 0.3:
            strength *= 0.7
        return Finding(min(1.0, strength), "; ".join(d for _, d in parts[:2]))
