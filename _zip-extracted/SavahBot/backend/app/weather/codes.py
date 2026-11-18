"""WMO weather interpretation codes as Open-Meteo reports them (verified against the Open-Meteo forecast docs).

`describe(code, is_day)` returns a stable condition id, a plain label, and the name of a dashboard icon. Every other part of
SavahBot works with these, never with raw codes.
"""
from __future__ import annotations

# code -> (condition id, label, icon day, icon night)
TABLE: dict[int, tuple[str, str, str, str]] = {
    0: ("clear", "Clear sky", "sun", "moon"),
    1: ("mostly_clear", "Mainly clear", "sun", "moon"),
    2: ("partly_cloudy", "Partly cloudy", "cloudSun", "cloudMoon"),
    3: ("overcast", "Overcast", "cloud", "cloud"),
    45: ("fog", "Fog", "cloudFog", "cloudFog"),
    48: ("fog", "Freezing fog", "cloudFog", "cloudFog"),
    51: ("drizzle", "Light drizzle", "cloudDrizzle", "cloudDrizzle"),
    53: ("drizzle", "Drizzle", "cloudDrizzle", "cloudDrizzle"),
    55: ("drizzle", "Dense drizzle", "cloudDrizzle", "cloudDrizzle"),
    56: ("freezing_rain", "Light freezing drizzle", "cloudDrizzle", "cloudDrizzle"),
    57: ("freezing_rain", "Freezing drizzle", "cloudDrizzle", "cloudDrizzle"),
    61: ("rain", "Light rain", "cloudRain", "cloudRain"),
    63: ("rain", "Rain", "cloudRain", "cloudRain"),
    65: ("heavy_rain", "Heavy rain", "cloudRain", "cloudRain"),
    66: ("freezing_rain", "Light freezing rain", "cloudRain", "cloudRain"),
    67: ("freezing_rain", "Heavy freezing rain", "cloudRain", "cloudRain"),
    71: ("snow", "Light snow", "snowflake", "snowflake"),
    73: ("snow", "Snow", "snowflake", "snowflake"),
    75: ("heavy_snow", "Heavy snow", "snowflake", "snowflake"),
    77: ("snow", "Snow grains", "snowflake", "snowflake"),
    80: ("showers", "Light rain showers", "cloudRain", "cloudRain"),
    81: ("showers", "Rain showers", "cloudRain", "cloudRain"),
    82: ("heavy_rain", "Violent rain showers", "cloudRain", "cloudRain"),
    85: ("snow", "Light snow showers", "snowflake", "snowflake"),
    86: ("heavy_snow", "Heavy snow showers", "snowflake", "snowflake"),
    95: ("thunderstorm", "Thunderstorm", "cloudLightning", "cloudLightning"),
    96: ("thunderstorm", "Thunderstorm with hail", "cloudLightning", "cloudLightning"),
    97: ("thunderstorm", "Heavy thunderstorm", "cloudLightning", "cloudLightning"),
    99: ("thunderstorm", "Thunderstorm with heavy hail", "cloudLightning", "cloudLightning"),
}

SEVERE = {"thunderstorm", "heavy_rain", "heavy_snow", "freezing_rain"}
WET = {"drizzle", "rain", "showers", "heavy_rain", "freezing_rain", "snow", "heavy_snow", "thunderstorm"}


def describe(code: int | None, is_day: bool = True) -> dict[str, str]:
    """Unknown or missing codes degrade to a neutral 'Unknown' instead of raising."""
    row = TABLE.get(int(code)) if code is not None and isinstance(code, (int, float)) else None
    if row is None:
        return {"id": "unknown", "label": "Unknown", "icon": "cloud"}
    return {"id": row[0], "label": row[1], "icon": row[2] if is_day else row[3]}


COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


def compass(deg: float | None) -> str:
    return "" if deg is None else COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]
