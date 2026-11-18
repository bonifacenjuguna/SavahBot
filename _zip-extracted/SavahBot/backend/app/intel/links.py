"""Link intelligence: judges where a link really goes, not just that it is a link.

Looks at look-alike brand domains (youtub3.com), brand names inside other domains (paypal-secure.net), punycode,
IP addresses, the user@host trick, URL shorteners, messenger invites, risky endings, bait words in the address
and domains from threat lists. Standard library only.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..moderation.engine import _DOT_WORD, _LINK
from .packs import Entry, Pack
from .textkit import deep_normalize, levenshtein, mixed_script_words

_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "go", "or", "ne", "gov", "edu", "sch", "me", "mil"}
_SCHEME = re.compile(r"(?i)^[a-z][a-z0-9+.\-]*://")
_DIGIT_L = str.maketrans({"1": "l", "0": "o", "5": "s", "3": "e", "4": "a", "7": "t", "8": "b"})


@dataclass
class LinkFinding:
    host: str
    weight: int
    reasons: list[str] = field(default_factory=list)

    @property
    def why(self) -> str:
        return f"{self.host}: " + "; ".join(self.reasons)


def registrable(host: str) -> str:
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _suffixes(host: str) -> Iterable[str]:
    parts = host.split(".")
    for i in range(len(parts) - 1):
        yield ".".join(parts[i:])


def host_of(url: str) -> tuple[str, bool]:
    """(host, had_userinfo). Strips scheme, credentials, port, path and a leading www."""
    u = _SCHEME.sub("", url.strip().strip("<>()[]{}\"'.,;!?"))
    netloc = re.split(r"[/?#]", u, maxsplit=1)[0]
    userinfo = "@" in netloc
    netloc = netloc.rsplit("@", 1)[-1]
    host = netloc.split(":")[0].lower().strip(".")
    return (host[4:] if host.startswith("www.") else host), userinfo


class LinkAnalyzer:
    def __init__(self) -> None:
        self.shorteners: dict[str, int] = {}
        self.messengers: dict[str, int] = {}
        self.hubs: dict[str, int] = {}
        self.tlds: dict[str, int] = {}
        self.protected: list[tuple[str, str, str]] = []  # (registrable domain, label, normalised label)
        self.safe: set[str] = set()
        self.scam: dict[str, int] = {}
        self.patterns: list[tuple[re.Pattern[str], int]] = []
        self.bait: dict[str, int] = {}
        self._extra_rx: re.Pattern[str] | None = None
        self._known_rx: re.Pattern[str] | None = None
        self.size = 0

    def build(self, packs: Iterable[tuple[Pack, list[Entry]]], extra_protected: Iterable[str] = (),
              extra_safe: Iterable[str] = ()) -> "LinkAnalyzer":
        self.shorteners, self.messengers, self.hubs, self.tlds = {}, {}, {}, {}
        self.protected, self.safe, self.scam, self.patterns, self.bait = [], set(), {}, [], {}
        for pack, entries in packs:
            for e in entries:
                w = e.weight or pack.weight
                p = e.phrase.strip().lower()
                if pack.role == "shortener":
                    self.shorteners[p] = w
                elif pack.role == "messenger":
                    self.messengers[p] = w
                elif pack.role == "hub":
                    self.hubs[p] = w
                elif pack.role == "tld":
                    self.tlds[p.lstrip(".")] = w
                elif pack.role == "protected":
                    self._add_protected(p)
                elif pack.role == "never_block":
                    self.safe.add(p)
                elif pack.role == "scam":
                    self.scam[p] = w
                elif pack.role == "pattern" and e.regex:
                    try:
                        self.patterns.append((re.compile(e.phrase, re.I), w))
                    except re.error:
                        pass
                elif pack.role == "bait":
                    self.bait[p] = w
        for d in extra_protected:
            self._add_protected(d.strip().lower())
        for d in extra_safe:
            if d.strip():
                self.safe.add(d.strip().lower())
        names = sorted(self.tlds, key=len, reverse=True)
        self._extra_rx = re.compile(r"(?i)\b(?:[a-z0-9][a-z0-9\-]{0,62}\.)+(?:%s)\b(?:/[^\s]*)?" % "|".join(map(re.escape, names))) if names else None
        known = sorted({*self.shorteners, *self.messengers, *self.hubs}, key=len, reverse=True)
        self._known_rx = re.compile(r"(?i)(?<![\w.\-@])(?:%s)(?![\w\-])(?:/[^\s]*)?" % "|".join(map(re.escape, known))) if known else None
        self.size = len(self.shorteners) + len(self.messengers) + len(self.scam) + len(self.protected) + len(self.patterns)
        return self

    def _add_protected(self, domain: str) -> None:
        domain = re.sub(r"^https?://", "", domain).split("/")[0]
        if domain.startswith("www."):
            domain = domain[4:]
        if "." not in domain:
            return
        label = registrable(domain).split(".")[0]
        self.protected.append((registrable(domain), label, deep_normalize(label.replace("-", ""))))

    # ---- extraction --------------------------------------------------------------------
    def extract(self, text: str) -> list[str]:
        disguised = _DOT_WORD.sub(".", text or "")
        found = list(_LINK.findall(disguised))
        if self._extra_rx:
            found += [m.group(0) for m in self._extra_rx.finditer(disguised)]
        if self._known_rx:
            found += [m.group(0) for m in self._known_rx.finditer(disguised)]
        found += re.findall(r"(?i)\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?:/\S*)?", disguised)
        seen, out = set(), []
        for u in found:
            if u.lower() not in seen:
                seen.add(u.lower())
                out.append(u)
        return out[:6]

    # ---- judgement ---------------------------------------------------------------------
    def _is_safe(self, host: str, allowed: list[str]) -> bool:
        reg = registrable(host)
        return host in self.safe or reg in self.safe or any(host == a or host.endswith("." + a) for a in allowed)

    def analyse(self, text: str, allowed: Iterable[str] = ()) -> list[LinkFinding]:
        allowed_l = [a.lower() for a in allowed if a]
        out: list[LinkFinding] = []
        for url in self.extract(text):
            host, userinfo = host_of(url)
            if not host or " " in host:
                continue
            if self._is_safe(host, allowed_l) and not userinfo:
                continue
            f = self._judge(host, userinfo, url)
            if f and f.weight > 0:
                out.append(f)
        merged: dict[str, LinkFinding] = {}
        for f in out:  # the same host can be found by several patterns; keep the heaviest reading
            if f.host not in merged or f.weight > merged[f.host].weight:
                merged[f.host] = f
        return list(merged.values())

    def _judge(self, host: str, userinfo: bool, url: str) -> LinkFinding | None:
        w, why = 0, []
        reg = registrable(host)
        labels = host.split(".")
        tld = labels[-1]

        def add(points: int, reason: str) -> None:
            nonlocal w
            w += points
            why.append(reason)

        try:
            ipaddress.ip_address(host)
            add(30, "a bare IP address, not a website name")
            return LinkFinding(host, min(70, w), why)
        except ValueError:
            pass
        if userinfo:
            add(35, "uses the user@site trick to hide the real address")
        if "xn--" in host or any(ord(ch) > 127 for ch in host):
            add(30, "uses look-alike international letters")
        elif mixed_script_words(host):
            add(30, "mixes alphabets inside the address")

        for sfx in _suffixes(host):
            if sfx in self.scam:
                add(self.scam[sfx], "listed as a scam or phishing site")
                break
        for rx, weight in self.patterns:
            if rx.search(host):
                add(weight, "the address itself looks like a scam")
                break
        for sfx in _suffixes(host):
            if sfx in self.shorteners:
                add(self.shorteners[sfx], "a link shortener hides the real destination")
                break
            if sfx in self.messengers:
                add(self.messengers[sfx], "invites people into a private chat group")
                break
            if sfx in self.hubs:
                add(self.hubs[sfx], "a link-in-bio page")
                break

        lab = reg.split(".")[0]
        lab_n = deep_normalize(lab.replace("-", ""))
        lab_l = deep_normalize(lab.replace("-", "").translate(_DIGIT_L))
        best: tuple[int, str] | None = None
        for breg, blabel, bnorm in self.protected:
            if reg == breg or host.endswith("." + breg):
                best = None
                break
            if len(bnorm) < 6:
                continue  # short brand names (x.com, ea.com) are too easy to match by accident
            tol = 1 if len(bnorm) <= 9 else 2
            if lab == blabel:
                cand = (40, f"same name as {breg} with a different ending")
            elif lab_n == bnorm or lab_l == bnorm:
                cand = (50, f"looks like {breg} (disguised letters) but is not")
            elif (min(levenshtein(lab_n, bnorm, tol), levenshtein(lab_l, bnorm, tol)) <= tol
                  and abs(len(lab_n) - len(bnorm)) <= tol):
                cand = (50, f"looks like {breg} but is not")
            elif bnorm in lab_n.replace(" ", "") or bnorm in deep_normalize(host.replace(".", "")):
                cand = (45, f"uses the name of {breg} but is not it")
            else:
                continue
            if best is None or cand[0] > best[0]:
                best = cand
        if best:
            add(*best)

        if tld in self.tlds:
            add(self.tlds[tld], f"'.{tld}' endings are common in scams")
        words = [t for t in re.split(r"[^a-z0-9]+", host.rsplit(".", 1)[0]) if t]
        hits = [t for t in words if t in self.bait]
        if hits:
            add(min(3, len(set(hits))) * max(self.bait[hits[0]], 1), "bait words in the address (" + ", ".join(sorted(set(hits))[:3]) + ")")
        if len(labels) >= 5:
            add(10, "an unusually deep chain of sub-domains")
        if host.count("-") >= 3:
            add(10, "many hyphens in the address")
        if sum(ch.isdigit() for ch in lab) >= 4:
            add(8, "lots of digits in the name")
        return LinkFinding(host, min(70, w), why) if w else None
