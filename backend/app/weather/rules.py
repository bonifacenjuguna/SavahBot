"""Weather rules: a small, reusable evaluator. A rule says "for this location, when VARIABLE OP THRESHOLD within the next N hours, tell me".

Anything in SavahBot can call `evaluate()` on a normalized forecast; the weather service uses it for alerts. Thresholds are stored in metric.
"""
from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Any

from . import units
from .codes import describe


def _n(v):
    """Number for text; a missing value shows as a dash instead of crashing."""
    return "–" if v is None else f"{v:g}"


OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}

# variable -> (label, canonical unit kind, how to read it from an hourly row, how to combine hours)
VARIABLES: dict[str, dict[str, Any]] = {
    "precip_probability": {"label": "Chance of rain", "unit": "%", "kind": "pct", "field": "pop", "agg": max},
    "precipitation_total": {"label": "Rain amount", "unit": "precip", "kind": "precip", "field": "precip", "agg": "sum"},
    "temperature_max": {"label": "Highest temperature", "unit": "temp", "kind": "temp", "field": "temp", "agg": max},
    "temperature_min": {"label": "Lowest temperature", "unit": "temp", "kind": "temp", "field": "temp", "agg": min},
    "wind_speed_max": {"label": "Wind speed", "unit": "wind", "kind": "wind", "field": "wind", "agg": max},
    "wind_gust_max": {"label": "Wind gusts", "unit": "wind", "kind": "wind", "field": "gust", "agg": max},
    "thunderstorm": {"label": "Thunderstorm", "unit": "", "kind": "flag", "field": "cond", "agg": "storm"},
}


@dataclass
class Result:
    value: float | None
    hit: bool
    first_ts: float | None     # first hour that meets the condition
    peak_ts: float | None      # the hour with the extreme value


def window(forecast: dict[str, Any], now: float, hours: int) -> list[dict[str, Any]]:
    """The hourly rows from the current hour up to `hours` ahead."""
    rows = [h for h in forecast["hourly"] if now - 3600 < h["ts"] <= now + max(1, hours) * 3600]
    return rows


def evaluate(forecast: dict[str, Any], variable: str, op: str, threshold: float, hours: int, now: float) -> Result:
    spec = VARIABLES.get(variable)
    if spec is None or op not in OPS:
        raise ValueError(f"Unknown rule: {variable} {op}")
    rows = window(forecast, now, hours)
    cmp = OPS[op]
    if spec["agg"] == "storm":
        hits = [h["ts"] for h in rows if h["cond"]["id"] == "thunderstorm"]
        return Result(1.0 if hits else 0.0, bool(hits), hits[0] if hits else None, hits[0] if hits else None)
    vals = [(h["ts"], h[spec["field"]]) for h in rows if h.get(spec["field"]) is not None]
    if not vals:
        return Result(None, False, None, None)
    if spec["agg"] == "sum":
        total = round(sum(v for _, v in vals), 2)
        hits = [t for t, _ in vals if cmp(total, threshold)]
        return Result(total, cmp(total, threshold), vals[0][0] if cmp(total, threshold) else None, max(vals, key=lambda x: x[1])[0])
    best = spec["agg"](vals, key=lambda x: x[1])
    first = next((t for t, v in vals if cmp(v, threshold)), None)
    return Result(best[1], cmp(best[1], threshold), first, best[0])


def to_display(variable: str, canonical: float, prefs: dict[str, Any]) -> float:
    kind = VARIABLES[variable]["kind"]
    return {"temp": lambda v: units.temp(v, prefs["temp"]), "wind": lambda v: units.wind(v, prefs["wind"]), "precip": lambda v: units.precip(v, prefs["precip"])}.get(kind, lambda v: round(v, 1))(canonical)  # type: ignore[return-value]


def to_canonical(variable: str, shown: float, prefs: dict[str, Any]) -> float:
    kind = VARIABLES[variable]["kind"]
    return {"temp": lambda v: units.temp_back(v, prefs["temp"]), "wind": lambda v: units.wind_back(v, prefs["wind"]), "precip": lambda v: units.precip_back(v, prefs["precip"])}.get(kind, lambda v: v)(shown)


def unit_label(variable: str, prefs: dict[str, Any]) -> str:
    u = VARIABLES[variable]["unit"]
    return {"temp": units.TEMP[prefs["temp"]], "wind": units.WIND[prefs["wind"]], "precip": units.PRECIP[prefs["precip"]]}.get(u, u)


def sentence(rule: dict[str, Any], res: Result, place: str, tz: str, prefs: dict[str, Any]) -> tuple[str, str]:
    """(title, body) for an alert. Always says that this is SavahBot's own forecast-based alert, not an official warning."""
    v = rule["variable"]
    shown = to_display(v, res.value, prefs) if res.value is not None else None
    lab = unit_label(v, prefs)
    at = f" around {units.clock(res.peak_ts, tz, prefs['clock'] == '24')}" if res.peak_ts else ""
    h = rule["window_hours"]
    core = {
        "precip_probability": f"Up to {_n(shown)}{lab} chance of rain in the next {h} h{at}.",
        "precipitation_total": f"About {_n(shown)} {lab} of rain expected in the next {h} h.",
        "temperature_max": f"Temperatures up to {_n(shown)}{lab} in the next {h} h{at}.",
        "temperature_min": f"Temperatures down to {_n(shown)}{lab} in the next {h} h{at}.",
        "wind_speed_max": f"Wind up to {_n(shown)} {lab} in the next {h} h{at}.",
        "wind_gust_max": f"Gusts up to {_n(shown)} {lab} in the next {h} h{at}.",
        "thunderstorm": f"Thunderstorms in the forecast within {h} h{at}.",
    }[v] if shown is not None or v == "thunderstorm" else "Conditions changed."
    return f"{rule['name']}: {place}", f"{core} Forecast alert from SavahBot, not an official warning."


def day_summary(forecast: dict[str, Any], place: str, prefs: dict[str, Any]) -> tuple[str, str]:
    d = forecast["daily"][0] if forecast["daily"] else None
    c = forecast["current"]
    if d is None:
        return f"Today in {place}", "No forecast available."
    t, w, p = prefs["temp"], prefs["wind"], prefs["precip"]
    lab = units.labels(prefs)
    bits = [f"{describe(d['code'], True)['label']}", f"{_n(units.temp(d['tmin'], t))} to {_n(units.temp(d['tmax'], t))}{lab['temp']}"]
    if d.get("pop") is not None:
        bits.append(f"{_n(d['pop'])}% chance of rain" + (f", {_n(units.precip(d['precip'], p))} {lab['precip']}" if d.get("precip") else ""))
    if d.get("gust") is not None:
        bits.append(f"gusts to {_n(units.wind(d['gust'], w))} {lab['wind']}")
    return f"Today in {place}", "; ".join(bits) + "."
