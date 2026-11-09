"""Link intelligence: judges where a link leads without visiting it.

Checks the address itself: link shorteners, heavily abused endings, punycode and mixed alphabets, raw IP addresses,
the '@' trick, lookalikes of big brands (youtub3.com, discord-nitro.click, youtube.com.verify-login.xyz), scam words in
the domain, and links disguised as 'site dot com'. Links to safe or allowed domains are never flagged.
"""
from __future__ import annotations

import re

from ...moderation.engine import _DOT_WORD, _domain
from ...moderation.normalize import normalize
from ...utils import split_csv
from ..text import damerau, mixed_script_words, noisy_or
from .base import Ctx, Detector, Finding

_IP = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "or", "go", "ne", "sc", "me", "edu"}
_COMMON_TLD = {"com", "net", "org", "io", "gg", "tv", "co", "me", "dev", "app"}
# Whole addresses, so 'youtube.com.verify-login.xyz' is judged as one thing and not cut at '.com'.
_CANDIDATE = re.compile(r"(?i)(?:https?://|www\.)\S+|\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}\b(?:/\S*)?")
_KNOWN_TLD = set("""com net org io gg tv me co ly link top club site online shop info biz cc app dev live stream click win vip fun store pro icu xyz ru
ke ug tz rw et ng gh za zm zw so cd sn ma eg dz tn uk us ca au nz ie de fr es it pt nl be ch at se no dk fi pl cz gr tr ua il ae sa ir in pk bd lk cn jp kr hk sg my th vn id ph br ar mx cl pe co
edu gov mil int""".split())


def registrable(host: str) -> str:
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


class LinkDetector(Detector):
    id = "links"
    title = "Link intelligence"
    signal = "link_risk"
    description = "Judges the link itself: shorteners, abused endings, lookalikes of big brands, raw IP addresses, the @ trick and scam words in the address. Safe and allowed domains are skipped."

    def analyze(self, ctx: Ctx) -> Finding | None:
        text = re.sub(r"\[\.\]|\(\.\)", ".", ctx.text)
        disguised = _DOT_WORD.sub(".", text)
        risk = self.registry.linkrisk()
        known = _KNOWN_TLD | risk["tld_high"] | risk["tld_medium"]
        found = [m for m in _CANDIDATE.findall(disguised) if m.lower().startswith(("http", "www.")) or re.split(r"[/?]", m.lower())[0].rsplit(".", 1)[-1] in known]
        if not found:
            return None
        allowed = {d.lower() for d in split_csv(self.svc.cfg.get("mod_allowed_domains"))} | risk["safe"]
        best: tuple[float, list[str]] | None = None
        for url in found[:5]:
            raw = re.sub(r"^https?://", "", url.lower())
            authority = raw.split("/")[0].split("?")[0]
            at_trick = "@" in authority
            host = _domain(url.split("@", 1)[1] if at_trick else url)
            if not host or host in allowed or any(host.endswith("." + a) for a in allowed):
                continue
            s, why = self._judge(host, at_trick, disguised != ctx.text, risk)
            if s > 0 and (best is None or s > best[0]):
                best = (s, [host] + why)
        if best is None:
            return None
        strength = best[0] * (0.8 + 0.4 * self.sensitivity())
        return Finding(min(1.0, strength), f"{best[1][0]} ({', '.join(best[1][1:])})" if len(best[1]) > 1 else best[1][0], meta={"host": best[1][0]})

    def _judge(self, host: str, at_trick: bool, dot_disguise: bool, risk: dict) -> tuple[float, list[str]]:
        parts: list[tuple[float, str]] = []
        labels = host.split(".")
        reg = registrable(host)
        tld = labels[-1]
        sld = reg.split(".")[0]
        if reg in risk["shorteners"] or host in risk["shorteners"]:
            parts.append((0.35, "link shortener"))
        if tld in risk["tld_high"]:
            parts.append((0.40, f"risky ending .{tld}"))
        elif tld in risk["tld_medium"] and tld not in _COMMON_TLD:
            parts.append((0.20, f"often abused ending .{tld}"))
        if any(l.startswith("xn--") for l in labels) or not host.isascii():
            parts.append((0.5, "disguised letters in the address"))
        if mixed_script_words(host.replace(".", " ")):
            parts.append((0.6, "mixed alphabets"))
        if _IP.match(host):
            parts.append((0.5, "raw IP address"))
        if at_trick:
            parts.append((0.5, "the @ trick hides the real address"))
        # lookalikes of big brands
        sld_norm = normalize(sld.replace("-", " ")).replace(" ", "")
        sld_tokens = set(re.split(r"[-_.]", sld))
        for brand, official in risk["brands"].items():
            if reg in official or any(host.endswith("." + o) for o in official):
                continue
            if brand in labels[:-2] or any(o in host.replace(reg, "") for o in official):
                parts.append((0.85, f"pretends to be {brand} using a subdomain"))
                break
            if sld_norm == brand and sld != brand:
                parts.append((0.85, f"spelled like {brand} with swapped letters"))
                break
            if len(brand) >= 5 and sld_norm != brand and damerau(sld_norm, brand, 1) == 1:
                parts.append((0.75, f"one letter away from {brand}"))
                break
            if brand in sld_tokens and len(sld_tokens) > 1:
                parts.append((0.70, f"uses the name {brand} on another domain"))
                break
            if len(brand) >= 5 and brand in sld and sld != brand:
                parts.append((0.6, f"contains the name {brand}"))
                break
        words = [w for w in risk["scam_words"] if (w in sld if len(w) >= 5 else w in sld_tokens)]
        if words:
            parts.append((min(0.5, 0.2 + 0.1 * len(words)), "scam words: " + ", ".join(sorted(words)[:3])))
        if sld.count("-") >= 3:
            parts.append((0.2, "many hyphens"))
        if len(sld) > 8 and sum(c.isdigit() for c in sld) / len(sld) > 0.3:
            parts.append((0.15, "mostly numbers"))
        if len(labels) >= 5:
            parts.append((0.2, "many subdomains"))
        if dot_disguise:
            parts.append((0.10, "written to hide it is a link"))
        if not parts:
            return 0.0, []
        return noisy_or(s for s, _ in parts), [d for _, d in sorted(parts, key=lambda x: -x[0])[:3]]
