"""Weather providers. `WeatherProvider` is the interface the rest of SavahBot uses; `OpenMeteo` is the first implementation.

Providers return NORMALIZED data in fixed metric units (degrees C, km/h, mm, metres). Unit preferences are applied later, on the
way out to the dashboard or Telegram, so one cached forecast serves every unit choice.
Verified against the Open-Meteo docs (forecast + geocoding): `timezone=auto`, `forecast_days` 0-16, error body `{"error": true, "reason": "..."}`.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..http import NetworkError, request_json

logger = logging.getLogger("savahbot.weather")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
# A paid Open-Meteo plan uses these hosts plus `apikey`. Only these fixed, https addresses are ever called: there is no setting for a custom URL.
COMMERCIAL_FORECAST_URL = "https://customer-api.open-meteo.com/v1/forecast"
COMMERCIAL_GEOCODE_URL = "https://customer-geocoding-api.open-meteo.com/v1/search"

CURRENT = "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,cloud_cover,wind_speed_10m,wind_direction_10m,wind_gusts_10m,surface_pressure"
HOURLY = "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation_probability,precipitation,weather_code,cloud_cover,visibility,wind_speed_10m,wind_direction_10m,wind_gusts_10m,is_day,uv_index"
DAILY = "weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,sunrise,sunset,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,uv_index_max"


class WeatherError(Exception):
    """kind: invalid (bad input or coordinates) | rate_limit | timeout | unavailable | malformed"""

    def __init__(self, message: str, kind: str = "unavailable") -> None:
        super().__init__(message)
        self.message, self.kind = message, kind


def valid_coords(lat: Any, lon: Any) -> tuple[float, float]:
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        raise WeatherError("Latitude and longitude must be numbers.", "invalid") from None
    if not (math.isfinite(la) and math.isfinite(lo)) or not -90 <= la <= 90 or not -180 <= lo <= 180:
        raise WeatherError("Latitude must be between -90 and 90 and longitude between -180 and 180.", "invalid")
    return round(la, 4), round(lo, 4)


class WeatherProvider(Protocol):
    name: str
    async def search(self, query: str, count: int = 8, language: str = "en") -> list[dict[str, Any]]: ...
    async def forecast(self, lat: float, lon: float, timezone: str = "auto", days: int = 7) -> dict[str, Any]: ...


# ------------------------------------------------------------------ normalization (pure; unit tested with recorded responses)
def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _epoch(local_iso: str, tz: ZoneInfo | None, offset: int) -> float | None:
    try:
        naive = datetime.fromisoformat(local_iso)
    except (TypeError, ValueError):
        return None
    if tz is not None:
        return naive.replace(tzinfo=tz).timestamp()
    return (naive - datetime(1970, 1, 1)).total_seconds() - offset


def normalize_forecast(raw: Any, now: float) -> dict[str, Any]:
    """Open-Meteo forecast JSON -> SavahBot's internal shape. Raises WeatherError('malformed') when it cannot be trusted."""
    from .codes import describe
    if not isinstance(raw, dict) or raw.get("error"):
        raise WeatherError(str((raw or {}).get("reason", "unexpected answer")) if isinstance(raw, dict) else "unexpected answer", "malformed")
    la, lo = _num(raw.get("latitude")), _num(raw.get("longitude"))
    hourly, daily, cur = raw.get("hourly"), raw.get("daily"), raw.get("current")
    if la is None or lo is None or not isinstance(hourly, dict) or not isinstance(daily, dict) or not isinstance(cur, dict):
        raise WeatherError("The weather service sent an incomplete answer.", "malformed")
    tzname = str(raw.get("timezone") or "UTC")
    offset = int(_num(raw.get("utc_offset_seconds")) or 0)
    try:
        tz: ZoneInfo | None = ZoneInfo(tzname)
    except (ZoneInfoNotFoundError, ValueError):
        tz = None

    def col(block: dict[str, Any], key: str, n: int) -> list[Any]:
        v = block.get(key)
        return v if isinstance(v, list) and len(v) == n else [None] * n

    ht = hourly.get("time")
    if not isinstance(ht, list) or not ht:
        raise WeatherError("The hourly forecast is missing.", "malformed")
    dt = daily.get("time")
    if not isinstance(dt, list) or not dt:
        raise WeatherError("The daily forecast is missing.", "malformed")
    n = len(ht)
    c = {k: col(hourly, k, n) for k in HOURLY.split(",")}
    hours = []
    for i, t in enumerate(ht):
        ts = _epoch(t, tz, offset)
        if ts is None:
            continue
        day = bool(c["is_day"][i]) if c["is_day"][i] is not None else True
        hours.append({"ts": ts, "time": t, "temp": _num(c["temperature_2m"][i]), "feels": _num(c["apparent_temperature"][i]), "humidity": _num(c["relative_humidity_2m"][i]),
                      "pop": _num(c["precipitation_probability"][i]), "precip": _num(c["precipitation"][i]), "code": _num(c["weather_code"][i]), "cloud": _num(c["cloud_cover"][i]),
                      "visibility": _num(c["visibility"][i]), "wind": _num(c["wind_speed_10m"][i]), "wind_dir": _num(c["wind_direction_10m"][i]), "gust": _num(c["wind_gusts_10m"][i]),
                      "is_day": day, "uv": _num(c["uv_index"][i]), "cond": describe(_num(c["weather_code"][i]), day)})
    m = len(dt)
    d = {k: col(daily, k, m) for k in DAILY.split(",")}
    days = []
    for i, date in enumerate(dt):
        days.append({"date": str(date)[:10], "code": _num(d["weather_code"][i]), "tmax": _num(d["temperature_2m_max"][i]), "tmin": _num(d["temperature_2m_min"][i]),
                     "feels_max": _num(d["apparent_temperature_max"][i]), "feels_min": _num(d["apparent_temperature_min"][i]),
                     "sunrise": _epoch(d["sunrise"][i], tz, offset) if d["sunrise"][i] else None, "sunset": _epoch(d["sunset"][i], tz, offset) if d["sunset"][i] else None,
                     "precip": _num(d["precipitation_sum"][i]), "pop": _num(d["precipitation_probability_max"][i]), "wind": _num(d["wind_speed_10m_max"][i]),
                     "gust": _num(d["wind_gusts_10m_max"][i]), "uv": _num(d["uv_index_max"][i]), "cond": describe(_num(d["weather_code"][i]), True)})
    cts = _epoch(cur.get("time"), tz, offset) if cur.get("time") else None
    cday = bool(cur.get("is_day", 1))
    # visibility is not offered as a "current" value, so take the hour we are in
    vis = None
    if cts is not None:
        near = min(hours, key=lambda h: abs(h["ts"] - cts), default=None)
        vis = near["visibility"] if near else None
    current = {"ts": cts or now, "temp": _num(cur.get("temperature_2m")), "feels": _num(cur.get("apparent_temperature")), "humidity": _num(cur.get("relative_humidity_2m")),
               "is_day": cday, "precip": _num(cur.get("precipitation")), "code": _num(cur.get("weather_code")), "cloud": _num(cur.get("cloud_cover")),
               "wind": _num(cur.get("wind_speed_10m")), "wind_dir": _num(cur.get("wind_direction_10m")), "gust": _num(cur.get("wind_gusts_10m")),
               "pressure": _num(cur.get("surface_pressure")), "visibility": vis, "cond": describe(_num(cur.get("weather_code")), cday)}
    if current["temp"] is None:
        raise WeatherError("The weather service sent no current temperature.", "malformed")
    return {"provider": "open-meteo", "fetched_at": now, "timezone": tzname, "utc_offset": offset, "lat": la, "lon": lo, "elevation": _num(raw.get("elevation")),
            "current": current, "hourly": hours, "daily": days}


