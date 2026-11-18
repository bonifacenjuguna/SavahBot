"""The central weather service. The dashboard, Telegram and the alert engine all go through here; nothing else talks to a provider.

Cache layers: memory (always) + Redis through `Shared` (when configured, shared between instances; any Redis trouble falls back to
memory silently). Saved locations, preferences, rules and alert state live in the database. Cached forecasts are never stored
permanently, and a cached forecast is always labelled with when it was fetched.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any

from ..db import register_schema
from ..notify import Category, register as register_category
from . import rules as R
from . import units
from .codes import compass
from .provider import OpenMeteo, WeatherError, WeatherProvider, valid_coords

logger = logging.getLogger("savahbot.weather")

register_schema([
    """CREATE TABLE IF NOT EXISTS weather_locations (
        id {PK}, name TEXT NOT NULL, admin1 TEXT NOT NULL DEFAULT '', country TEXT NOT NULL DEFAULT '', country_code TEXT NOT NULL DEFAULT '',
        lat {REAL} NOT NULL, lon {REAL} NOT NULL, timezone TEXT NOT NULL DEFAULT '', elevation {REAL}, is_default INTEGER NOT NULL DEFAULT 0,
        monitor INTEGER NOT NULL DEFAULT 1, created {REAL} NOT NULL, UNIQUE (lat, lon))""",
    """CREATE TABLE IF NOT EXISTS weather_rules (
        id {PK}, name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'threshold', variable TEXT NOT NULL DEFAULT '', op TEXT NOT NULL DEFAULT '>=', threshold {REAL} NOT NULL DEFAULT 0,
        window_hours INTEGER NOT NULL DEFAULT 3, location_id INTEGER, category TEXT NOT NULL, cooldown_minutes INTEGER NOT NULL DEFAULT 180,
        every_minutes INTEGER NOT NULL DEFAULT 30, active_from TEXT NOT NULL DEFAULT '', active_to TEXT NOT NULL DEFAULT '', summary_time TEXT NOT NULL DEFAULT '07:00',
        enabled INTEGER NOT NULL DEFAULT 1, created {REAL} NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS weather_alert_state (
        rule_id INTEGER NOT NULL, location_id INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 0, last_sent {REAL}, last_eval {REAL}, signature TEXT NOT NULL DEFAULT '',
        last_value {REAL}, last_summary_date TEXT NOT NULL DEFAULT '', PRIMARY KEY (rule_id, location_id))""",
])

register_category(
    Category("weather.rain", "weather", "Rain expected", "Rain is likely soon at your monitored location.", "cloudRain", "warn", "normal", route="#/weather", dedupe_seconds=3600),
    Category("weather.heavy_rain", "weather", "Heavy rain", "A large amount of rain is forecast.", "cloudRain", "bad", "high", route="#/weather", dedupe_seconds=3600),
    Category("weather.temperature", "weather", "Extreme temperature", "Very hot or very cold weather is forecast.", "thermometer", "warn", "normal", route="#/weather", dedupe_seconds=3600),
    Category("weather.wind", "weather", "Strong wind", "Strong winds or gusts are forecast.", "wind", "warn", "normal", route="#/weather", dedupe_seconds=3600),
    Category("weather.storm", "weather", "Thunderstorm", "Thunderstorms are in the forecast.", "cloudLightning", "bad", "high", route="#/weather", dedupe_seconds=3600),
    Category("weather.summary", "weather", "Daily weather summary", "A short summary of today's weather each morning.", "sun", "info", "low", route="#/weather", dedupe_seconds=3600),
)
CATEGORIES = ("weather.rain", "weather.heavy_rain", "weather.temperature", "weather.wind", "weather.storm", "weather.summary")

DEFAULT_PREFS: dict[str, Any] = {
    "temp": "c", "wind": "kmh", "precip": "mm", "clock": "24", "horizon_hours": 24, "daily_days": 7, "offer_device_location": True,
    "show": {"current": True, "hourly": True, "daily": True, "precip": True, "wind": True, "sun": True, "details": True},
    "refresh": {"auto": True, "minutes": 30},
    "alerts": {"enabled": True},
}
CHOICES = {"temp": ("c", "f"), "wind": ("kmh", "ms", "mph", "kn"), "precip": ("mm", "in"), "clock": ("12", "24"), "horizon_hours": (12, 24, 48, 72), "daily_days": (3, 5, 7, 10, 14)}
SEED_RULES = [
    ("Rain likely", "precip_probability", ">=", 70, 3, "weather.rain", 180, 1),
    ("Heavy rain", "precipitation_total", ">=", 20, 3, "weather.heavy_rain", 360, 1),
    ("Very hot", "temperature_max", ">=", 35, 24, "weather.temperature", 720, 1),
    ("Very cold", "temperature_min", "<=", 5, 24, "weather.temperature", 720, 1),
    ("Strong gusts", "wind_gust_max", ">=", 60, 6, "weather.wind", 360, 1),
    ("Thunderstorm", "thunderstorm", ">=", 1, 6, "weather.storm", 360, 1),
]
MAX_LOCATIONS = 20


class WeatherServiceError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message, self.status = message, status


class WeatherService:
    def __init__(self, db: Any, cfg: Any, shared: Any = None, notifier: Any = None, provider: WeatherProvider | None = None) -> None:
        self.db, self.cfg, self.shared, self.notifier = db, cfg, shared, notifier
        self.provider: WeatherProvider = provider or OpenMeteo(float(cfg.get("weather_timeout_seconds")), int(cfg.get("weather_retries")), str(cfg.get("weather_commercial_api_key") or ""))
        self._prefs: dict[str, Any] | None = None
        self._mem: dict[str, tuple[float, Any]] = {}
        self._inflight: dict[str, asyncio.Future] = {}
        self._status: dict[str, dict[str, Any]] = {}
        self._last_tick = 0.0

    # ------------------------------------------------------------------ preferences
    async def prefs(self) -> dict[str, Any]:
        if self._prefs is None:
            raw = await self.db.kv_get("weather_prefs")
            try:
                saved = json.loads(raw) if raw else {}
            except ValueError:
                saved = {}
            self._prefs = self._merge(saved)
        return self._prefs

    @staticmethod
    def _merge(saved: dict[str, Any]) -> dict[str, Any]:
        out = json.loads(json.dumps(DEFAULT_PREFS))
        for k, allowed in CHOICES.items():
            if saved.get(k) in allowed:
                out[k] = saved[k]
        if isinstance(saved.get("offer_device_location"), bool):
            out["offer_device_location"] = saved["offer_device_location"]
        for k in out["show"]:
            if isinstance((saved.get("show") or {}).get(k), bool):
                out["show"][k] = saved["show"][k]
        r = saved.get("refresh") or {}
        if isinstance(r.get("auto"), bool):
            out["refresh"]["auto"] = r["auto"]
        if isinstance(r.get("minutes"), int) and 15 <= r["minutes"] <= 180:
            out["refresh"]["minutes"] = r["minutes"]
        if isinstance((saved.get("alerts") or {}).get("enabled"), bool):
            out["alerts"]["enabled"] = saved["alerts"]["enabled"]
        return out

    async def set_prefs(self, patch: dict[str, Any]) -> dict[str, Any]:
        cur = json.loads(json.dumps(await self.prefs()))
        for k, v in patch.items():
            if k in CHOICES and v not in CHOICES[k]:
                raise WeatherServiceError(f"{k} must be one of {', '.join(map(str, CHOICES[k]))}.")
            if k in ("show", "refresh", "alerts") and isinstance(v, dict):
                if k == "refresh" and "minutes" in v and not (isinstance(v["minutes"], int) and 15 <= v["minutes"] <= 180):
                    raise WeatherServiceError("Refresh every 15 to 180 minutes. Open-Meteo's free service asks apps to stay well under its limits.")
                cur[k].update({a: b for a, b in v.items() if a in cur[k]})
            elif k in cur:
                cur[k] = v
        self._prefs = self._merge(cur)
        await self.db.kv_set("weather_prefs", json.dumps(self._prefs))
        return self._prefs

    # ------------------------------------------------------------------ cache
    async def _cache_get(self, key: str, max_age: float) -> tuple[float, Any] | None:
        hit = self._mem.get(key)
        if hit and time.time() - hit[0] <= max_age:
            return hit
        if self.shared is not None:
            try:
                raw = await self.shared.get(key)
                if raw:
                    ts, data = json.loads(raw)
                    if time.time() - ts <= max_age:
                        self._mem[key] = (ts, data)
                        return ts, data
            except Exception:
                logger.debug("Redis cache read failed; using memory", exc_info=True)
        return None

    async def _cache_set(self, key: str, data: Any, keep: float) -> float:
        ts = time.time()
        self._mem[key] = (ts, data)
        if len(self._mem) > 400:
            for k in sorted(self._mem, key=lambda x: self._mem[x][0])[:100]:
                self._mem.pop(k, None)
        if self.shared is not None:
            try:
                await self.shared.set(key, json.dumps([ts, data]), ex=keep)
            except Exception:
                logger.debug("Redis cache write failed; memory only", exc_info=True)
        return ts

    async def _single(self, key: str, make: Any) -> Any:
        """One provider call per key at a time: simultaneous requests share the same answer."""
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            res = await make()
            fut.set_result(res)
            return res
        except BaseException as exc:
            fut.set_exception(exc)
            fut.exception()      # mark retrieved so a lone caller does not log "never retrieved"
            raise
        finally:
            self._inflight.pop(key, None)

    @staticmethod
    def _fkey(lat: float, lon: float) -> str:
        return f"weather:fc:{lat:.3f}:{lon:.3f}"        # coordinates are part of the key: one place never gets another's forecast

    # ------------------------------------------------------------------ locations
    async def search(self, query: str, count: int = 8) -> list[dict[str, Any]]:
        q = " ".join((query or "").split())
        if len(q) < 2:
            raise WeatherServiceError("Type at least two letters.")
        key = f"weather:geo:{q.lower()[:100]}:{count}"
        hit = await self._cache_get(key, float(self.cfg.get("weather_geocode_ttl_hours")) * 3600)
        if hit:
            return hit[1]
        try:
            places = await self._single(key, lambda: self.provider.search(q, count))
        except WeatherError as exc:
            raise WeatherServiceError(exc.message, 400 if exc.kind == "invalid" else 502) from None
        await self._cache_set(key, places, float(self.cfg.get("weather_geocode_ttl_hours")) * 3600)
        return places

    @staticmethod
    def _loc(r: dict[str, Any]) -> dict[str, Any]:
        label = ", ".join(x for x in (r["name"], r["admin1"], r["country"]) if x)
        return {"id": r["id"], "name": r["name"], "admin1": r["admin1"], "country": r["country"], "country_code": r["country_code"], "label": label,
                "lat": round(r["lat"], 2), "lon": round(r["lon"], 2), "timezone": r["timezone"], "default": bool(r["is_default"]), "monitor": bool(r["monitor"])}

    async def locations(self) -> list[dict[str, Any]]:
        rows = await self.db.fetchall("SELECT * FROM weather_locations ORDER BY is_default DESC, created")
        return [self._loc(r) for r in rows]

    async def get_location(self, loc_id: int | None = None) -> dict[str, Any] | None:
        if loc_id:
            return await self.db.fetchone("SELECT * FROM weather_locations WHERE id = ?", (loc_id,))
        return await self.db.fetchone("SELECT * FROM weather_locations WHERE is_default = 1") or await self.db.fetchone("SELECT * FROM weather_locations ORDER BY created LIMIT 1")

    async def add_location(self, *, name: str = "", lat: Any, lon: Any, admin1: str = "", country: str = "", country_code: str = "", timezone: str = "", elevation: float | None = None,
                           make_default: bool = False) -> dict[str, Any]:
        try:
            la, lo = valid_coords(lat, lon)
        except WeatherError as exc:
            raise WeatherServiceError(exc.message) from None
        existing = await self.db.fetchone("SELECT * FROM weather_locations WHERE lat = ? AND lon = ?", (la, lo))
        if existing:
            if make_default:
                await self.set_default(existing["id"])
            return self._loc(await self.get_location(existing["id"]))  # type: ignore[arg-type]
        if (await self.db.fetchone("SELECT COUNT(*) AS n FROM weather_locations"))["n"] >= MAX_LOCATIONS:
            raise WeatherServiceError(f"You can save up to {MAX_LOCATIONS} locations. Remove one first.")
        name = " ".join((name or "").split())[:80]
        if not timezone or not name:                      # a manual pin: ask the provider for the timezone, which also proves the coordinates work
            try:
                fc = await self.provider.forecast(la, lo, "auto", 1)
            except WeatherError as exc:
                raise WeatherServiceError(f"Could not use those coordinates: {exc.message}", 400 if exc.kind == "invalid" else 502) from None
            timezone = timezone or fc["timezone"]
            elevation = elevation if elevation is not None else fc.get("elevation")
            name = name or f"{la:.2f}, {lo:.2f}"
        first = (await self.db.fetchone("SELECT COUNT(*) AS n FROM weather_locations"))["n"] == 0
        i = await self.db.insert("INSERT INTO weather_locations (name, admin1, country, country_code, lat, lon, timezone, elevation, is_default, monitor, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                                 (name, admin1[:80], country[:80], country_code[:3], la, lo, timezone[:60], elevation, 1 if first else 0, time.time()))
        if make_default and not first:
            await self.set_default(i)
        logger.info("Weather location %s saved", i)       # ids only: coordinates stay out of the logs
        return self._loc(await self.get_location(i))      # type: ignore[arg-type]

    async def set_default(self, loc_id: int) -> None:
        if not await self.get_location(loc_id):
            raise WeatherServiceError("That location no longer exists.", 404)
        await self.db.execute("UPDATE weather_locations SET is_default = 0")
        await self.db.execute("UPDATE weather_locations SET is_default = 1 WHERE id = ?", (loc_id,))

    async def update_location(self, loc_id: int, name: str | None, monitor: bool | None) -> None:
        if not await self.get_location(loc_id):
            raise WeatherServiceError("That location no longer exists.", 404)
        if name is not None and name.strip():
            await self.db.execute("UPDATE weather_locations SET name = ? WHERE id = ?", (" ".join(name.split())[:80], loc_id))
        if monitor is not None:
            await self.db.execute("UPDATE weather_locations SET monitor = ? WHERE id = ?", (int(monitor), loc_id))

    async def remove_location(self, loc_id: int) -> None:
        row = await self.get_location(loc_id)
        if not row:
            raise WeatherServiceError("That location no longer exists.", 404)
        await self.db.execute("DELETE FROM weather_locations WHERE id = ?", (loc_id,))
        await self.db.execute("DELETE FROM weather_alert_state WHERE location_id = ?", (loc_id,))
        await self.db.execute("UPDATE weather_rules SET location_id = NULL WHERE location_id = ?", (loc_id,))     # its rules fall back to the default location
        self._status.pop(str(loc_id), None)
        if row["is_default"]:
            nxt = await self.db.fetchone("SELECT id FROM weather_locations ORDER BY created LIMIT 1")
            if nxt:
                await self.set_default(nxt["id"])

    async def resolve(self, text: str) -> dict[str, Any] | None:
        """For Telegram: a saved location by name or number, else the best match from a search. Returns a location-like dict (saved or not)."""
        t = text.strip()
        rows = await self.db.fetchall("SELECT * FROM weather_locations ORDER BY is_default DESC, created")
        if t.isdigit() and 1 <= int(t) <= len(rows):
            return rows[int(t) - 1]
        for r in rows:
            if r["name"].lower() == t.lower() or r["name"].lower().startswith(t.lower()):
                return r
        found = await self.search(t, 1)
        if not found:
            return None
        f = found[0]
        return {"id": 0, "name": f["name"], "admin1": f["admin1"], "country": f["country"], "lat": f["lat"], "lon": f["lon"], "timezone": f["timezone"], "is_default": 0, "monitor": 0}

    # ------------------------------------------------------------------ forecasts
    def _mark(self, loc_id: int, **kw: Any) -> None:
        self._status.setdefault(str(loc_id), {}).update(kw)

    async def forecast(self, loc: dict[str, Any], force: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
        """(normalized forecast, meta). meta says when it was fetched and whether it is stale. Raises WeatherServiceError if there is nothing to show."""
        key = self._fkey(loc["lat"], loc["lon"])
        ttl = float(self.cfg.get("weather_forecast_ttl_minutes")) * 60
        stale_max = float(self.cfg.get("weather_stale_max_hours")) * 3600
        if not force:
            fresh = await self._cache_get(key, ttl)
            if fresh:
                return fresh[1], self._meta(fresh[0], False, "", loc)
        self._mark(loc["id"], last_try=time.time())
        try:
            fc = await self._single(key, lambda: self.provider.forecast(loc["lat"], loc["lon"], "auto", 7))
        except WeatherError as exc:
            logger.warning("Weather refresh failed for location %s: %s (%s)", loc["id"], exc.kind, exc.message)
            self._mark(loc["id"], last_error=exc.message, last_error_ts=time.time())
            old = await self._cache_get(key, stale_max)
            if old:       # never pass old data off as live: the meta carries stale=True and the age
                return old[1], self._meta(old[0], True, exc.message, loc)
            raise WeatherServiceError(exc.message, 400 if exc.kind == "invalid" else 502) from None
        ts = await self._cache_set(key, fc, stale_max)
        self._mark(loc["id"], last_ok=ts, last_error="")
        if loc.get("id") and not loc.get("timezone"):
            await self.db.execute("UPDATE weather_locations SET timezone = ? WHERE id = ?", (fc["timezone"], loc["id"]))
        return fc, self._meta(ts, False, "", loc)

    def _meta(self, ts: float, stale: bool, error: str, loc: dict[str, Any]) -> dict[str, Any]:
        st = self._status.get(str(loc.get("id", 0)), {})
        return {"fetched_at": ts, "age_seconds": int(time.time() - ts), "stale": stale, "error": error or "", "last_try": st.get("last_try"), "next_refresh": st.get("next")}

    async def overview(self, loc_id: int | None = None, force: bool = False) -> dict[str, Any]:
        loc = await self.get_location(loc_id)
        if loc is None:
            return {"location": None, "prefs": await self.prefs(), "locations": [], "attribution": self.attribution()}
        return await self.overview_for(loc, force)

    async def overview_for(self, loc: dict[str, Any], force: bool = False) -> dict[str, Any]:
        """Same as overview() for any location dict, saved or not (Telegram can ask about a place that is not saved)."""
        prefs = await self.prefs()
        fc, meta = await self.forecast(loc, force)
        now = time.time()
        u = {"temp": prefs["temp"], "wind": prefs["wind"], "precip": prefs["precip"]}
        hours = [h for h in fc["hourly"] if h["ts"] >= now - 1800][: prefs["horizon_hours"]]
        today = datetime.fromtimestamp(now, units.tzinfo(fc["timezone"])).strftime("%Y-%m-%d")
        days = [d for d in fc["daily"] if d["date"] >= today][: prefs["daily_days"]]
        cur = units.convert_current(fc["current"], u)
        cur["wind_dir_label"] = compass(fc["current"]["wind_dir"])
        return {"location": self._loc({**{"admin1": "", "country": "", "country_code": "", "is_default": 0, "monitor": 0}, **loc}), "timezone": fc["timezone"], "current": cur, "hourly": [units.convert_hour(h, u) for h in hours], "daily": [units.convert_day(d, u) for d in days],
                "meta": meta, "units": units.labels(u), "prefs": prefs, "attribution": self.attribution(), "now": now}

    def attribution(self) -> dict[str, Any]:
        commercial = bool(getattr(self.provider, "commercial", False))
        return {"text": "Weather data by Open-Meteo.com", "url": "https://open-meteo.com/", "license": "CC BY 4.0", "commercial_plan": commercial,
                "note": "" if commercial else "The free Open-Meteo service is for non-commercial use. Commercial use needs an Open-Meteo licence (see docs/WEATHER.md)."}

    async def status(self) -> dict[str, Any]:
        prefs = await self.prefs()
        locs = await self.locations()
        p = self.provider
        out = []
        for loc in locs:
            st = self._status.get(str(loc["id"]), {})
            out.append({"id": loc["id"], "name": loc["name"], "last_ok": st.get("last_ok"), "last_try": st.get("last_try"), "last_error": st.get("last_error", ""), "next": st.get("next")})
        return {"provider": getattr(p, "name", "?"), "commercial": bool(getattr(p, "commercial", False)), "calls": getattr(p, "calls", 0), "failures": getattr(p, "failures", 0),
                "paused_until": getattr(p, "blocked_until", 0) or None, "redis": bool(self.shared is not None and getattr(self.shared, "active", False)), "cache_entries": len(self._mem),
                "locations": out, "refresh": prefs["refresh"], "alerts": prefs["alerts"]}

    # ------------------------------------------------------------------ rules
    async def seed_rules(self) -> None:
        if await self.db.kv_get("weather_rules_seeded"):
            return
        now = time.time()
        for name, var, op, thr, hrs, cat, cool, en in SEED_RULES:
            await self.db.insert("INSERT INTO weather_rules (name, kind, variable, op, threshold, window_hours, category, cooldown_minutes, enabled, created) VALUES (?, 'threshold', ?, ?, ?, ?, ?, ?, ?, ?)",
                                 (name, var, op, thr, hrs, cat, cool, en, now))
        await self.db.insert("INSERT INTO weather_rules (name, kind, variable, op, threshold, window_hours, category, cooldown_minutes, every_minutes, summary_time, enabled, created) VALUES ('Morning summary', 'summary', '', '>=', 0, 24, 'weather.summary', 720, 15, '07:00', 0, ?)", (now,))
        await self.db.kv_set("weather_rules_seeded", "1")

    async def rules(self) -> list[dict[str, Any]]:
        prefs = await self.prefs()
        out = []
        for r in await self.db.fetchall("SELECT * FROM weather_rules ORDER BY id"):
            out.append(self._rule_out(r, prefs))
        return out

    @staticmethod
    def _rule_out(r: dict[str, Any], prefs: dict[str, Any]) -> dict[str, Any]:
        v = r["variable"]
        shown = R.to_display(v, r["threshold"], prefs) if v in R.VARIABLES else None
        return {"id": r["id"], "name": r["name"], "kind": r["kind"], "variable": v, "variable_label": R.VARIABLES[v]["label"] if v in R.VARIABLES else "", "op": r["op"], "threshold": shown,
                "unit": R.unit_label(v, prefs) if v in R.VARIABLES else "", "window_hours": r["window_hours"], "location_id": r["location_id"], "category": r["category"],
                "cooldown_minutes": r["cooldown_minutes"], "every_minutes": r["every_minutes"], "active_from": r["active_from"], "active_to": r["active_to"], "summary_time": r["summary_time"], "enabled": bool(r["enabled"])}

    async def save_rule(self, rule_id: int | None, d: dict[str, Any]) -> dict[str, Any]:
        prefs = await self.prefs()
        cur = await self.db.fetchone("SELECT * FROM weather_rules WHERE id = ?", (rule_id,)) if rule_id else None
        if rule_id and not cur:
            raise WeatherServiceError("That rule no longer exists.", 404)
        m = {**(cur or {"kind": "threshold", "variable": "precip_probability", "op": ">=", "threshold": 70, "window_hours": 3, "category": "weather.rain", "cooldown_minutes": 180,
                        "every_minutes": 30, "active_from": "", "active_to": "", "summary_time": "07:00", "enabled": 1, "location_id": None, "name": "New rule"})}
        for k in ("name", "kind", "variable", "op", "window_hours", "category", "cooldown_minutes", "every_minutes", "active_from", "active_to", "summary_time", "enabled", "location_id"):
            if k in d and d[k] is not None or (k == "location_id" and k in d):
                m[k] = d[k]
        if m["kind"] not in ("threshold", "summary"):
            raise WeatherServiceError("Unknown rule kind.")
        if m["category"] not in CATEGORIES:
            raise WeatherServiceError("Pick one of the weather notification categories.")
        if m["kind"] == "threshold":
            if m["variable"] not in R.VARIABLES or m["op"] not in R.OPS:
                raise WeatherServiceError("Unknown variable or comparison.")
            if "threshold" in d and d["threshold"] is not None:
                m["threshold"] = R.to_canonical(m["variable"], float(d["threshold"]), prefs)
        for k, lo, hi in (("window_hours", 1, 72), ("cooldown_minutes", 15, 7 * 1440), ("every_minutes", 15, 1440)):
            if not isinstance(m[k], int) or not lo <= m[k] <= hi:
                raise WeatherServiceError(f"{k.replace('_', ' ').capitalize()} must be between {lo} and {hi}.")
        for k in ("active_from", "active_to", "summary_time"):
            if m[k] and not (len(m[k]) == 5 and m[k][2] == ":" and m[k][:2].isdigit() and m[k][3:].isdigit() and int(m[k][:2]) < 24 and int(m[k][3:]) < 60):
                raise WeatherServiceError("Times look like 07:30.")
        if m["location_id"] is not None and not await self.get_location(m["location_id"]):
            raise WeatherServiceError("That location no longer exists.", 404)
        m["name"] = " ".join(str(m["name"]).split())[:60] or "Rule"
        vals = (m["name"], m["kind"], m["variable"], m["op"], float(m["threshold"]), m["window_hours"], m["location_id"], m["category"], m["cooldown_minutes"], m["every_minutes"],
                m["active_from"], m["active_to"], m["summary_time"], int(bool(m["enabled"])))
        if rule_id:
            await self.db.execute("UPDATE weather_rules SET name=?, kind=?, variable=?, op=?, threshold=?, window_hours=?, location_id=?, category=?, cooldown_minutes=?, every_minutes=?, active_from=?, active_to=?, summary_time=?, enabled=? WHERE id=?", (*vals, rule_id))
        else:
            if (await self.db.fetchone("SELECT COUNT(*) AS n FROM weather_rules"))["n"] >= 40:
                raise WeatherServiceError("That is plenty of rules. Remove one first.")
            rule_id = await self.db.insert("INSERT INTO weather_rules (name, kind, variable, op, threshold, window_hours, location_id, category, cooldown_minutes, every_minutes, active_from, active_to, summary_time, enabled, created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (*vals, time.time()))
        await self.db.execute("DELETE FROM weather_alert_state WHERE rule_id = ?", (rule_id,))        # an edited rule starts fresh
        return self._rule_out(await self.db.fetchone("SELECT * FROM weather_rules WHERE id = ?", (rule_id,)), prefs)  # type: ignore[arg-type]

    async def delete_rule(self, rule_id: int) -> None:
        if not await self.db.execute("DELETE FROM weather_rules WHERE id = ?", (rule_id,)):
            raise WeatherServiceError("That rule no longer exists.", 404)
        await self.db.execute("DELETE FROM weather_alert_state WHERE rule_id = ?", (rule_id,))

    # ------------------------------------------------------------------ the scheduler hook
    async def tick(self, now: float) -> None:
        if now - self._last_tick < 60:
            return
        self._last_tick = now
        prefs = await self.prefs()
        default = await self.get_location()
        if default is None:
            return
        locs = await self.db.fetchall("SELECT * FROM weather_locations WHERE monitor = 1 OR is_default = 1")
        every = prefs["refresh"]["minutes"] * 60
        fresh: dict[int, dict[str, Any]] = {}
        for loc in locs:       # one request per location, shared by every rule and by the dashboard
            if not prefs["refresh"]["auto"] and not prefs["alerts"]["enabled"]:
                break
            st = self._status.get(str(loc["id"]), {})
            last = st.get("last_ok") or 0
            self._mark(loc["id"], next=max(now, last + every) if prefs["refresh"]["auto"] else None)
            if prefs["refresh"]["auto"] and now - last >= every:
                try:
                    fc, _ = await self.forecast(loc, force=True)
                    fresh[loc["id"]] = fc
                except WeatherServiceError:
                    pass
        if prefs["alerts"]["enabled"] and self.notifier is not None:
            await self._evaluate(now, prefs, default, locs)

    async def _evaluate(self, now: float, prefs: dict[str, Any], default: dict[str, Any], locs: list[dict[str, Any]]) -> None:
        by_id = {l["id"]: l for l in locs}
        for rule in await self.db.fetchall("SELECT * FROM weather_rules WHERE enabled = 1"):
            loc = by_id.get(rule["location_id"] or default["id"])
            if loc is None:
                continue           # the rule's place is not being monitored: never judge it by another city's forecast
            try:
                key = self._fkey(loc["lat"], loc["lon"])
                hit = await self._cache_get(key, float(self.cfg.get("weather_stale_max_hours")) * 3600)
                if not hit or now - hit[0] > max(float(self.cfg.get("weather_forecast_ttl_minutes")) * 60 * 8, prefs["refresh"]["minutes"] * 120):
                    continue       # never alert from data that is old; wait for a good refresh
                await self._evaluate_rule(rule, loc, hit[1], now, prefs)
            except Exception:
                logger.exception("Weather rule %s failed", rule["id"])

    @staticmethod
    def _in_schedule(rule: dict[str, Any], local: datetime) -> bool:
        a, b = rule["active_from"], rule["active_to"]
        if not a or not b or a == b:
            return True
        t = local.strftime("%H:%M")
        return a <= t < b if a < b else t >= a or t < b

    async def _evaluate_rule(self, rule: dict[str, Any], loc: dict[str, Any], fc: dict[str, Any], now: float, prefs: dict[str, Any]) -> None:
        tz = fc["timezone"]
        local = datetime.fromtimestamp(now, units.tzinfo(tz))
        state = await self.db.fetchone("SELECT * FROM weather_alert_state WHERE rule_id = ? AND location_id = ?", (rule["id"], loc["id"])) or {"active": 0, "last_sent": None, "last_eval": None, "signature": "", "last_value": None, "last_summary_date": ""}
        if state["last_eval"] and now - state["last_eval"] < rule["every_minutes"] * 60:
            return
        if not self._in_schedule(rule, local):
            return
        place = loc["name"]
        if rule["kind"] == "summary":
            today = local.strftime("%Y-%m-%d")
            if local.strftime("%H:%M") >= rule["summary_time"] and state["last_summary_date"] != today:
                title, body = R.day_summary(fc, place, prefs)
                await self.notifier.emit(rule["category"], title, body, key=f"{rule['id']}:{loc['id']}", route="#/weather", now=now)
                await self._save_state(rule["id"], loc["id"], state, now, active=0, last_sent=now, last_summary_date=today)
            else:
                await self._save_state(rule["id"], loc["id"], state, now)
            return
        res = R.evaluate(fc, rule["variable"], rule["op"], rule["threshold"], rule["window_hours"], now)
        if not res.hit:
            await self._save_state(rule["id"], loc["id"], state, now, active=0, last_value=res.value)    # condition ended: the rule is armed again
            return
        sig = datetime.fromtimestamp(res.first_ts or now, units.tzinfo(tz)).strftime("%Y-%m-%d")      # the day, not the hour: the first matching hour slides forward as time passes
        cooled = not state["last_sent"] or now - state["last_sent"] >= rule["cooldown_minutes"] * 60
        send = cooled and (not state["active"] or sig != state["signature"])
        if send:
            title, body = R.sentence(rule, res, place, tz, prefs)
            await self.notifier.emit(rule["category"], title, body, key=f"{rule['id']}:{loc['id']}", route="#/weather", now=now, data={"rule": rule["id"], "location": loc["id"]})
            await self._save_state(rule["id"], loc["id"], state, now, active=1, last_sent=now, signature=sig, last_value=res.value)
        else:
            await self._save_state(rule["id"], loc["id"], state, now, active=1, last_value=res.value)

    async def _save_state(self, rule_id: int, loc_id: int, old: dict[str, Any], now: float, **kw: Any) -> None:
        s = {**old, **kw, "last_eval": now}
        await self.db.execute("DELETE FROM weather_alert_state WHERE rule_id = ? AND location_id = ?", (rule_id, loc_id))
        await self.db.execute("INSERT INTO weather_alert_state (rule_id, location_id, active, last_sent, last_eval, signature, last_value, last_summary_date) VALUES (?,?,?,?,?,?,?,?)",
                              (rule_id, loc_id, s["active"], s["last_sent"], s["last_eval"], s["signature"], s["last_value"], s["last_summary_date"]))

    async def load(self) -> None:
        await self.seed_rules()
