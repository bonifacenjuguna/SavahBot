"""Weather API. Owner-only like everything else; the dashboard never talks to a weather provider itself."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request

from ..weather import WeatherServiceError
from ..weather import rules as R
from .routes import ApiError, R as ROUTES, parse

MIN_MANUAL_REFRESH = 60      # seconds between forced provider calls for one place: stays inside Open-Meteo's fair use


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewLocation(_In):
    model_config = ConfigDict(extra="ignore")      # a search result is sent back as it came; unknown fields (population...) are dropped

    name: str = Field(default="", max_length=80)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    admin1: str = Field(default="", max_length=80)
    country: str = Field(default="", max_length=80)
    country_code: str = Field(default="", max_length=3)
    timezone: str = Field(default="", max_length=60)
    elevation: float | None = None
    make_default: bool = False


class LocationPatch(_In):
    name: str | None = Field(default=None, max_length=80)
    monitor: bool | None = None


class Show(_In):
    current: bool | None = None
    hourly: bool | None = None
    daily: bool | None = None
    precip: bool | None = None
    wind: bool | None = None
    sun: bool | None = None
    details: bool | None = None


class Refresh(_In):
    auto: bool | None = None
    minutes: int | None = Field(default=None, ge=15, le=180)


class Prefs(_In):
    temp: Literal["c", "f"] | None = None
    wind: Literal["kmh", "ms", "mph", "kn"] | None = None
    precip: Literal["mm", "in"] | None = None
    clock: Literal["12", "24"] | None = None
    horizon_hours: Literal[12, 24, 48, 72] | None = None
    daily_days: Literal[3, 5, 7, 10, 14] | None = None
    offer_device_location: bool | None = None
    show: Show | None = None
    refresh: Refresh | None = None
    alerts: dict[Literal["enabled"], bool] | None = None


class Rule(_In):
    name: str | None = Field(default=None, max_length=60)
    kind: Literal["threshold", "summary"] | None = None
    variable: str | None = Field(default=None, max_length=40)
    op: Literal[">", ">=", "<", "<="] | None = None
    threshold: float | None = None
    window_hours: int | None = Field(default=None, ge=1, le=72)
    location_id: int | None = None
    category: str | None = Field(default=None, max_length=40)
    cooldown_minutes: int | None = Field(default=None, ge=15, le=7 * 1440)
    every_minutes: int | None = Field(default=None, ge=15, le=1440)
    active_from: str | None = Field(default=None, max_length=5)
    active_to: str | None = Field(default=None, max_length=5)
    summary_time: str | None = Field(default=None, max_length=5)
    enabled: bool | None = None


class RefreshBody(_In):
    location_id: int | None = None


def _guard(fn: Any) -> Any:
    async def wrapped(request: Request, c: Any) -> dict:
        try:
            return await fn(request, c)
        except WeatherServiceError as exc:
            raise ApiError(exc.message, exc.status) from None
    wrapped.__name__ = fn.__name__
    return wrapped


def _loc_id(request: Request) -> int | None:
    v = request.query_params.get("location")
    return int(v) if v and v.isdigit() else None


@ROUTES.add("/weather/overview", ["GET"])
@_guard
async def overview(request: Request, c: Any) -> dict:
    return await c.weather.overview(_loc_id(request))


@ROUTES.add("/weather/current", ["GET"])
@_guard
async def current(request: Request, c: Any) -> dict:
    o = await c.weather.overview(_loc_id(request))
    return {k: o.get(k) for k in ("location", "current", "units", "meta", "attribution")}


@ROUTES.add("/weather/hourly", ["GET"])
@_guard
async def hourly(request: Request, c: Any) -> dict:
    o = await c.weather.overview(_loc_id(request))
    return {k: o.get(k) for k in ("location", "hourly", "units", "meta", "attribution", "timezone")}


@ROUTES.add("/weather/daily", ["GET"])
@_guard
async def daily(request: Request, c: Any) -> dict:
    o = await c.weather.overview(_loc_id(request))
    return {k: o.get(k) for k in ("location", "daily", "units", "meta", "attribution", "timezone")}


@ROUTES.add("/weather/search", ["GET"])
@_guard
async def search(request: Request, c: Any) -> dict:
    return {"results": await c.weather.search(request.query_params.get("q", ""), 8)}


@ROUTES.add("/weather/locations", ["GET"])
@_guard
async def locations(request: Request, c: Any) -> dict:
    return {"locations": await c.weather.locations()}


@ROUTES.add("/weather/locations", ["POST"])
@_guard
async def add_location(request: Request, c: Any) -> dict:
    b = await parse(request, NewLocation)
    loc = await c.weather.add_location(**b.model_dump())
    return {"location": loc, "locations": await c.weather.locations()}


@ROUTES.add("/weather/locations/{loc_id:int}", ["PATCH"])
@_guard
async def patch_location(request: Request, c: Any) -> dict:
    b = await parse(request, LocationPatch)
    await c.weather.update_location(request.path_params["loc_id"], b.name, b.monitor)
    return {"locations": await c.weather.locations()}


@ROUTES.add("/weather/locations/{loc_id:int}", ["DELETE"])
@_guard
async def delete_location(request: Request, c: Any) -> dict:
    await c.weather.remove_location(request.path_params["loc_id"])
    return {"locations": await c.weather.locations()}


@ROUTES.add("/weather/locations/{loc_id:int}/default", ["POST"])
@_guard
async def default_location(request: Request, c: Any) -> dict:
    await c.weather.set_default(request.path_params["loc_id"])
    return {"locations": await c.weather.locations()}


@ROUTES.add("/weather/prefs", ["GET"])
@_guard
async def prefs(request: Request, c: Any) -> dict:
    return await c.weather.prefs()


@ROUTES.add("/weather/prefs", ["PATCH", "PUT"])
@_guard
async def set_prefs(request: Request, c: Any) -> dict:
    b = await parse(request, Prefs)
    return await c.weather.set_prefs(b.model_dump(exclude_none=True))


@ROUTES.add("/weather/refresh", ["POST"])
@_guard
async def refresh(request: Request, c: Any) -> dict:
    import time
    b = await parse(request, RefreshBody)
    loc = await c.weather.get_location(b.location_id)
    if loc is None:
        raise ApiError("Choose a location first.", 400)
    st = c.weather._status.get(str(loc["id"]), {})
    recent = bool(st.get("last_ok") and time.time() - st["last_ok"] < MIN_MANUAL_REFRESH)
    o = await c.weather.overview(loc["id"], force=not recent)
    return {**o, "throttled": recent}


@ROUTES.add("/weather/status", ["GET"])
@_guard
async def status(request: Request, c: Any) -> dict:
    return await c.weather.status()


@ROUTES.add("/weather/catalog", ["GET"])
@_guard
async def catalog(request: Request, c: Any) -> dict:
    p = await c.weather.prefs()
    from ..weather import CATEGORIES
    from ..notify import categories as cats
    return {"variables": [{"id": k, "label": v["label"], "unit": R.unit_label(k, p)} for k, v in R.VARIABLES.items()], "ops": list(R.OPS),
            "categories": [{"id": i, "label": cats.REGISTRY[i].label} for i in CATEGORIES]}


@ROUTES.add("/weather/rules", ["GET"])
@_guard
async def rules(request: Request, c: Any) -> dict:
    return {"rules": await c.weather.rules()}


@ROUTES.add("/weather/rules", ["POST"])
@_guard
async def create_rule(request: Request, c: Any) -> dict:
    b = await parse(request, Rule)
    return {"rule": await c.weather.save_rule(None, b.model_dump(exclude_unset=True)), "rules": await c.weather.rules()}


@ROUTES.add("/weather/rules/{rule_id:int}", ["PATCH"])
@_guard
async def patch_rule(request: Request, c: Any) -> dict:
    b = await parse(request, Rule)
    return {"rule": await c.weather.save_rule(request.path_params["rule_id"], b.model_dump(exclude_unset=True)), "rules": await c.weather.rules()}


@ROUTES.add("/weather/rules/{rule_id:int}", ["DELETE"])
@_guard
async def delete_rule(request: Request, c: Any) -> dict:
    await c.weather.delete_rule(request.path_params["rule_id"])
    return {"rules": await c.weather.rules()}
