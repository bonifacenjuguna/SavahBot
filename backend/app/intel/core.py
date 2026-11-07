"""The intelligence layer: a set of independent detectors that add evidence to a message's score.

No AI model and no API. Everything is classic, explainable technique: weighted phrase packs (Aho-Corasick), typo
tolerance (BK-tree + edit distance), scam-intent scoring from word groups, a Naive Bayes classifier, BM25 similarity
to known spam, link analysis, impersonation checks, text-trick detection and a raid-wave tracker.

Safety rules that keep it from harming existing behaviour:
  * It only ADDS signals; the engine's own signals, weights and settings are untouched.
  * Each detector is Off, Shadow (logged but never scored) or Live, switchable at runtime.
  * Everything it adds is capped (intel_max_weight) so it can never ban on its own.
  * When your own blocked list already matched, intel adds only a small corroboration instead of stacking.
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Callable

from ..moderation.ahocorasick import AhoCorasick
from ..moderation.engine import ModInput, Signal
from ..moderation.normalize import fold
from ..utils import split_csv
from .bayes import BM25, NaiveBayes
from .links import LinkAnalyzer
from .match import FuzzyIndex, Hit, PhraseIndex, Rule
from .packs import Pack, effective_entries, load_builtin
from .textkit import (art_ratio, bidi_count, deep_normalize, invisible_count, jaro_winkler, mixed_script_words,
                      second_person, spaced_letters, tokens, zalgo)

logger = logging.getLogger("savahbot.intel")

RANK = {"off": 0, "shadow": 1, "live": 2}

# What the dashboard shows for each detector. Mode and strength live in the settings table (intel_<id>_mode / _scale).
DETECTORS: dict[str, dict[str, str]] = {
    "scam": {"title": "Scam phrases", "signal": "scam",
             "about": "Giveaway bait, crypto doublers, fake support, fake account warnings, wallet addresses and the way scam messages combine money, contact and urgency words.",
             "example": "double your bitcoin, send 0.1 btc and get 0.2 back, whatsapp me +254712345678"},
    "spam": {"title": "Spam and promotion", "signal": "spam",
             "about": "Sub-for-sub, 'check my channel', follower sellers, shop spam and adult bait.",
             "example": "sub4sub i will sub back, buy cheap followers dm me"},
    "abuse": {"title": "Abuse (profanity and insults)", "signal": "abuse",
              "about": "Profanity and insults (stronger when aimed at someone). Gameplay talk like 'kill streak' is protected by the safe phrases. Shadow by default.",
              "example": "you are such an idiot, what the fuck"},
    "harassment": {"title": "Threats and harassment", "signal": "harassment",
                   "about": "Death wishes, 'I know where you live', doxxing, swatting and DDoS threats. Live by default, because these should never wait.",
                   "example": "kys, i know where you live"},
    "typo": {"title": "Typo and disguise matching", "signal": "typo",
             "about": "Catches blocked and known-bad phrases written with typos or stretched letters, such as 'frree robus'. Short words must match exactly.",
             "example": "frree robus click my profile"},
    "link_risk": {"title": "Link intelligence", "signal": "link_risk",
                  "about": "Judges where a link really goes: look-alike brand domains, shorteners, IP links, punycode, risky endings and threat-list domains.",
                  "example": "claim here youtub3.com/verify or bit.ly/abc"},
    "impersonation": {"title": "Impersonation guard", "signal": "impersonation",
                      "about": "Account names that copy the streamer or pose as staff, and messages that claim to be the admin.",
                      "example": "Display name 'Official YouTube Support'"},
    "obfuscation": {"title": "Text tricks", "signal": "obfuscation",
                    "about": "Zalgo text, invisible characters, mixed alphabets inside one word, symbol art and spaced-out letters.",
                    "example": "fr\u0435e r\u043ebux (some letters are Cyrillic)"},
    "bot_like": {"title": "Bot-like accounts", "signal": "bot_like",
                 "about": "Names like user83749201 or random letter mashes. A weak hint that only matters next to other evidence.",
                 "example": "Display name 'xkqzvtrw9921874'"},
    "intent": {"title": "Spam-likeness (Naive Bayes)", "signal": "intent",
               "about": "A word-statistics model trained on example spam and normal chat. It also learns from your approve and reject decisions.",
               "example": "guaranteed daily profit join vip group now"},
    "known_spam": {"title": "Looks like known spam (BM25)", "signal": "known_spam",
                   "about": "Finds the known spam message a new message most resembles, even when a few words are changed.",
                   "example": "claim your free gift card at the link below"},
    "raid_wave": {"title": "Raid wave", "signal": "raid_wave",
                  "about": "Spots a sudden wave of brand-new accounts and adds weight to suspicious messages from new accounts while it lasts.",
                  "example": "Triggered by many first-time chatters within seconds"},
}

_WALLET = [
    (re.compile(r"\b0x[a-fA-F0-9]{40}\b"), "an Ethereum wallet address"),
    (re.compile(r"\bbc1[ac-hj-np-z02-9]{25,62}\b"), "a Bitcoin wallet address"),
    (re.compile(r"\b[13](?=[a-km-zA-HJ-NP-Z1-9]*\d)(?=[a-km-zA-HJ-NP-Z1-9]*[a-zA-Z])[a-km-zA-HJ-NP-Z1-9]{25,34}\b"), "a Bitcoin wallet address"),
    (re.compile(r"\bT(?=[1-9A-HJ-NP-Za-km-z]*\d)(?=[1-9A-HJ-NP-Za-km-z]*[a-z])[1-9A-HJ-NP-Za-km-z]{33}\b"), "a Tron wallet address"),
]
_WARNING = re.compile(
    r"(?i)\b(don'?t|do not|never|beware|careful|watch out|stay away|ignore|report|reported|scammer|scammers|scam bot|"
    r"bots?|fake|phishing|mods? ban|ban (?:him|her|them|that|this)|that'?s a scam|this is a scam|it'?s a scam|is a scam)\b")
_QUESTION = re.compile(r"(?i)^\s*(is|are|was|were|does|do|did|can|could|why|what|who|how|anyone|any1|has|have)\b")
_PHONE = re.compile(r"\+\d{2,3}[\s\-]?\d{2,3}[\s\-]?\d{3}[\s\-]?\d{3,4}|\b0[17]\d{2}[\s\-]?\d{3}[\s\-]?\d{3}\b")
# collapsed like the normaliser collapses repeated letters ("support" -> "suport"), so they compare equal
_ROLE_WORDS = tuple(re.sub(r"(.)\1+", r"\1", w) for w in ("support", "official", "admin", "mod", "team", "staff", "giveaway", "help", "verified", "service"))
_BOT_NAME = re.compile(r"(?i)^@?(?:user[-_]?\d{6,}|[a-z]{3,}\d{6,}|[a-z]+[-_]\d{6,})$")


@dataclass
class IntelResult:
    live: list[Signal] = field(default_factory=list)
    shadow: list[Signal] = field(default_factory=list)


@dataclass
class _Cand:
    det: str
    name: str
    weight: float
    mode: str
    detail: str = ""
    why: str = ""
    capped: bool = False   # discounted by context (a question or a warning): the merged total is capped too


_CTX_CAPPED = ("warning about a scam", "asked as a question")


class Intel:
    def __init__(self, cfg: Any, names_fn: Callable[[], list[str]] | None = None) -> None:
        self.cfg = cfg
        self.names_fn = names_fn or (lambda: [])
        self.packs: dict[str, Pack] = load_builtin()
        self.pack_state: dict[str, dict[str, Any]] = {}
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.blacklist: list[dict[str, Any]] = []
        self.learned_scale: dict[str, float] = {}
        self.learned_nb = NaiveBayes()
        self.learned_examples: list[str] = []
        # compiled structures
        self.index = PhraseIndex()
        self.fuzzy = FuzzyIndex()
        self.names_index = PhraseIndex()
        self.safe = AhoCorasick()
        self.safe_count = 0
        self.links = LinkAnalyzer()
        self.facets: list[dict[str, Any]] = []
        self.nb = NaiveBayes()
        self.bm25 = BM25()
        self._example_text: dict[Any, str] = {}
        self.build_ms = 0.0
        # live statistics
        self.pending: Counter[str] = Counter()
        self.recent_shadow: deque[dict[str, Any]] = deque(maxlen=40)
        self._new_accounts: deque[tuple[float, str]] = deque(maxlen=400)
        self._seen_new: set[str] = set()
        self.wave_until = 0.0
        self.wave_started = False
        self.waves_seen = 0
        self._force = False  # probe(): treat every detector that is not off as live
        self._base_nb = NaiveBayes()
        self._base_docs: list[tuple[Any, str]] = []
        self.rebuild()

    # ------------------------------------------------------------------ configuration
    def _m(self, mode: str) -> str:
        return "live" if self._force and mode != "off" else mode

    def mode_of(self, det: str) -> str:
        m = str(self.cfg.get(f"intel_{det}_mode"))
        return self._m(m if m in RANK else "off")

    def scale_of(self, det: str) -> float:
        return float(self.cfg.get(f"intel_{det}_scale")) * self.learned_scale.get(det, 1.0)

    def pack_mode(self, pack: Pack) -> str:
        langs = {x.strip().lower() for x in split_csv(self.cfg.get("intel_languages"))} or {"en"}
        if pack.lang != "any" and pack.lang not in langs:
            return "off"
        mode = self.pack_state.get(pack.id, {}).get("mode") or pack.default_mode
        return mode if mode in RANK else "live"

    def pack_scale(self, pack_id: str) -> float:
        return float(self.pack_state.get(pack_id, {}).get("scale") or 1.0)

    def set_blacklist(self, entries: list[dict[str, Any]]) -> None:
        self.blacklist = list(entries)
        self.rebuild()

    def load_state(self, pack_state: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> None:
        self.pack_state = pack_state
        by_pack: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            by_pack.setdefault(r["pack_id"], []).append(r)
        self.rows = by_pack
        self.rebuild()

    def set_learned(self, nb: NaiveBayes | None = None, examples: list[str] | None = None,
                    scales: dict[str, float] | None = None) -> None:
        """What was learned from the owner's decisions. Cheap: only the statistical models are rebuilt."""
        if nb is not None:
            self.learned_nb = nb
        if examples is not None:
            self.learned_examples = list(examples)
        if scales is not None:
            self.learned_scale = dict(scales)
        self._rebuild_models()

    # ------------------------------------------------------------------ building
    def rebuild(self) -> None:
        t0 = time.perf_counter()
        rules: list[Rule] = []
        name_rules: list[Rule] = []
        link_packs: list[tuple[Pack, list[Any]]] = []
        safe_phrases: list[str] = []
        self.facets = []
        base_nb = NaiveBayes()
        spam_docs: list[tuple[Any, str]] = []
        for pack in self.packs.values():
            mode = self.pack_mode(pack)
            if mode == "off":
                continue
            entries = effective_entries(pack, self.rows.get(pack.id, []))
            if pack.kind == "phrases":
                if pack.category == "safe":
                    safe_phrases += [e.phrase for e in entries if not e.regex]
                    continue
                target = name_rules if pack.role == "name" else rules
                for e in entries:
                    target.append(Rule(pack=pack.id, signal=pack.signal, phrase=e.phrase, weight=e.weight or pack.weight,
                                       regex=e.regex, fuzzy=pack.fuzzy and e.source != "feed", needs_target=pack.needs_target,
                                       lang=pack.lang, source=e.source, mode=mode))
            elif pack.kind in ("domains", "tlds", "words", "domain_regex"):
                link_packs.append((pack, entries))
            elif pack.kind == "facets":
                self.facets.append(self._compile_facets(pack, mode))
            elif pack.kind == "corpus":
                label = pack.payload["label"]
                for i, ex in enumerate(pack.payload["examples"]):
                    base_nb.train(ex, label)
                    if label == "spam":
                        spam_docs.append((("corpus", pack.id, i), ex))
        bl_rules = []
        for e in self.blacklist:
            if e.get("enabled", True) and not e.get("is_regex") and (e.get("phrase") or "").strip():
                bl_rules.append(Rule(pack="blacklist", signal="blacklist", phrase=e["phrase"].strip(),
                                     weight=int(e.get("weight") or self.cfg.get("mod_blacklist_weight")),
                                     fuzzy=True, source="blacklist", mode="live"))
        self.index = PhraseIndex().build(rules)
        self.names_index = PhraseIndex().build(name_rules)
        compiled_bl = PhraseIndex().build(bl_rules)
        self.fuzzy = FuzzyIndex().build([*self.index.rules, *compiled_bl.rules])
        safe = AhoCorasick()
        n = 0
        for ph in safe_phrases:
            p = deep_normalize(ph)
            if p:
                safe.add(f" {p} " if len(p.replace(" ", "")) <= 4 else p, p)
                n += 1
        safe.build()
        self.safe, self.safe_count = safe, n
        protected = [x.strip() for x in split_csv(self.cfg.get("intel_protected_domains"))]
        allowed = [x.strip() for x in split_csv(self.cfg.get("mod_allowed_domains"))]
        self.links = LinkAnalyzer().build(link_packs, extra_protected=protected, extra_safe=allowed)
        self._base_nb, self._base_docs = base_nb, spam_docs
        self._rebuild_models()
        self.build_ms = (time.perf_counter() - t0) * 1000

    def _rebuild_models(self) -> None:
        """Naive Bayes and BM25: the built-in examples plus what was learned from approve/reject decisions."""
        nb = NaiveBayes()
        nb.spam.update(self._base_nb.spam)
        nb.ham.update(self._base_nb.ham)
        nb.docs = dict(self._base_nb.docs)
        nb.spam.update(self.learned_nb.spam)
        nb.ham.update(self.learned_nb.ham)
        nb.docs["spam"] += self.learned_nb.docs["spam"]
        nb.docs["ham"] += self.learned_nb.docs["ham"]
        self.nb = nb
        docs = list(self._base_docs) + [(("learned", i), ex) for i, ex in enumerate(self.learned_examples)]
        self._example_text = dict(docs)
        self.bm25 = BM25().build(docs)

    @staticmethod
    def _compile_facets(pack: Pack, mode: str) -> dict[str, Any]:
        groups: dict[str, tuple[set[str], list[re.Pattern[str]]]] = {}
        for name, words in pack.payload["facets"].items():
            toks, rxs = set(), []
            for w in words:
                if w.startswith("re:"):
                    rxs.append(re.compile(w[3:], re.I))
                else:
                    toks.add(deep_normalize(w))
            groups[name] = (toks, rxs)
        return {"pack": pack, "mode": mode, "groups": groups, "anchors": set(pack.payload.get("anchors", [])),
                "min_groups": int(pack.payload.get("min_groups", 2))}

    # ------------------------------------------------------------------ helpers used while scoring
    def _safe_found(self, text: str) -> list[str]:
        if not self.safe_count:
            return []
        return list({p for _, _, p in self.safe.search(f" {deep_normalize(text)} ")})

    @staticmethod
    def _is_safe(matched: str, safe_found: list[str]) -> bool:
        m = deep_normalize(matched)
        return bool(m) and any(m in s for s in safe_found)

    def _concrete(self, text: str) -> bool:
        """True when the message holds something actionable: a link, a phone number or a wallet address."""
        return bool(self.links.extract(text)) or bool(_PHONE.search(text)) or any(rx.search(text) for rx, _ in _WALLET)

    @staticmethod
    def _discount(w: float, factor: float, note: str) -> float:
        """A question or a warning about a scam must not be able to cause a flag on its own, even from a brand-new account
        (whose small new-chatter bonus is added on top), so its weight is also capped."""
        w *= factor
        return min(w, 12.0) if factor < 1 and note != "quoted" else w

    def _context_factor(self, text: str, matched_phrase: str, concrete: bool) -> tuple[float, str]:
        """Same words, different meaning: questions and warnings about a scam are not scams."""
        if not concrete and _WARNING.search(text):
            return 0.3, "warning about a scam"
        if not concrete and text.rstrip().endswith("?") and _QUESTION.match(text):
            return 0.4, "asked as a question"
        if matched_phrase and re.search(r"[\"\u201c\u00ab][^\"\u201d\u00bb]{0,80}" + re.escape(matched_phrase) + r"[^\"\u201d\u00bb]{0,80}[\"\u201d\u00bb]", text, re.I):
            return 0.5, "quoted"
        return 1.0, ""

    def _facet_score(self, text: str, folded: str, f: dict[str, Any]) -> tuple[int, list[str]]:
        words = set(deep_normalize(text).split())
        hit: list[str] = []
        for name, (toks, rxs) in f["groups"].items():
            if words & toks or any(rx.search(folded) for rx in rxs):
                hit.append(name)
        if len(hit) < f["min_groups"] or not (set(hit) & f["anchors"]):
            return 0, hit
        base = {2: 25, 3: 45}.get(len(hit), 60)
        pairs = [{"money", "contact"}, {"giveaway", "ask"}, {"money", "trust"}, {"money", "giveaway"}]
        if any(p <= set(hit) for p in pairs):
            base += 10
        return min(base, f["pack"].weight), hit

    # ------------------------------------------------------------------ the pipeline
    def analyse(self, m: ModInput, text: str, now: float, *, stateless: bool = False, existing: list[Signal] | None = None,
                is_new: bool = False, permitted: bool = False) -> IntelResult:
        res = IntelResult()
        c = self.cfg.get
        if not c("intel_enabled") or not (text or "").strip():
            return res
        text = text[:600]
        folded = fold(text)
        existing = existing or []
        has_blacklist = any(s.name == "blacklist" for s in existing)
        safe_found = self._safe_found(text) if c("intel_safe_enabled") else []
        use_context = bool(c("intel_context_enabled"))
        concrete = self._concrete(text) if use_context else False
        cands: list[_Cand] = []

        # ---- phrase packs (scam / spam / abuse / impersonation) --------------------------------
        exact = self.index.scan(text, folded)
        groups: dict[tuple[str, str], list[tuple[float, Hit, str]]] = {}

        def feed(h: Hit, base: float, det: str, mode: str) -> None:
            if self._is_safe(h.matched or h.rule.phrase, safe_found):
                return
            w = base * self.pack_scale(h.rule.pack) * self.scale_of(det)
            if h.rule.needs_target:
                w *= 1.3 if second_person(text) else 0.6
            note = ""
            if use_context and h.rule.source != "blacklist":
                f, note = self._context_factor(text, h.rule.phrase, concrete)
                w = self._discount(w, f, note)
            if has_blacklist and h.rule.source != "blacklist":
                w = min(15.0, w * 0.25)
                note = note or "also on your blocked list"
            if w >= 1:
                groups.setdefault((det, mode), []).append((w, h, note))

        for h in exact:
            det = h.rule.signal
            mode = _min_mode(self.mode_of(det), self._m(h.rule.mode))
            if mode != "off":
                feed(h, h.rule.weight, det, mode)

        # ---- typo / disguise matching ------------------------------------------------------------
        if self.mode_of("typo") != "off" and not has_blacklist and not exact:
            for h in self.fuzzy.scan(text, skip={id(x.rule) for x in exact}):
                mode = _min_mode(self.mode_of("typo"), self._m(h.rule.mode))
                if mode != "off":
                    feed(h, h.rule.weight * 0.85, "typo", mode)

        for (det, mode), items in groups.items():
            items.sort(key=lambda t: -t[0])
            weight = min(100.0, items[0][0] + 0.25 * sum(w for w, _, _ in items[1:]))
            names = []
            for _, h, _ in items[:3]:
                label = h.rule.phrase if not h.rule.regex else (h.matched or "pattern")
                names.append(label[:40] + (f" (typed as '{h.matched[:30]}')" if h.kind == "fuzzy" else ""))
            packs_hit = []
            for _, h, _ in items[:3]:
                t = self.packs[h.rule.pack].title if h.rule.pack in self.packs else "your blocked list"
                if t not in packs_hit:
                    packs_hit.append(t)
            notes = {n for _, _, n in items if n}
            capped = all(n in _CTX_CAPPED for _, _, n in items)
            why = f"Matches {', '.join(packs_hit)}: {', '.join(names)}" + (f" ({'; '.join(sorted(notes))})" if notes else "")
            cands.append(_Cand(det, det, weight, mode, ", ".join(names), why, capped))

        # ---- scam intent (word groups) and wallet addresses ---------------------------------------
        scam_mode = self.mode_of("scam")
        if scam_mode != "off":
            for f in self.facets:
                mode = _min_mode(scam_mode, self._m(f["mode"]))
                if mode == "off":
                    continue
                w, hit = self._facet_score(text, folded, f)
                if w:
                    factor, note = self._context_factor(text, "", concrete) if use_context else (1.0, "")
                    w = self._discount(w * self.scale_of("scam") * self.pack_scale(f["pack"].id), factor, note)
                    if has_blacklist:
                        w = min(15.0, w * 0.25)
                    if w >= 1:
                        cands.append(_Cand("scam", "scam", w, mode, " + ".join(hit),
                                           f"Combines {', '.join(hit)} words, the way scam messages are built" + (f" ({note})" if note else ""),
                                           note in _CTX_CAPPED))
            for rx, label in _WALLET:
                if rx.search(text):
                    w = 55.0 * self.scale_of("scam")
                    if has_blacklist:
                        w = min(15.0, w * 0.25)
                    cands.append(_Cand("scam", "scam", w, scam_mode, label, f"Posted {label}; real chatters rarely do"))
                    break

        # ---- link intelligence ------------------------------------------------------------------
        if self.mode_of("link_risk") != "off" and not permitted:
            found = self.links.analyse(text, allowed=split_csv(c("mod_allowed_domains")))
            if found:
                top = max(found, key=lambda f: f.weight)
                cands.append(_Cand("link_risk", "link_risk", top.weight * self.scale_of("link_risk"), self.mode_of("link_risk"),
                                   ", ".join(f.host for f in found[:2]), top.why))

        # ---- impersonation (the account name; message claims already came through the phrase packs) -----
        if self.mode_of("impersonation") != "off":
            imp = self._impersonation(m)
            if imp:
                cands.append(_Cand("impersonation", "impersonation", imp[0] * self.scale_of("impersonation"),
                                   self.mode_of("impersonation"), imp[1], imp[2]))

        # ---- text tricks -------------------------------------------------------------------------
        if self.mode_of("obfuscation") != "off":
            ob = self._obfuscation(text)
            if ob:
                cands.append(_Cand("obfuscation", "obfuscation", ob[0] * self.scale_of("obfuscation"),
                                   self.mode_of("obfuscation"), ob[1], "Uses text tricks to dodge filters: " + ob[1]))

        # ---- bot-like account -----------------------------------------------------------------------
        if self.mode_of("bot_like") != "off":
            bl = self._bot_like(m, text)
            if bl:
                cands.append(_Cand("bot_like", "bot_like", bl[0] * self.scale_of("bot_like"), self.mode_of("bot_like"), bl[1],
                                   "The account looks automated: " + bl[1]))

        # ---- statistical detectors -------------------------------------------------------------------
        if not has_blacklist and len(tokens(text)) >= int(c("intel_intent_min_tokens")):
            if self.mode_of("intent") != "off" and self.nb.trained:
                p, words = self.nb.predict(text)
                w = 30 if p >= 0.985 else 20 if p >= 0.95 else 10 if p >= 0.9 else 0
                if w:
                    factor, note = self._context_factor(text, "", concrete) if use_context else (1.0, "")
                    w = self._discount(w * self.scale_of("intent"), factor, note)
                    if w >= 1:
                        cands.append(_Cand("intent", "intent", w, self.mode_of("intent"), f"{p:.0%} spam-like ({', '.join(words)})",
                                           f"Its words are {p:.0%} like spam in the training examples; strongest: {', '.join(words)}"
                                           + (f" ({note})" if note else ""), note in _CTX_CAPPED))
            if self.mode_of("known_spam") != "off" and len(self.bm25):
                q = set(tokens(text))
                for _score, key in self.bm25.search(text, top=3):
                    d = set(self.bm25.words(key))
                    shared = len(q & d)
                    sim = shared / max(1, len(q | d))
                    if shared >= 3 and sim >= 0.6:
                        ex = self._example_text.get(key, "")
                        cands.append(_Cand("known_spam", "known_spam", 35 * (0.5 + sim / 2) * self.scale_of("known_spam"),
                                           self.mode_of("known_spam"), f"{sim:.0%} the same as \u201c{ex[:50]}\u201d",
                                           f"{sim:.0%} of its words match a known spam message: \u201c{ex[:70]}\u201d"))
                        break

        # ---- merge, cap, split live / shadow ----------------------------------------------------------------
        cands = _merge(cands)
        live = [x for x in cands if x.mode == "live" and x.weight >= 1]
        shadow = [x for x in cands if x.mode == "shadow" and x.weight >= 1]
        cap = float(c("intel_max_weight"))
        total = sum(x.weight for x in live)
        if total > cap > 0:
            for x in live:
                x.weight *= cap / total
        base_total = sum(s.weight for s in existing) + sum(x.weight for x in live)

        # ---- raid wave (stateful) ---------------------------------------------------------------------------
        if not stateless:
            wave = self._wave(m, now, is_new)
            if wave and is_new and base_total > 0 and self.mode_of("raid_wave") != "off":
                w = float(c("intel_wave_weight")) * self.scale_of("raid_wave")
                (live if self.mode_of("raid_wave") == "live" else shadow).append(
                    _Cand("raid_wave", "raid_wave", w, self.mode_of("raid_wave"), "wave of new accounts"))

        res.live = [Signal(x.name, max(1, round(x.weight)), x.detail, x.why) for x in live]
        res.shadow = [Signal(x.name, max(1, round(x.weight)), x.detail, x.why) for x in shadow]
        if not stateless:
            for x in live:
                self.pending[f"live:{x.det}"] += 1
            for x in shadow:
                self.pending[f"shadow:{x.det}"] += 1
                self.recent_shadow.appendleft({"ts": now, "text": text[:140], "detector": x.det, "weight": round(x.weight),
                                               "detail": x.detail, "author": m.author_name})
        return res

    # ------------------------------------------------------------------ individual detectors
    def _protected_names(self) -> list[tuple[str, str]]:
        names = [*split_csv(self.cfg.get("intel_protected_names")), *self.names_fn()]
        out, seen = [], set()
        for n in names:
            flat = re.sub(r"[^a-z0-9]", "", deep_normalize(n))
            if len(flat) >= 3 and flat not in seen:
                seen.add(flat)
                out.append((n.strip(), flat))
        return out

    def _impersonation(self, m: ModInput) -> tuple[float, str, str] | None:
        name = (m.author_name or "").strip()
        if not name:
            return None
        flat = re.sub(r"[^a-z0-9]", "", deep_normalize(name))
        best: tuple[float, str, str] | None = None

        def offer(w: float, detail: str, why: str) -> None:
            nonlocal best
            if best is None or w > best[0]:
                best = (w, detail, why)

        for shown, p in self._protected_names():
            if flat == p:
                offer(60, f"same name as {shown}", f"The account name is the same as {shown}")
            elif len(p) >= 4 and p in flat:
                rest = flat.replace(p, "", 1)
                if any(r in rest for r in _ROLE_WORDS):
                    offer(55, f"{shown} + a staff word", f"The name copies {shown} and adds a staff word")
                elif 0 < len(rest) <= 3 and not rest.isdigit():
                    offer(25, f"almost {shown}", f"The name is almost {shown}")
            elif len(p) >= 5 and abs(len(flat) - len(p)) <= 2 and jaro_winkler(flat, p) >= 0.94:
                offer(35, f"very close to {shown}", f"The name is very close to {shown} (possible look-alike)")
        for h in self.names_index.scan(name):
            offer(float(h.rule.weight), f"name contains '{h.rule.phrase}'", f"The account name sounds like staff: '{h.rule.phrase}'")
        return best

    @staticmethod
    def _obfuscation(text: str) -> tuple[float, str] | None:
        w, why = 0.0, []
        marks, letters = zalgo(text)
        if marks >= 6 and marks / max(1, letters) >= 0.3:
            w += 30
            why.append("stacked accent marks (zalgo)")
        if invisible_count(text) >= 3:
            w += 25
            why.append("hidden characters")
        if bidi_count(text):
            w += 40
            why.append("text-direction tricks")
        mixed = mixed_script_words(text)
        if mixed:
            w += 35
            why.append(f"mixed alphabets in one word ({mixed[0]})")
        if len(text) >= 12 and art_ratio(text) >= 0.6:
            w += 30
            why.append("symbol art")
        if spaced_letters(text) >= 8:
            w += 20
            why.append("letters spaced apart")
        return (min(60.0, w), ", ".join(why)) if w else None

    @staticmethod
    def _bot_like(m: ModInput, text: str) -> tuple[float, str] | None:
        name = (m.author_name or "").strip()
        w, why = 0.0, []
        if _BOT_NAME.match(name):
            w += 10
            why.append("name ends in a long number")
        digits = sum(ch.isdigit() for ch in name)
        if len(name) >= 8 and digits / len(name) >= 0.5:
            w += 6
            why.append("mostly digits")
        letters = re.sub(r"[^a-z]", "", name.lower())
        if len(letters) >= 8 and not re.search(r"[aeiouy]", letters):
            w += 8
            why.append("no vowels")
        if text.lstrip().startswith("@") and re.search(r"https?://|www\.", text, re.I):
            w += 5
            why.append("mentions someone and drops a link")
        return (min(15.0, w), ", ".join(why)) if w else None

    def _wave(self, m: ModInput, now: float, is_new: bool) -> bool:
        key = f"{m.platform}:{m.author_id}"
        if is_new and key not in self._seen_new:
            self._seen_new.add(key)
            if len(self._seen_new) > 2000:
                self._seen_new = set(list(self._seen_new)[-1000:])
            self._new_accounts.append((now, key))
            window = float(self.cfg.get("intel_wave_window_seconds"))
            while self._new_accounts and now - self._new_accounts[0][0] > window:
                self._new_accounts.popleft()
            if len(self._new_accounts) >= int(self.cfg.get("intel_wave_accounts")) and now >= self.wave_until:
                self.waves_seen += 1
                self.wave_started = True
                self.wave_until = now + float(self.cfg.get("intel_wave_duration_seconds"))
        return now < self.wave_until

    def probe(self, text: str, author: str = "tester") -> dict[str, int]:
        """Which detectors would react to this text if every active detector were live? Stateless."""
        self._force = True
        try:
            res = self.analyse(ModInput("probe", "probe", author, text, "everyone", 0.0), text, 0.0, stateless=True)
        finally:
            self._force = False
        return {sig.name: sig.weight for sig in res.live}

    def pop_wave_started(self) -> bool:
        started, self.wave_started = self.wave_started, False
        return started

    # ------------------------------------------------------------------ views
    def trace(self, text: str, author: str = "tester") -> dict[str, Any]:
        """Every raw match with its pack, before context, caps or modes: for the knowledge test lab."""
        folded = fold(text)
        hits = self.index.scan(text, folded)
        exact_ids = {id(h.rule) for h in hits}
        typo = self.fuzzy.scan(text, skip=exact_ids)
        safe = self._safe_found(text)
        out = [{"pack": h.rule.pack, "pack_title": self.packs[h.rule.pack].title if h.rule.pack in self.packs else "Blocked phrases",
                "phrase": h.rule.phrase, "kind": h.kind, "weight": h.rule.weight, "typos": h.typos,
                "protected_by_safe_phrase": self._is_safe(h.matched or h.rule.phrase, safe)} for h in [*hits, *typo]]
        facets = []
        for f in self.facets:
            w, hit = self._facet_score(text, folded, f)
            facets.append({"pack": f["pack"].id, "groups": hit, "weight": w})
        links = [{"host": f.host, "weight": f.weight, "reasons": f.reasons} for f in self.links.analyse(text)]
        p, words = self.nb.predict(text) if self.nb.trained else (0.5, [])
        return {"matches": out, "facets": facets, "links": links, "safe_phrases_found": safe,
                "bayes": {"spam_probability": round(p, 3), "words": words},
                "normalised": deep_normalize(text)}

    def status(self) -> dict[str, Any]:
        live_packs = sum(1 for p in self.packs.values() if self.pack_mode(p) != "off")
        return {
            "enabled": bool(self.cfg.get("intel_enabled")),
            "packs_total": len(self.packs), "packs_active": live_packs,
            "rules": self.index.size, "typo_rules": self.fuzzy.size, "domains": len(self.links.scam),
            "safe_phrases": self.safe_count, "examples": len(self._example_text),
            "model_ready": self.nb.trained, "build_ms": round(self.build_ms, 1),
            "wave_active": time.time() < self.wave_until or False, "waves_seen": self.waves_seen,
            "shadow_recent": len(self.recent_shadow),
        }


def _merge(cands: list[_Cand]) -> list[_Cand]:
    """One signal per kind and mode: the strongest evidence plus a quarter of the rest (diminishing returns)."""
    by: dict[tuple[str, str], list[_Cand]] = {}
    for x in cands:
        by.setdefault((x.name, x.mode), []).append(x)
    out: list[_Cand] = []
    for (name, mode), items in by.items():
        items.sort(key=lambda x: -x.weight)
        weight = min(100.0, items[0].weight + 0.25 * sum(i.weight for i in items[1:]))
        if all(i.capped for i in items):
            weight = min(weight, 12.0)
        detail = "; ".join(dict.fromkeys(i.detail for i in items if i.detail))[:140]
        why = items[0].why + (f" (and {len(items) - 1} more sign{'s' if len(items) > 2 else ''})" if len(items) > 1 else "")
        out.append(_Cand(items[0].det, name, weight, mode, detail, why, all(i.capped for i in items)))
    return out


def _min_mode(a: str, b: str) -> str:
    return a if RANK[a] <= RANK[b] else b
