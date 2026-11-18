"""Text toolkit for the intelligence layer (standard library only).

Fuzzy matching (Levenshtein, Jaro-Winkler, approximate substring search), a deeper normaliser than the
one the blocklist uses, and detectors for text tricks: zalgo, invisible characters, mixed scripts.
Nothing here learns or calls out; every function is a small, testable algorithm.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from ..moderation.normalize import normalize

# ---------------------------------------------------------------------------- deeper normalisation
# Look-alike letters and symbol sequences live in packs/normalize/confusables.json so they can be extended
# without touching code. Applied BEFORE the base normaliser.
def _load_maps() -> tuple[dict[str, str], list[tuple[str, str]]]:
    try:
        data = json.loads((Path(__file__).parent / "packs" / "normalize" / "confusables.json").read_text(encoding="utf-8"))
        letters = {str(k): str(v) for k, v in data.get("letters", {}).items()}
        seqs = [(str(a), str(b)) for a, b in data.get("sequences", [])]
        return letters, sorted(seqs, key=lambda x: -len(x[0]))
    except (OSError, ValueError):  # a broken file must not stop the bot: fall back to the base normaliser only
        return {}, []


_EXTRA, _SEQUENCES = _load_maps()
_ZW = {ord(c): None for c in "\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e\u2062\u2063"}


def deep_normalize(text: str) -> str:
    """Base normalisation plus the extra look-alikes and symbol sequences above."""
    t = unicodedata.normalize("NFKC", text or "").casefold().translate(_ZW)
    t = "".join(_EXTRA.get(ch, ch) for ch in t)
    for seq, rep in _SEQUENCES:
        if seq in t:
            t = t.replace(seq, rep)
    return normalize(t)


def flat(text: str) -> str:
    """deep_normalize with spaces removed and repeated letters collapsed ('f r e e e' -> 'fre')."""
    return re.sub(r"(.)\1+", r"\1", deep_normalize(text).replace(" ", ""))


# ---------------------------------------------------------------------------- distances
def levenshtein(a: str, b: str, max_dist: int | None = None) -> int:
    """Edit distance, with an early exit once it must exceed max_dist (returns max_dist + 1)."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if max_dist is not None and len(a) - len(b) > max_dist:
        return max_dist + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if max_dist is not None and min(cur) > max_dist:
            return max_dist + 1
        prev = cur
    return prev[-1]


def jaro(a: str, b: str) -> float:
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    window = max(la, lb) // 2 - 1
    ma, mb = [False] * la, [False] * lb
    matches = 0
    for i, ca in enumerate(a):
        for j in range(max(0, i - window), min(lb, i + window + 1)):
            if not mb[j] and b[j] == ca:
                ma[i] = mb[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    k = trans = 0
    for i in range(la):
        if ma[i]:
            while not mb[k]:
                k += 1
            if a[i] != b[k]:
                trans += 1
            k += 1
    return (matches / la + matches / lb + (matches - trans / 2) / matches) / 3


def jaro_winkler(a: str, b: str, p: float = 0.1) -> float:
    j = jaro(a, b)
    prefix = 0
    for ca, cb in zip(a[:4], b[:4]):
        if ca != cb:
            break
        prefix += 1
    return j + prefix * p * (1 - j)


def approx_find(pattern: str, text: str, max_dist: int) -> int | None:
    """Smallest edit distance between `pattern` and ANY substring of `text` (Sellers' algorithm).

    Returns None when it is above max_dist. O(len(text) * len(pattern)); callers only use it on a short
    list of candidates picked by the trigram index.
    """
    m = len(pattern)
    if not m or not text:
        return None
    col = list(range(m + 1))
    best = m
    for c in text:
        new = [0]
        for i in range(1, m + 1):
            new.append(min(col[i - 1] + (pattern[i - 1] != c), col[i] + 1, new[i - 1] + 1))
        col = new
        if col[m] < best:
            best = col[m]
            if best == 0:
                break
    return best if best <= max_dist else None


# ---------------------------------------------------------------------------- tokens
_URL = re.compile(r"(?i)(?:https?://|www\.)\S+|\b[a-z0-9\-]+\.(?:com|net|org|io|gg|tv|xyz|ru|me|co|ly|link|top|club|site|online)\b\S*")
_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_MENTION = re.compile(r"@\w+")


def tokens(text: str, markers: bool = True) -> list[str]:
    """Words for statistical models. URLs, mentions and numbers become generic markers, so
    'send 0.5 btc to bc1...' and 'send 2 btc to bc1...' look alike to the model."""
    t = unicodedata.normalize("NFKC", text or "").casefold()
    if markers:
        t = _URL.sub(" urlmark ", t)
        t = _MENTION.sub(" mentionmark ", t)
        t = _NUM.sub(" nummark ", t)
    return [w for w in deep_normalize(t).split() if w]


def ngrams(words: list[str], n: int) -> list[str]:
    return [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]


# ---------------------------------------------------------------------------- text tricks
def script_of(ch: str) -> str | None:
    if not ch.isalpha():
        return None
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "other"
    for tag, label in (("LATIN", "latin"), ("CYRILLIC", "cyrillic"), ("GREEK", "greek"), ("ARMENIAN", "armenian")):
        if name.startswith(tag):
            return label
    return "other"


def mixed_script_words(text: str) -> list[str]:
    """Words that mix Latin with Cyrillic/Greek/Armenian letters: the signature of a disguised word."""
    out = []
    for w in re.findall(r"\w+", text or ""):
        scripts = {s for s in (script_of(c) for c in w) if s}
        if "latin" in scripts and scripts & {"cyrillic", "greek", "armenian"}:
            out.append(w)
    return out


def zalgo(text: str) -> tuple[int, int]:
    """(combining marks, letters). Zalgo text stacks many marks on each letter."""
    marks = letters = 0
    for ch in unicodedata.normalize("NFD", text or ""):
        cat = unicodedata.category(ch)
        if cat == "Mn":
            marks += 1
        elif cat.startswith("L"):
            letters += 1
    return marks, letters


_INVISIBLE = set("\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e\u2062\u2063\u2064\u200e\u200f")
_BIDI = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
_ART = (range(0x2500, 0x2600), range(0x2800, 0x2900), range(0x25A0, 0x2600), range(0x2190, 0x2200))


def invisible_count(text: str) -> int:
    return sum(1 for ch in text or "" if ch in _INVISIBLE)


def bidi_count(text: str) -> int:
    return sum(1 for ch in text or "" if ch in _BIDI)


def art_ratio(text: str) -> float:
    """Share of non-space characters that are box-drawing, block, braille or arrow symbols."""
    body = [ch for ch in text or "" if not ch.isspace()]
    if not body:
        return 0.0
    n = sum(1 for ch in body if any(ord(ch) in r for r in _ART))
    return n / len(body)


def spaced_letters(text: str) -> int:
    """Length of the longest run of single-character words ('f r e e  r o b u x' -> 9)."""
    best = run = 0
    for w in (text or "").split():
        if len(w) == 1 and w.isalnum():
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


_SECOND_PERSON = re.compile(r"(?i)\b(you|u|ur|your|youre|you're|yourself|ya|wewe|wako|yako|mwenzako|kwako)\b")


def second_person(text: str) -> bool:
    return bool(_SECOND_PERSON.search(text or ""))


@lru_cache(maxsize=4096)
def trigrams(s: str) -> frozenset[str]:
    return frozenset(s[i:i + 3] for i in range(len(s) - 2))
