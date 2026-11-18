"""Live data: refreshes public threat lists in the background and stores them as a knowledge pack.

Careful by design: polite (one feed per tick, an interval between refreshes, ETag support, a size cap), safe (well-known
sites can never be added, a list that suddenly shrinks is refused, a failed download keeps the old data) and reversible
(the previous version is kept so a refresh can be rolled back). The bot's own server makes the requests.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .. import __version__
from ..http import NetworkError, request_raw
from ..store import ValidationFailed
from .links import registrable

logger = logging.getLogger("savahbot.intel")

HOST_RX = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
# Shared hosting: listing the bare name would blame every site on it, so only the exact name is refused.
SHARED_HOSTS = {"github.io", "blogspot.com", "web.app", "pages.dev", "netlify.app", "vercel.app", "herokuapp.com", "workers.dev",
                "firebaseapp.com", "weebly.com", "wixsite.com", "000webhostapp.com", "glitch.me", "repl.co", "wordpress.com",
                "azurewebsites.net", "amazonaws.com", "cloudfront.net", "googleusercontent.com", "sites.google.com", "forms.gle"}
USER_AGENT = f"SavahBot/{__version__} (owner chat moderation; threat-list refresh)"


@dataclass(frozen=True)
class FeedDef:
    id: str
    title: str
    url: str
    format: str            # domains | hosts | urls | phrases
    about: str
    license: str
    homepage: str = ""
    default_enabled: bool = True
    custom: bool = False

    @property
    def pack(self) -> str:
        return "spam.community" if self.format == "phrases" else "links.threat_feed"


BUILTIN = [
    FeedDef("phishing_filter", "Phishing domains (malware-filter)", "https://malware-filter.gitlab.io/malware-filter/phishing-filter-domains.txt",
            "domains", "Domains of active phishing sites, rebuilt several times a day from PhishTank, OpenPhish and others.",
            "CC0 / MIT", "https://gitlab.com/malware-filter/phishing-filter"),
    FeedDef("urlhaus_filter", "Malware domains (URLhaus filter)", "https://malware-filter.gitlab.io/malware-filter/urlhaus-filter-domains.txt",
            "domains", "Domains currently serving malware, from abuse.ch URLhaus.", "CC0", "https://gitlab.com/malware-filter/urlhaus-filter"),
    FeedDef("urlhaus_hosts", "Malware hosts (abuse.ch URLhaus)", "https://urlhaus.abuse.ch/downloads/hostfile/",
            "hosts", "The official URLhaus hosts file: sites distributing malware right now.", "CC0", "https://urlhaus.abuse.ch/api/"),
    FeedDef("blocklist_scam", "Scam sites (Block List Project)", "https://raw.githubusercontent.com/blocklistproject/Lists/master/scam.txt",
            "hosts", "Community list of scam, fake-shop and fraud sites.", "Unlicense", "https://github.com/blocklistproject/Lists"),
    FeedDef("openphish", "Phishing URLs (OpenPhish community feed)", "https://openphish.com/feed.txt",
            "urls", "Fresh phishing URLs. The free feed is for personal, non-commercial use, so it starts switched off.",
            "OpenPhish community terms", "https://openphish.com/", default_enabled=False),
]


# ---------------------------------------------------------------------------- parsing
def parse_feed(text: str, fmt: str, limit: int, never: set[str] | None = None) -> list[str]:
    never = never or set()
    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "#!;[<":
            continue
        if fmt == "phrases":
            phrase = re.sub(r"\s+", " ", line)[:100]
            if len(phrase) >= 4 and phrase.casefold() not in seen:
                seen.add(phrase.casefold())
                out.append(phrase)
        else:
            host = _host_from(line, fmt)
            if not host or host in seen:
                continue
            seen.add(host)
            if host in SHARED_HOSTS or registrable(host) in never or host in never:
                continue
            out.append(host)
        if len(out) >= limit:
            break
    return out


def _host_from(line: str, fmt: str) -> str:
    if fmt == "hosts":
        parts = line.split()
        if len(parts) < 2 or parts[0] not in ("0.0.0.0", "127.0.0.1", "::1", "::"):
            return ""
        token = parts[1]
    elif fmt == "urls":
        token = urlparse(line if "://" in line else "http://" + line).hostname or ""
    else:
        token = line.split()[0]
    host = token.lower().strip(".")
    host = host[4:] if host.startswith("www.") else host
    return host if HOST_RX.match(host) and host != "localhost" else ""


class _GuardCfg:
    """check_url wants the urlfetch settings; custom feeds always get the private-address block and ignore the allow-list."""
    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg

    def get(self, name: str) -> Any:
        return {"urlfetch_allowed_hosts": "", "urlfetch_block_private": True}.get(name, self.cfg.get(name))


class FeedManager:
    def __init__(self, db: Any, cfg: Any, intel: Any, knowledge: Any) -> None:
        self.db, self.cfg, self.intel, self.knowledge = db, cfg, intel, knowledge
        self._born = time.time()
        self._state: dict[str, dict[str, Any]] = {}
        self._custom: list[FeedDef] = []
        self._busy = False

    # ------------------------------------------------------------------ definitions and state
    async def load(self) -> None:
        try:
            raw = json.loads(await self.db.kv_get("intel_custom_feeds") or "[]")
        except ValueError:
            raw = []
        self._custom = [FeedDef(str(d["id"]), str(d["title"]), str(d["url"]), str(d["format"]), "A feed you added.", "your own source",
                                custom=True) for d in raw if isinstance(d, dict) and {"id", "title", "url", "format"} <= set(d)]
        for d in self.defs():
            await self.db.execute("INSERT INTO knowledge_feeds (id, enabled) VALUES (?, ?) ON CONFLICT (id) DO NOTHING",
                                  (d.id, int(d.default_enabled)))
        self._state = {r["id"]: r for r in await self.db.fetchall("SELECT * FROM knowledge_feeds")}

    def defs(self) -> list[FeedDef]:
        return [*BUILTIN, *self._custom]

    def _def(self, fid: str) -> FeedDef:
        for d in self.defs():
            if d.id == fid:
                return d
        raise KeyError(fid)

    async def _refresh_state(self) -> None:
        self._state = {r["id"]: r for r in await self.db.fetchall("SELECT * FROM knowledge_feeds")}

    def list(self) -> list[dict[str, Any]]:
        out = []
        interval = self._interval()
        for d in self.defs():
            st = self._state.get(d.id, {})
            last = st.get("last_run")
            out.append({"id": d.id, "title": d.title, "url": d.url, "format": d.format, "about": d.about, "license": d.license,
                        "homepage": d.homepage, "custom": d.custom, "pack": d.pack, "enabled": bool(st.get("enabled", d.default_enabled)),
                        "entries": int(st.get("entries") or 0), "previous_entries": int(st.get("prev_entries") or 0),
                        "last_run": last, "last_ok": st.get("last_ok"), "status": st.get("status") or "never run",
                        "error": st.get("error") or "", "can_rollback": bool(int(st.get("gen") or 0) > 1 and int(st.get("prev_entries") or 0) > 0),
                        "next_due": (last + interval) if last else None})
        return out

    def summary(self) -> dict[str, Any]:
        rows = self.list()
        oks = [r["last_ok"] for r in rows if r["last_ok"]]
        return {"enabled": sum(1 for r in rows if r["enabled"]), "total": len(rows), "entries": sum(r["entries"] for r in rows if r["enabled"]),
                "last_ok": max(oks) if oks else None, "errors": sum(1 for r in rows if r["enabled"] and r["error"]),
                "auto": bool(self.cfg.get("intel_feeds_enabled"))}

    def _interval(self) -> float:
        return max(1.0, float(self.cfg.get("intel_feed_interval_hours"))) * 3600

    # ------------------------------------------------------------------ custom feeds
    async def add_custom(self, title: str, url: str, fmt: str) -> dict[str, Any]:
        title, url = (title or "").strip()[:60], (url or "").strip()
        if not title:
            raise ValidationFailed("Give the feed a name.")
        if fmt not in ("domains", "hosts", "urls", "phrases"):
            raise ValidationFailed("Format must be domains, hosts, urls or phrases.")
        if len(self._custom) >= 10:
            raise ValidationFailed("You can add at most 10 feeds of your own.")
        from ..commands.variables import UrlBlocked, check_url
        try:
            await check_url(url, _GuardCfg(self.cfg))
        except UrlBlocked as exc:
            raise ValidationFailed(f"That address cannot be used: {exc}.") from exc
        fid = "custom_" + re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:24]
        if any(d.id == fid for d in self.defs()):
            fid += f"_{len(self._custom) + 1}"
        self._custom.append(FeedDef(fid, title, url, fmt, "A feed you added.", "your own source", custom=True))
        await self.db.kv_set("intel_custom_feeds", json.dumps([{"id": d.id, "title": d.title, "url": d.url, "format": d.format} for d in self._custom]))
        await self.db.execute("INSERT INTO knowledge_feeds (id, enabled) VALUES (?, 1) ON CONFLICT (id) DO NOTHING", (fid,))
        await self._refresh_state()
        return {"id": fid}

    async def remove_custom(self, fid: str) -> None:
        if not any(d.id == fid and d.custom for d in self.defs()):
            raise KeyError(fid)
        self._custom = [d for d in self._custom if d.id != fid]
        await self.db.kv_set("intel_custom_feeds", json.dumps([{"id": d.id, "title": d.title, "url": d.url, "format": d.format} for d in self._custom]))
        await self.db.execute("DELETE FROM knowledge_entries WHERE source = ?", (f"feed:{fid}",))
        await self.db.execute("DELETE FROM knowledge_feeds WHERE id = ?", (fid,))
        await self.knowledge.load()
        await self._refresh_state()

    async def set_enabled(self, fid: str, enabled: bool) -> None:
        self._def(fid)
        await self.db.execute("UPDATE knowledge_feeds SET enabled = ? WHERE id = ?", (int(enabled), fid))
        await self._refresh_state()
        await self.knowledge.load()

    # ------------------------------------------------------------------ refreshing
    def _never(self) -> set[str]:
        never = set(self.intel.links.safe)
        never.update(d for d, _, _ in self.intel.links.protected)
        never.update(x.strip().lower() for x in str(self.cfg.get("mod_allowed_domains")).split(",") if x.strip())
        return never

    async def refresh(self, fid: str, force: bool = False) -> dict[str, Any]:
        d = self._def(fid)
        if self._busy:
            raise ValidationFailed("A refresh is already running. Try again in a moment.")
        self._busy = True
        now = time.time()
        st = self._state.get(fid, {})
        try:
            try:
                if d.custom:
                    from ..commands.variables import UrlBlocked, check_url
                    try:
                        await check_url(d.url, _GuardCfg(self.cfg))
                    except UrlBlocked as exc:
                        raise NetworkError(f"blocked: {exc}") from exc
                headers = {"User-Agent": USER_AGENT, "Accept": "text/plain, */*;q=0.5"}
                if st.get("etag") and not force:
                    headers["If-None-Match"] = st["etag"]
                limit = int(self.cfg.get("intel_feed_max_bytes"))
                status, raw, resp = await request_raw("GET", d.url, headers=headers, timeout=25.0, max_bytes=limit,
                                                      follow_redirects=not d.custom)
            except NetworkError as exc:
                return await self._fail(fid, now, f"Could not download: {exc}")
            if status == 304:
                await self.db.execute("UPDATE knowledge_feeds SET last_run = ?, status = 'up to date', error = '' WHERE id = ?", (now, fid))
                await self._refresh_state()
                return {"ok": True, "status": "up to date", "entries": int(st.get("entries") or 0)}
            if status != 200 or not raw:
                return await self._fail(fid, now, f"The server answered {status}.")
            text = raw.decode("utf-8", "replace")
            if len(raw) >= limit:  # cut off at the size cap: drop the half line at the end
                text = text.rsplit("\n", 1)[0]
            entries = parse_feed(text, d.format, int(self.cfg.get("intel_feed_max_entries")), self._never())
            if not entries:
                return await self._fail(fid, now, "The download held nothing usable, so the old data was kept.")
            prev = int(st.get("entries") or 0)
            if not force and prev >= 100 and len(entries) < prev * 0.3:
                return await self._fail(fid, now, f"The list shrank from {prev} to {len(entries)}; kept the old data (use Refresh now with force to accept).")
            gen = int(st.get("gen") or 0) + 1
            for i in range(0, len(entries), 150):
                chunk = entries[i:i + 150]
                marks = ",".join("(?, ?, 0, 0, 1, ?, ?, ?)" for _ in chunk)
                args: list[Any] = []
                for e in chunk:
                    args += [d.pack, e, f"feed:{fid}", gen, now]
                await self.db.execute(
                    "INSERT INTO knowledge_entries (pack_id, phrase, is_regex, weight, enabled, source, gen, created) VALUES " + marks
                    + " ON CONFLICT (pack_id, phrase, source, gen) DO NOTHING", tuple(args))
            etag = next((v for k, v in resp.items() if k.lower() == "etag"), "")
            await self.db.execute(
                "UPDATE knowledge_feeds SET gen = ?, last_run = ?, last_ok = ?, status = 'ok', error = '', entries = ?, prev_entries = ?, etag = ? WHERE id = ?",
                (gen, now, now, len(entries), prev, etag, fid))
            await self.db.execute("DELETE FROM knowledge_entries WHERE source = ? AND gen < ?", (f"feed:{fid}", gen - 1))
            await self._refresh_state()
            await self.knowledge.load()
            return {"ok": True, "status": "ok", "entries": len(entries), "previous": prev}
        finally:
            self._busy = False

    async def _fail(self, fid: str, now: float, message: str) -> dict[str, Any]:
        logger.warning("Feed %s: %s", fid, message)
        await self.db.execute("UPDATE knowledge_feeds SET last_run = ?, status = 'failed', error = ? WHERE id = ?", (now, message[:300], fid))
        await self._refresh_state()
        return {"ok": False, "status": "failed", "error": message}

    async def rollback(self, fid: str) -> dict[str, Any]:
        self._def(fid)
        st = self._state.get(fid, {})
        gen = int(st.get("gen") or 0)
        if gen < 2:
            raise ValidationFailed("There is no earlier version to go back to.")
        have = await self.db.fetchone("SELECT COUNT(*) AS n FROM knowledge_entries WHERE source = ? AND gen = ?", (f"feed:{fid}", gen - 1))
        if not have or not have["n"]:
            raise ValidationFailed("The earlier version is no longer stored.")
        await self.db.execute("DELETE FROM knowledge_entries WHERE source = ? AND gen > ?", (f"feed:{fid}", gen - 1))
        await self.db.execute("UPDATE knowledge_feeds SET gen = ?, entries = ?, prev_entries = 0, status = 'rolled back', etag = '' WHERE id = ?",
                              (gen - 1, have["n"], fid))
        await self._refresh_state()
        await self.knowledge.load()
        return {"ok": True, "entries": have["n"]}

    async def tick(self, now: float) -> None:
        """Called by the scheduler. Refreshes at most one due feed per call."""
        if not self.cfg.get("intel_feeds_enabled") or self._busy:
            return
        if time.time() - self._born < float(self.cfg.get("intel_feed_startup_delay_seconds")):
            return
        interval = self._interval()
        for d in self.defs():
            st = self._state.get(d.id, {})
            if not st.get("enabled", d.default_enabled):
                continue
            last = st.get("last_run") or 0
            wait = interval if st.get("status") != "failed" else min(interval, 3600 * 3)  # retry a failure sooner, but politely
            if now - last >= wait:
                try:
                    await self.refresh(d.id)
                except Exception:  # a feed must never take the scheduler down
                    logger.exception("Feed refresh crashed: %s", d.id)
                return
