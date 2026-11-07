"""Plain-words explanations and a confidence estimate for moderation signals (standard library only)."""
from __future__ import annotations

from typing import Any

# How much each kind of signal can be trusted on its own, 0-1. Content signals that match known bad patterns
# are trusted more than behaviour hints, which are only suggestive.
RELIABILITY = {
    "blacklist": 0.90, "scam": 0.85, "link_risk": 0.80, "impersonation": 0.80, "raid": 0.80, "typo": 0.75,
    "spam": 0.75, "abuse": 0.70, "harassment": 0.75, "obfuscation": 0.70, "known_spam": 0.65, "intent": 0.60, "duplicate": 0.60,
    "link": 0.50, "rate": 0.50, "timing": 0.50, "raid_wave": 0.45, "bot_like": 0.40,
}
_PLAIN = {
    "blacklist": "Matched a phrase on your blocked list: {d}",
    "link": "Posted a link ({d}) without a permit",
    "caps": "Mostly capital letters ({d})",
    "symbols": "Mostly symbols ({d})",
    "emotes": "Too many emotes ({d})",
    "repetition": "Repeated itself ({d})",
    "length": "Very long message ({d})",
    "rate": "Posting faster than normal ({d})",
    "duplicate": "Sent the same message again ({d})",
    "raid": "Several accounts posted nearly the same text ({d})",
    "timing": "Posts on a fixed beat like a program ({d})",
    "new_chatter": "Joined chat only moments ago",
    "scam": "Reads like a scam: {d}",
    "spam": "Reads like spam or promotion: {d}",
    "abuse": "Contains abusive language: {d}",
    "harassment": "Threatens or harasses someone: {d}",
    "typo": "Looks like a blocked phrase written with typos or stretched letters: {d}",
    "link_risk": "A risky link: {d}",
    "impersonation": "Pretends to be staff or the streamer: {d}",
    "obfuscation": "Uses text tricks to dodge filters: {d}",
    "bot_like": "The account name and message look automated: {d}",
    "intent": "Word pattern is close to known spam: {d}",
    "known_spam": "Nearly the same as a known spam message: {d}",
    "raid_wave": "Part of a sudden wave of new accounts",
}


def explain(name: str, detail: str = "") -> str:
    tpl = _PLAIN.get(name)
    if tpl is None:
        return f"{name}: {detail}" if detail else name
    if "{d}" not in tpl:
        return tpl
    if not detail:
        return tpl.split(":")[0].split(" (")[0]
    return tpl.format(d=detail)


def confidence(signals: list[Any]) -> float:
    """Noisy-OR of per-signal trust. Several independent kinds of evidence agreeing push it up; one weak hint stays low."""
    if not signals:
        return 0.0
    miss = 1.0
    for s in signals:
        c = RELIABILITY.get(s.name, 0.4) * min(1.0, s.weight / 60)
        miss *= 1 - min(0.97, c)
    return round(1 - miss, 2)
