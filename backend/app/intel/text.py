"""Small text and maths tools shared by the detectors (standard library only).

Nothing here knows about chat, settings or the database, so every function can be tested on its own.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Iterable

from ..moderation.normalize import fold, normalize, strip_accents

_WS = re.compile(r"\s+")
_REPEAT = re.compile(r"(.)\1+")
_VOWELS = set("aeiou")


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * clamp(t)


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-min(x, 60)))
    e = math.exp(max(x, -60))
    return e / (1.0 + e)


def noisy_or(strengths: Iterable[float]) -> float:
    """Combine independent hints: two weak ones add up, a strong one stays strong, the total never passes 1."""
    miss = 1.0
    for s in strengths:
        miss *= 1.0 - clamp(s)
    return 1.0 - miss


def flat(text: str) -> str:
    """Letters only, no spaces, repeats collapsed: 'f r e e e  r0bux' -> 'frerobux'."""
    return _REPEAT.sub(r"\1", normalize(text).replace(" ", ""))


def lite(text: str) -> str:
    """A gentle form that keeps digits and punctuation (money amounts, phone numbers, links stay visible)."""
    t = strip_accents(fold(text))
    return _WS.sub(" ", t).strip()


def words(text: str) -> list[str]:
    return normalize(text).split()


def damerau(a: str, b: str, limit: int | None = None) -> int:
    """Edit distance counting a swap of two neighbours as one edit. Stops early once it is certain to pass `limit`."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if limit is not None and abs(la - lb) > limit:
        return limit + 1
    if not la or not lb:
        return max(la, lb)
    prev2: list[int] | None = None
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        lo = i
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if prev2 is not None and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
            lo = min(lo, v)
        if limit is not None and lo > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[lb]


def ngrams(s: str, n: int = 3) -> set[str]:
    return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else ({s} if s else set())


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def skeleton(s: str) -> str:
    """Consonants only, repeats collapsed: 'frree robux' and 'fre rbx' both become 'frrbx'-like cores."""
    return _REPEAT.sub(r"\1", "".join(ch for ch in s if ch not in _VOWELS and ch != " "))


def entropy(s: str) -> float:
    """Shannon entropy in bits per character. Ordinary words sit around 3 to 4; keyboard mashing is higher or very low."""
    if not s:
        return 0.0
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in Counter(s).values())


def longest_consonant_run(word: str) -> int:
    best = run = 0
    for ch in word:
        if ch.isalpha() and ch not in _VOWELS and ch != "y":
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def script_of(ch: str) -> str:
    """'latin', 'cyrillic', 'greek' or 'other' for a letter ('' for anything that is not a letter)."""
    if not ch.isalpha():
        return ""
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "other"
    for key in ("LATIN", "CYRILLIC", "GREEK"):
        if name.startswith(key):
            return key.lower()
    return "other"


def mixed_script_words(text: str) -> list[str]:
    """Words that mix Latin with Cyrillic or Greek letters: the classic look-alike disguise."""
    out = []
    for w in re.findall(r"\w+", text):
        kinds = {script_of(c) for c in w if c.isalpha()}
        if "latin" in kinds and kinds & {"cyrillic", "greek"}:
            out.append(w)
    return out


def combining_ratio(text: str) -> float:
    """Share of characters that are combining marks (stacked accents, 'zalgo' text)."""
    if not text:
        return 0.0
    return sum(1 for ch in text if unicodedata.category(ch) == "Mn") / len(text)
