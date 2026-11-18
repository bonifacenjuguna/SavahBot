"""Auto-replies: a viewer sends a phrase, the bot answers.

This is the foundation for richer chat automation. A trigger has a phrase, a match type and a reply:

  exact  the whole message is the phrase (case and extra spaces ignored)   "gm"  ->  "gm", "GM", " gm "
  word   the phrase appears as a whole word or phrase inside a message     "discord"  ->  "is there a discord?"

New match types (starts with, regex, per-user rules ...) only need a new branch in `matches`.
"""
from __future__ import annotations

import re
from typing import Any


def key(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def matches(trigger: dict[str, Any], text: str) -> bool:
    phrase, said = key(trigger["phrase"]), key(text)
    if not phrase or not said:
        return False
    if trigger.get("match_type", "exact") == "word":
        return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", said) is not None
    return said == phrase
