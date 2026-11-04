"""Text normalisation used by the moderation engine (standard library only).

Spammers disguise banned words with look-alike letters (Cyrillic 'а'), leetspeak (fr33 r0bux),
zero-width characters, stretched letters and spacing (f.r.e.e). Everything is folded to a plain
canonical form before matching.
"""
from __future__ import annotations

import re
import unicodedata

_ZERO_WIDTH = {ord(c): None for c in "​‌‍⁠﻿­᠎⁢⁣"}

# Look-alike letters from Cyrillic and Greek that survive NFKC, mapped to Latin.
_CONFUSABLES = {
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c",
    "т": "t", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ɡ": "g", "ӏ": "l",
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t",
    "υ": "u", "χ": "x", "ı": "i",
}
_DIGIT_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b"})
_SYMBOL_LEET = {"@": "a", "$": "s", "!": "i", "|": "i", "+": "t"}
# A symbol only counts as a disguised letter when it sits between word characters (sc@m, fr!end).
_INNER_SYMBOL = re.compile(r"(?<=\w)([@$!|+])(?=\w)")
_PUNCT = re.compile(r"[^\w\s]|_")
_WS = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")


def fold(text: str) -> str:
    """Unicode-fold: NFKC (full-width, maths-bold -> ASCII), casefold, drop zero-width, map look-alikes."""
    t = unicodedata.normalize("NFKC", text or "").casefold().translate(_ZERO_WIDTH)
    return "".join(_CONFUSABLES.get(ch, ch) for ch in t)


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def normalize(text: str, collapse: int = 1) -> str:
    """Aggressive form for banned-phrase matching.

    collapse=1 reduces any run of a repeated character to one ('freeee' -> 'fre'), applied to both
    the phrase and the message, so stretched spelling still matches.
    """
    t = strip_accents(fold(text))
    t = _INNER_SYMBOL.sub(lambda m: _SYMBOL_LEET[m.group(1)], t)
    t = t.translate(_DIGIT_LEET)
    t = _PUNCT.sub(" ", t)
    if collapse:
        t = re.sub(r"(.)\1{%d,}" % collapse, r"\1" * collapse, t)
    return _WS.sub(" ", t).strip()


def squash(text: str) -> str:
    """normalize() with all spaces removed; catches 'f r e e  r o b u x' style spacing."""
    return normalize(text).replace(" ", "")


def canon(text: str) -> str:
    """Gentle canonical form for duplicate / similarity checks.

    Digits are removed so 'join now 4821' and 'join now 9033' look identical (raids append random
    numbers to dodge exact-match filters).
    """
    t = strip_accents(fold(text))
    t = _DIGITS.sub(" ", t)
    t = _PUNCT.sub(" ", t)
    return _WS.sub(" ", t).strip()
