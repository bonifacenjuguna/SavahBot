"""Moderation engine: layered, explainable, no machine learning.

Every message runs through independent *signals* (content rules and behaviour trackers). Each signal
adds weight to a 0-100 score; the score maps to an action ladder (allow < flag < delete < timeout <
ban). Repeat offenders escalate one rung. Every verdict lists the signals that fired, so you can
always see why something was caught and tune the weights from the dashboard.
"""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..utils import split_csv
from .ahocorasick import AhoCorasick
from .explain import confidence as _confidence, explain
from .normalize import normalize
from .trackers import BehaviorTracker, DuplicateTracker, SimilarityTracker, SlidingWindowCounter

ACTION_RANK = {"allow": -1, "flag": 0, "delete": 1, "timeout": 2, "ban": 3}

_DOT_WORD = re.compile(r"\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|\bdot\b)\s*", re.I)
_LINK = re.compile(
    r"(?i)(?:https?://|www\.)[^\s]+|\b[a-z0-9][a-z0-9\-]{1,62}\."
    r"(?:com|net|org|io|gg|tv|xyz|ru|me|co|ly|link|top|club|site|online|shop|info|biz|cc|app|dev|live|"
    r"stream|click|win|vip|fun|store|pro|icu)\b(?:/[^\s]*)?"
)
_SHORTCODE = re.compile(r":[a-zA-Z0-9_\-]{2,}:")
_EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0xFE00, 0xFE0F))


@dataclass
class ModInput:
    platform: str
    author_id: str
    author_name: str
    text: str
    level: str = "everyone"
    ts: float | None = None


@dataclass
class Signal:
    name: str
    weight: int
    detail: str = ""
    why: str = ""


@dataclass
class Verdict:
    score: int = 0
    action: str = "allow"
    duration: int | None = None
    signals: list[Signal] = field(default_factory=list)
    exempt: bool = False
    strikes: int = 0
    blacklist_ids: list[int] = field(default_factory=list)
    shadow: list[Signal] = field(default_factory=list)   # what Shadow-mode detectors found (never changes the score)
    confidence: float = 0.0

    @property
    def reasons(self) -> list[str]:
        return [f"{s.name}: {s.detail}" if s.detail else s.name for s in self.signals]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "action": self.action,
            "duration": self.duration,
            "exempt": self.exempt,
            "strikes": self.strikes,
            "confidence": self.confidence,
            "signals": [_sig(s) for s in self.signals],
            "shadow": [_sig(s) for s in self.shadow],
        }


def _sig(s: Signal) -> dict[str, Any]:
    return {"name": s.name, "weight": s.weight, "detail": s.detail, "why": s.why or explain(s.name, s.detail)}