def normalize_places(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        raise WeatherError("The search service sent an unexpected answer.", "malformed")
    if raw.get("error"):
        raise WeatherError(str(raw.get("reason", "search failed")), "invalid")
    out = []
    for r in raw.get("results") or []:      # the key is simply absent when nothing matches
        la, lo = _num(r.get("latitude")), _num(r.get("longitude"))
        if la is None or lo is None or not r.get("name"):
            continue
        out.append({"name": str(r["name"]), "admin1": str(r.get("admin1") or ""), "admin2": str(r.get("admin2") or ""), "country": str(r.get("country") or ""),
                    "country_code": str(r.get("country_code") or ""), "lat": round(la, 4), "lon": round(lo, 4), "timezone": str(r.get("timezone") or ""),
                    "elevation": _num(r.get("elevation")), "population": int(_num(r.get("population")) or 0), "feature": str(r.get("feature_code") or "")})
    return out


# ------------------------------------------------------------------ Open-Meteo
class OpenMeteo:
    name = "open-meteo"

    def __init__(self, timeout: float = 8.0, retries: int = 2, api_key: str = "") -> None:
        self.timeout, self.retries, self.api_key = timeout, max(0, retries), api_key.strip()
        self.failures = 0
        self.blocked_until = 0.0
        self.calls = 0

    @property
    def commercial(self) -> bool:
        return bool(self.api_key)

    async def _get(self, url: str, params: dict[str, Any]) -> Any:
        now = time.time()
        if now < self.blocked_until:
            raise WeatherError("The weather service is being given a rest after repeated problems. Trying again shortly.", "unavailable")
        if self.api_key:
            params = {**params, "apikey": self.api_key}
        last: WeatherError | None = None
        for attempt in range(self.retries + 1):
            if attempt:
                await asyncio.sleep(min(4.0, 0.6 * 2 ** (attempt - 1)))     # growing pause between tries
            self.calls += 1
            try:
                status, data = await request_json("GET", url, params=params, timeout=self.timeout, max_bytes=2_000_000)
            except NetworkError as exc:
                last = WeatherError(f"Could not reach the weather service ({exc}).", "timeout" if "timed out" in str(exc).lower() else "unavailable")
                continue
            if status == 200:
                self.failures = 0
                return data
            reason = str(data.get("reason")) if isinstance(data, dict) and data.get("reason") else f"HTTP {status}"
            if status == 429:
                self._trip(300)
                raise WeatherError("Open-Meteo says too many requests were made. Waiting a few minutes.", "rate_limit")
            if status in (400, 404, 422):
                raise WeatherError(reason, "invalid")      # our request is wrong: retrying will not change that
            last = WeatherError(f"The weather service answered {status}.", "unavailable")
        self._trip()
        raise last or WeatherError("The weather service did not answer.", "unavailable")

    def _trip(self, seconds: float | None = None) -> None:
        self.failures += 1
        self.blocked_until = time.time() + (seconds if seconds is not None else min(900, 30 * 2 ** min(self.failures, 5)))

    async def search(self, query: str, count: int = 8, language: str = "en") -> list[dict[str, Any]]:
        q = " ".join((query or "").split())[:100]
        if len(q) < 2:
            raise WeatherError("Type at least two letters.", "invalid")
        url = COMMERCIAL_GEOCODE_URL if self.api_key else GEOCODE_URL
        return normalize_places(await self._get(url, {"name": q, "count": max(1, min(int(count), 20)), "language": language[:5] or "en", "format": "json"}))

    async def forecast(self, lat: float, lon: float, timezone: str = "auto", days: int = 7) -> dict[str, Any]:
        la, lo = valid_coords(lat, lon)
        url = COMMERCIAL_FORECAST_URL if self.api_key else FORECAST_URL
        raw = await self._get(url, {"latitude": la, "longitude": lo, "current": CURRENT, "hourly": HOURLY, "daily": DAILY, "timezone": "auto", "forecast_days": max(1, min(int(days), 16))})
        return normalize_forecast(raw, time.time())
