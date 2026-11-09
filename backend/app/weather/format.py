"""Telegram text for weather. Pure functions over `WeatherService.overview()` output, so the formatting is testable without Telegram."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..services import telegram_ui as ui
from ..services.telegram_ui import esc
from . import units
from .codes import compass


def _n(v):
    """Number for text; a missing value shows as a dash instead of crashing."""
    return "–" if v is None else f"{v:g}"


ICON = {"sun": "☀️", "moon": "🌙", "cloudSun": "⛅", "cloudMoon": "☁️", "cloud": "☁️", "cloudFog": "🌫", "cloudDrizzle": "🌦", "cloudRain": "🌧", "snowflake": "❄️", "cloudLightning": "⛈"}
FOOT = "Weather data by Open-Meteo.com"


def _ic(cond: dict[str, str]) -> str:
    return ICON.get(cond["icon"], "🌡")


def _clock(ts: float | None, tz: str, p: dict[str, Any]) -> str:
    return units.clock(ts, tz, p["clock"] == "24")


def _stale(meta: dict[str, Any]) -> str:
    if not meta.get("stale"):
        return ""
    mins = max(1, meta["age_seconds"] // 60)
    return f"\n⚠️ <b>Old data</b>: Open-Meteo could not be reached, this is from {mins // 60} h {mins % 60} min ago." if mins >= 60 else f"\n⚠️ <b>Old data</b>: from {mins} min ago, the service could not be reached."


def place(o: dict[str, Any]) -> str:
    loc = o["location"]
    return esc(", ".join(x for x in (loc["name"], loc["admin1"], loc["country"]) if x))


def now_text(o: dict[str, Any]) -> str:
    c, u, p, tz = o["current"], o["units"], o["prefs"], o["timezone"]
    d = o["daily"][0] if o["daily"] else None
    rows = [f"{_ic(c['cond'])} <b>{_n(c['temp'])}{u['temp']}</b>  {esc(c['cond']['label'])}",
            f"Feels like {_n(c['feels'])}{u['temp']}" if c["feels"] is not None else "",
            f"💧 Humidity {_n(c['humidity'])}%" if c["humidity"] is not None else "",
            f"💨 Wind {_n(c['wind'])} {u['wind']} {compass(c['wind_dir'])}" + (f", gusts {_n(c['gust'])}" if c["gust"] else "") if c["wind"] is not None else "",
            f"☔ Rain now {_n(c['precip'])} {u['precip']}" if c["precip"] else "",
            f"☁️ Cloud cover {_n(c['cloud'])}%" if c["cloud"] is not None else ""]
    if d:
        rows.append(f"📈 Today {_n(d['tmin'])} to {_n(d['tmax'])}{u['temp']}" + (f" · rain chance {_n(d['pop'])}%" if d["pop"] is not None else ""))
        if d["sunrise"] and d["sunset"]:
            rows.append(f"🌅 {_clock(d['sunrise'], tz, p)}   🌇 {_clock(d['sunset'], tz, p)}")
    return ui.card(f"Weather in {place(o)}", [r for r in rows if r], FOOT + _stale(o["meta"]), "🌍")


def forecast_text(o: dict[str, Any], days: int = 5) -> str:
    u, rows = o["units"], []
    for d in o["daily"][:days]:
        name = datetime.strptime(d["date"], "%Y-%m-%d").strftime("%a %d")
        rain = f" · {_n(d['pop'])}%" if d["pop"] is not None else ""
        rows.append(f"{_ic(d['cond'])} <b>{name}</b>  {_n(d['tmin'])} to {_n(d['tmax'])}{u['temp']}{rain}  {esc(d['cond']['label'])}")
    return ui.card(f"Forecast for {place(o)}", rows or ["No forecast available."], FOOT + _stale(o["meta"]), "📅")


def hourly_text(o: dict[str, Any], hours: int = 12) -> str:
    u, p, tz, rows = o["units"], o["prefs"], o["timezone"], []
    for h in o["hourly"][:hours]:
        rain = f" · {_n(h['pop'])}%" if h["pop"] is not None else ""
        rows.append(f"<code>{_clock(h['ts'], tz, p):>8}</code> {_ic(h['cond'])} {_n(h['temp'])}{u['temp']}{rain} · {_n(h['wind'])} {u['wind']}")
    return ui.card(f"Next hours in {place(o)}", rows or ["No hourly data."], FOOT + _stale(o["meta"]), "🕒")


def locations_text(locs: list[dict[str, Any]]) -> str:
    rows = [f"{i}. {'⭐ ' if l['default'] else ''}{esc(l['label'])}" for i, l in enumerate(locs, 1)]
    return ui.card("Saved locations", rows or ["None yet. Add one on the dashboard (Weather), or send /weather <place>."], "Make one the default with /locations <number>.", "📍")