class PermitStore:
    """Temporary link permits created by the !permit command."""

    def __init__(self) -> None:
        self._until: dict[str, float] = {}

    def permit(self, name: str, seconds: float, now: float | None = None) -> None:
        self._until[name.lower().lstrip("@")] = (now if now is not None else time.time()) + seconds

    def is_permitted(self, name: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        key = name.lower().lstrip("@")
        until = self._until.get(key)
        if until is None:
            return False
        if until < now:
            del self._until[key]
            return False
        return True


class BlacklistMatcher:
    """Banned phrases (Aho-Corasick) + regex entries, matched against disguised text."""

    def __init__(self) -> None:
        self._spaced = AhoCorasick()
        self._squashed = AhoCorasick()
        self._regex: list[tuple[re.Pattern, dict]] = []
        self.size = 0

    def rebuild(self, entries: list[dict]) -> None:
        spaced, squashed, regexes = AhoCorasick(), AhoCorasick(), []
        count = 0
        for e in entries:
            if not e.get("enabled", True):
                continue
            phrase = (e.get("phrase") or "").strip()
            if not phrase:
                continue
            count += 1
            if e.get("is_regex"):
                try:
                    regexes.append((re.compile(phrase, re.I), e))
                except re.error:
                    count -= 1
                continue
            p = normalize(phrase)
            if not p:
                count -= 1
                continue
            # Short phrases must match whole words; padding with spaces enforces the boundary.
            spaced.add(f" {p} " if len(p.replace(" ", "")) <= 4 else p, e)
            flat = _flat(p)
            if len(flat) >= 6:
                squashed.add(flat, e)
        spaced.build()
        squashed.build()
        self._spaced, self._squashed, self._regex, self.size = spaced, squashed, regexes, count

    def scan(self, text: str) -> list[dict]:
        if not self.size:
            return []
        padded = f" {normalize(text)} "
        hits: dict[Any, dict] = {}
        for _, _, e in self._spaced.search(padded):
            hits[e.get("id", e["phrase"])] = e
        for _, _, e in self._squashed.search(_flat(padded)):
            hits[e.get("id", e["phrase"])] = e
        sample = text[:500]
        for rx, e in self._regex:
            if rx.search(sample):
                hits[e.get("id", e["phrase"])] = e
        return list(hits.values())


def _flat(text: str) -> str:
    """Remove spaces, then collapse repeated characters again (spacing can create new runs)."""
    return re.sub(r"(.)\1+", r"\1", text.replace(" ", ""))


def _count_emotes(text: str) -> int:
    n = len(_SHORTCODE.findall(text))
    for ch in text:
        o = ord(ch)
        if any(lo <= o <= hi for lo, hi in _EMOJI_RANGES):
            n += 1
    return n


def _domain(url: str) -> str:
    d = re.sub(r"^https?://", "", url.lower())
    d = d.split("/")[0].split("?")[0].split(":")[0]
    return d[4:] if d.startswith("www.") else d


class ModerationEngine:
    def __init__(self, cfg: Any, permits: PermitStore | None = None) -> None:
        self.cfg = cfg
        self.permits = permits or PermitStore()
        self.matcher = BlacklistMatcher()
        self.rate = SlidingWindowCounter()
        self.dups = DuplicateTracker()
        self.sims = SimilarityTracker()
        self.behavior = BehaviorTracker()
        self._strikes: dict[str, deque[float]] = {}
        self.intel: Any = None                 # 1.1.6: the Intelligence service, attached by the container
        self._blacklist: list[dict] = []

    # 1.1.8: what the engine remembers about chatters, as plain data (saved to Redis, restored after a restart)
    def export_state(self, now: float) -> dict[str, Any]:
        strikes = {k: list(dq) for k, dq in self._strikes.items() if dq and now - dq[-1] <= 86400}
        return {"rate": self.rate.export_state(now), "dups": self.dups.export_state(now), "sims": self.sims.export_state(now),
                "behavior": self.behavior.export_state(now), "strikes": dict(list(strikes.items())[:5000])}

    def import_state(self, data: dict[str, Any]) -> None:
        self.rate.import_state(data.get("rate") or {})
        self.dups.import_state(data.get("dups") or {})
        self.sims.import_state(data.get("sims") or [])
        self.behavior.import_state(data.get("behavior") or {})
        for k, ts in (data.get("strikes") or {}).items():
            self._strikes[str(k)] = deque((float(t) for t in ts), maxlen=50)

    def attach_intel(self, intel: Any) -> None:
        self.intel = intel
        intel.set_blacklist(self._blacklist)

    def set_blacklist(self, entries: list[dict]) -> None:
        self.matcher.rebuild(entries)
        self._blacklist = list(entries)
        if self.intel is not None:
            self.intel.set_blacklist(entries)

    def exempt(self, level: str) -> bool:
        c = self.cfg.get
        if level in split_csv(c("mod_exempt_levels")):
            return True
        if level == "regular" and c("mod_exempt_regulars"):
            return True
        if level == "member" and c("mod_exempt_members"):
            return True
        return False

    # --- strikes ---------------------------------------------------------------------------
    def strikes(self, key: str, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        dq = self._strikes.get(key)
        if not dq:
            return 0
        horizon = self.cfg.get("mod_strike_decay_minutes") * 60
        while dq and now - dq[0] > horizon:
            dq.popleft()
        return len(dq)

    def strikes_clear(self, key: str) -> None:
        self._strikes.pop(key, None)

    def add_strike(self, key: str, now: float | None = None) -> None:
        self._strikes.setdefault(key, deque(maxlen=50)).append(now if now is not None else time.time())

    # --- evaluation ------------------------------------------------------------------------
    def evaluate(self, m: ModInput, *, stateless: bool = False) -> Verdict:
        """Score one message. stateless=True only runs content rules and records nothing (used by the
        dashboard's 'test a message' box)."""
        c = self.cfg.get
        now = m.ts if m.ts is not None else time.time()
        if self.exempt(m.level):
            return Verdict(exempt=True)
        text = m.text or ""
        key = f"{m.platform}:{m.author_id}"
        signals: list[Signal] = []
        blacklist_ids: list[int] = []

        # ---- content signals -------------------------------------------------------------
        if c("mod_blacklist_enabled"):
            hits = self.matcher.scan(text)
            if hits:
                blacklist_ids = [h["id"] for h in hits if "id" in h]
                weight = max(int(h.get("weight") or c("mod_blacklist_weight")) for h in hits)
                signals.append(Signal("blacklist", min(100, weight), ", ".join(h["phrase"] for h in hits[:3])))

        if c("mod_links_enabled"):
            link = self._link_signal(m, text, now)
            if link:
                signals.append(link)

        if c("mod_caps_enabled") and len(text) >= c("mod_caps_min_length"):
            letters = [ch for ch in text if ch.isalpha()]
            if len(letters) >= 10:
                ratio = sum(1 for ch in letters if ch.isupper()) / len(letters)
                if ratio >= c("mod_caps_ratio"):
                    signals.append(Signal("caps", c("mod_caps_weight"), f"{ratio:.0%} capitals"))

        if c("mod_symbols_enabled") and len(text) >= c("mod_symbols_min_length"):
            body = [ch for ch in text if not ch.isspace()]
            if body:
                sym = sum(1 for ch in body if not ch.isalnum()) / len(body)
                if sym >= c("mod_symbols_ratio"):
                    signals.append(Signal("symbols", c("mod_symbols_weight"), f"{sym:.0%} symbols"))

        if c("mod_emotes_enabled"):
            n = _count_emotes(text)
            if n > c("mod_emotes_max"):
                signals.append(Signal("emotes", c("mod_emotes_weight"), f"{n} emotes"))

        if c("mod_repeat_enabled"):
            run = c("mod_repeat_char_run")
            words = text.lower().split()
            if re.search(r"(\S)\1{%d,}" % max(1, run - 1), text):
                signals.append(Signal("repetition", c("mod_repeat_weight"), f"character repeated {run}+ times"))
            elif len(words) >= 6 and 1 - len(set(words)) / len(words) >= c("mod_repeat_word_ratio"):
                signals.append(Signal("repetition", c("mod_repeat_weight"), "same words over and over"))

        if c("mod_length_enabled") and len(text) > c("mod_max_length"):
            signals.append(Signal("length", c("mod_length_weight"), f"{len(text)} characters"))

        # ---- behaviour signals -----------------------------------------------------------
        is_new = False
        if not stateless:
            info = self.behavior.observe(
                key, now, new_window=c("mod_new_chatter_seconds"), min_messages=c("mod_interval_min_messages"),
                max_cv=c("mod_interval_max_cv"), max_mean_gap=c("mod_interval_max_mean_gap"),
            )
            is_new = info.is_new

            if c("mod_rate_enabled"):
                window = c("mod_rate_window_seconds")
                count = self.rate.hit(key, now, window)
                limit = c("mod_rate_new_chatter_max") if is_new else c("mod_rate_max_messages")
                if count > limit:
                    signals.append(Signal("rate", c("mod_rate_weight"), f"{count} messages in {window}s"))

            if c("mod_dup_enabled"):
                repeats = self.dups.observe(key, text, now, c("mod_dup_window_seconds"))
                if repeats >= 2:
                    w = c("mod_dup_weight") if repeats >= 3 else int(c("mod_dup_weight") * 0.6)
                    signals.append(Signal("duplicate", w, f"same message x{repeats}"))

            if c("mod_sim_enabled"):
                accounts = self.sims.observe(
                    key, text, now, c("mod_sim_window_seconds"), c("mod_sim_max_distance"), c("mod_sim_min_length"),
                )
                if accounts >= c("mod_sim_min_accounts"):
                    signals.append(Signal("raid", c("mod_sim_weight"), f"{accounts} accounts posting similar text"))

            if c("mod_interval_enabled") and info.regular_interval:
                signals.append(Signal("timing", c("mod_interval_weight"),
                                      f"posts every {info.mean_gap:.1f}s like clockwork"))

        shadow: list[Signal] = []
        if self.intel is not None:
            permitted = self.permits.is_permitted(m.author_name, now) or self.permits.is_permitted(m.author_id, now)
            res = self.intel.analyse(m, text, now, stateless=stateless, existing=signals, is_new=is_new, permitted=permitted)
            signals.extend(res.live)
            shadow = res.shadow

        base = sum(s.weight for s in signals)
        if base > 0 and is_new:
            signals.append(Signal("new_chatter", c("mod_new_chatter_weight"), "first minutes in chat"))
        score = min(100, base + (c("mod_new_chatter_weight") if base > 0 and is_new else 0))

        action = "allow"
        if score >= c("mod_score_ban"):
            action = "ban"
        elif score >= c("mod_score_timeout"):
            action = "timeout"
        elif score >= c("mod_score_delete"):
            action = "delete"
        elif score >= c("mod_score_flag"):
            action = "flag"

        strikes = self.strikes(key, now)
        if action == "delete" and strikes >= c("mod_strikes_to_timeout"):
            action = "timeout"
        if action == "timeout" and strikes >= c("mod_strikes_to_ban") and c("mod_allow_ban_escalation"):
            action = "ban"

        duration = None
        if action == "timeout":
            ladder = [int(x) for x in split_csv(c("mod_timeout_ladder")) if x.isdigit()] or [300]
            # The first timeout is always the first rung; each strike beyond the threshold climbs one.
            rung = max(0, strikes - c("mod_strikes_to_timeout"))
            duration = ladder[min(rung, len(ladder) - 1)]
        for sig in signals:
            if not sig.why:
                sig.why = explain(sig.name, sig.detail)
        return Verdict(score=score, action=action, duration=duration, signals=signals, strikes=strikes,
                       blacklist_ids=blacklist_ids, shadow=shadow, confidence=_confidence(signals))

    # --- helpers ---------------------------------------------------------------------------
    def _link_signal(self, m: ModInput, text: str, now: float) -> Signal | None:
        disguised = _DOT_WORD.sub(".", text)
        found = _LINK.findall(disguised)
        if not found:
            return None
        if self.permits.is_permitted(m.author_name, now) or self.permits.is_permitted(m.author_id, now):
            return None
        allowed = [d.lower() for d in split_csv(self.cfg.get("mod_allowed_domains"))]
        bad = []
        for url in found:
            d = _domain(url)
            if not any(d == a or d.endswith("." + a) for a in allowed):
                bad.append(d)
        if not bad:
            return None
        return Signal("link", self.cfg.get("mod_links_weight"), ", ".join(bad[:2]))
