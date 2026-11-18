"""Unit handling. Everything inside SavahBot is metric (C, km/h, mm, m, hPa); these helpers convert on the way out and back in."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TEMP = {"c": "°C", "f": "°F"}
WIND = {"kmh": "km/h", "ms": "m/s", "mph": "mph", "kn": "kn"}
PRECIP = {"mm": "mm", "in": "in"}
_WIND_FROM_KMH = {"kmh": 1.0, "ms": 1 / 3.6, "mph": 0.621371, "kn": 0.539957}


def temp(v: float | None, u: str) -> float | None:
    return None if v is None else round(v * 9 / 5 + 32, 1) if u == "f" else round(v, 1)


def temp_back(v: float, u: str) -> float:
    return (v - 32) * 5 / 9 if u == "f" else v


def wind(v: float | None, u: str) -> float | None:
    return None if v is None else round(v * _WIND_FROM_KMH.get(u, 1.0), 1)


def wind_back(v: float, u: str) -> float:
    return v / _WIND_FROM_KMH.get(u, 1.0)


def precip(v: float | None, u: str) -> float | None:
    return None if v is None else round(v / 25.4, 2) if u == "in" else round(v, 1)


def precip_back(v: float, u: str) -> float:
    return v * 25.4 if u == "in" else v


def vis(metres: float | None, u: str) -> float | None:
    if metres is None:
        return None
    return round(metres / 1609.344, 1) if u == "mph" else round(metres / 1000, 1)


def labels(p: dict[str, Any]) -> dict[str, str]:
    return {"temp": TEMP[p["temp"]], "wind": WIND[p["wind"]], "precip": PRECIP[p["precip"]], "vis": "mi" if p["wind"] == "mph" else "km", "pressure": "hPa"}


def tzinfo(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def clock(ts: float | None, tz: str, h24: bool = True) -> str:
    if ts is None:
        return ""
    d = datetime.fromtimestamp(ts, tzinfo(tz))
    return d.strftime("%H:%M") if h24 else d.strftime("%I:%M %p").lstrip("0")


# ---- convert a normalized forecast (metric) to the owner's units for display
def convert_current(c: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    return {**c, "temp": temp(c["temp"], p["temp"]), "feels": temp(c["feels"], p["temp"]), "precip": precip(c["precip"], p["precip"]), "wind": wind(c["wind"], p["wind"]),
            "gust": wind(c["gust"], p["wind"]), "visibility": vis(c["visibility"], p["wind"])}


def convert_hour(h: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    return {**h, "temp": temp(h["temp"], p["temp"]), "feels": temp(h["feels"], p["temp"]), "precip": precip(h["precip"], p["precip"]), "wind": wind(h["wind"], p["wind"]),
            "gust": wind(h["gust"], p["wind"]), "visibility": vis(h["visibility"], p["wind"])}


def convert_day(d: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    return {**d, "tmax": temp(d["tmax"], p["temp"]), "tmin": temp(d["tmin"], p["temp"]), "feels_max": temp(d["feels_max"], p["temp"]), "feels_min": temp(d["feels_min"], p["temp"]),
            "precip": precip(d["precip"], p["precip"]), "wind": wind(d["wind"], p["wind"]), "gust": wind(d["gust"], p["wind"])}
