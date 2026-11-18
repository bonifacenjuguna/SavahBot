"""Naive Bayes text classifier and BM25 ranking (standard library only).

Both are classic information-retrieval algorithms: they learn from word counts, run in microseconds, and
can be explained ('these words pushed the message towards spam').
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from typing import Any

from .textkit import ngrams, tokens


def features(text: str, limit: int = 60) -> list[str]:
    words = tokens(text)[:limit]
    return words + ngrams(words, 2)


class NaiveBayes:
    """Two-class (spam / ham) multinomial Naive Bayes with Laplace smoothing and a flat prior.

    The prior is flat on purpose: the training corpus is balanced by hand, not by real chat, so letting its
    ratio vote would only add noise. Words never seen in training are ignored.
    """

    def __init__(self, alpha: float = 1.0, max_vocab: int = 20000) -> None:
        self.alpha = alpha
        self.max_vocab = max_vocab
        self.spam: Counter[str] = Counter()
        self.ham: Counter[str] = Counter()
        self.docs = {"spam": 0, "ham": 0}

    def train(self, text: str, label: str, times: int = 1) -> None:
        if label not in ("spam", "ham"):
            raise ValueError("label must be spam or ham")
        target = self.spam if label == "spam" else self.ham
        for f in set(features(text)):
            target[f] += times
        self.docs[label] += times

    @property
    def trained(self) -> bool:
        return self.docs["spam"] >= 5 and self.docs["ham"] >= 5

    def predict(self, text: str, top: int = 3) -> tuple[float, list[str]]:
        """Return (probability the text is spam, the words that pushed it hardest towards spam)."""
        if not self.trained:
            return 0.5, []
        vocab = len(set(self.spam) | set(self.ham)) or 1
        ts = sum(self.spam.values()) + self.alpha * vocab
        th = sum(self.ham.values()) + self.alpha * vocab
        log_odds = 0.0
        pushes: list[tuple[float, str]] = []
        for f in set(features(text)):
            s, h = self.spam.get(f, 0), self.ham.get(f, 0)
            if not s and not h:
                continue
            d = math.log((s + self.alpha) / ts) - math.log((h + self.alpha) / th)
            log_odds += d
            if d > 0:
                pushes.append((d, f))
        log_odds = max(-30.0, min(30.0, log_odds))
        p = 1 / (1 + math.exp(-log_odds))
        pushes.sort(reverse=True)
        return p, [w for _, w in pushes[:top]]

    # ---- persistence: only the learned part is stored, the built-in corpus is re-read from disk ----
    def dump(self) -> str:
        def top(c: Counter[str]) -> dict[str, int]:
            return dict(c.most_common(self.max_vocab // 2))
        return json.dumps({"spam": top(self.spam), "ham": top(self.ham), "docs": self.docs})

    @classmethod
    def load(cls, raw: str) -> "NaiveBayes":
        nb = cls()
        data = json.loads(raw)
        nb.spam, nb.ham = Counter(data.get("spam", {})), Counter(data.get("ham", {}))
        nb.docs = {"spam": int(data.get("docs", {}).get("spam", 0)), "ham": int(data.get("docs", {}).get("ham", 0))}
        return nb


class BM25:
    """Okapi BM25 over short documents. Used to find the known-spam example a message most resembles, and to
    rank search results in the knowledge browser."""

    def __init__(self, k1: float = 1.4, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._docs: dict[Any, list[str]] = {}
        self._postings: dict[str, dict[Any, int]] = defaultdict(dict)
        self._len: dict[Any, int] = {}
        self._avg = 1.0

    def build(self, docs: list[tuple[Any, str]], tokenizer=tokens) -> "BM25":
        self._docs.clear()
        self._postings = defaultdict(dict)
        self._len.clear()
        for key, text in docs:
            words = tokenizer(text)
            self._docs[key] = words
            self._len[key] = len(words)
            for w, n in Counter(words).items():
                self._postings[w][key] = n
        self._avg = (sum(self._len.values()) / len(self._len)) if self._len else 1.0
        return self

    def __len__(self) -> int:
        return len(self._docs)

    def words(self, key: Any) -> list[str]:
        return self._docs.get(key, [])

    def search(self, query: str, top: int = 5, tokenizer=tokens) -> list[tuple[float, Any]]:
        n = len(self._docs)
        if not n:
            return []
        scores: dict[Any, float] = defaultdict(float)
        for w in set(tokenizer(query)):
            posting = self._postings.get(w)
            if not posting:
                continue
            idf = math.log(1 + (n - len(posting) + 0.5) / (len(posting) + 0.5))
            for key, tf in posting.items():
                norm = tf + self.k1 * (1 - self.b + self.b * self._len[key] / self._avg)
                scores[key] += idf * tf * (self.k1 + 1) / norm
        return sorted(((s, k) for k, s in scores.items()), reverse=True)[:top]
