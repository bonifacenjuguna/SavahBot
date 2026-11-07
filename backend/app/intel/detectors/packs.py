"""Knowledge packs: exact phrase matching against every enabled phrase pack (Aho-Corasick, disguise-proof)."""
from __future__ import annotations

from ...moderation.engine import BlacklistMatcher
from ..text import flat, noisy_or
from .base import Ctx, Detector, Finding

DEFAULT_WEIGHT = 60


class PackDetector(Detector):
    id = "packs"
    title = "Knowledge packs"
    signal = "knowledge"
    description = "Looks for phrases from the enabled knowledge packs: promo spam, scams, adult bots, Kenyan fraud and your own entries. Sees through spacing, leetspeak and look-alike letters."

    def __init__(self, svc) -> None:
        super().__init__(svc)
        self._rev = -1
        self._matcher = BlacklistMatcher()

    def _ensure(self) -> None:
        if self._rev == self.registry.revision:
            return
        best: dict[str, dict] = {}                 # 'sub4sub' and 'sub 4 sub' are one phrase once disguises are undone
        for pack, text, weight, _tags in self.registry.phrase_entries():
            key, w = flat(text), weight or DEFAULT_WEIGHT
            if key and (key not in best or best[key]["weight"] < w):
                best[key] = {"phrase": text, "weight": w, "enabled": True, "_pack": pack.title}
        entries = [{"id": i, **e} for i, e in enumerate(best.values())]
        self._matcher.rebuild(entries)
        self._rev = self.registry.revision

    def analyze(self, ctx: Ctx) -> Finding | None:
        self._ensure()
        hits = self._matcher.scan(ctx.text)
        if not hits:
            return None
        hits.sort(key=lambda h: -h["weight"])
        strength = noisy_or(min(1.0, h["weight"] / 100) for h in hits)
        # Higher sensitivity lets two weak hints count for a little more; lower trims lone weak hits.
        if len(hits) == 1 and hits[0]["weight"] < 30 and self.sensitivity() < 0.4:
            return None
        detail = ", ".join(f'{h["_pack"]}: {h["phrase"]}' for h in hits[:2]) + (f" and {len(hits) - 2} more" if len(hits) > 2 else "")
        return Finding(strength, detail, [flat(h["phrase"]) for h in hits], {"hits": len(hits)})
