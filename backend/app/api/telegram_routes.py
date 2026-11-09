"""Telegram control API: switches, pause, read-only, owner unlink, secret rotation, emergency cut-off and the activity trail."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from starlette.requests import Request

from .routes import ApiError, R, parse

NOTIFY_KEYS = {"pending": "telegram_notify_pending", "reminders": "telegram_notify_reminders", "stream_events": "telegram_notify_stream_events"}


class ControlIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    listen: bool | None = None
    send: bool | None = None
    actions: bool | None = None
    claim_open: bool | None = None
    pause_minutes: int | None = None
    notify: dict[str, bool] | None = None


class Confirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = False


async def _state(c: Any) -> dict[str, Any]:
    return {**await c.telegram.control.view(), "status": c.telegram.status()}


@R.add("/telegram/control", ["GET"])
async def telegram_control(request: Request, c: Any) -> dict:
    return await _state(c)


@R.add("/telegram/control", ["POST"])
async def telegram_control_set(request: Request, c: Any) -> dict:
    b = await parse(request, ControlIn)
    patch = {k: v for k, v in b.model_dump().items() if v is not None and k != "notify"}
    if "pause_minutes" in b.model_fields_set and b.pause_minutes is None:
        patch["pause_minutes"] = 0
    for name, on in (b.notify or {}).items():
        if name not in NOTIFY_KEYS:
            raise ApiError(f"Unknown alert type: {name}", 422)
        await c.cfg.set(NOTIFY_KEYS[name], bool(on))
        await c.telegram.control.log("control", f"alerts '{name}' {'on' if on else 'off'}")
    try:
        await c.telegram.control.update(patch)
    except ValueError as exc:
        raise ApiError(str(exc), 422) from None
    return await _state(c)


@R.add("/telegram/unlink", ["POST"])
async def telegram_unlink(request: Request, c: Any) -> dict:
    if not (await parse(request, Confirm)).confirm:
        raise ApiError("Confirm to unlink the owner.", 400)
    out = await c.telegram.control.unlink_owner()
    return {**out, **await _state(c)}


@R.add("/telegram/rotate-secret", ["POST"])
async def telegram_rotate(request: Request, c: Any) -> dict:
    if not (await parse(request, Confirm)).confirm:
        raise ApiError("Confirm to replace the webhook secret.", 400)
    out = await c.telegram.control.rotate_secret()
    if not out["ok"]:
        raise ApiError(out["error"], 409)
    return await _state(c)


@R.add("/telegram/shutdown", ["POST"])
async def telegram_shutdown(request: Request, c: Any) -> dict:
    if not (await parse(request, Confirm)).confirm:
        raise ApiError("Confirm to cut Telegram off.", 400)
    out = await c.telegram.control.shutdown()
    return {**out, **await _state(c)}


@R.add("/telegram/log", ["GET"])
async def telegram_log(request: Request, c: Any) -> dict:
    return {"items": await c.telegram.control.entries()}


@R.add("/telegram/log", ["DELETE"])
async def telegram_log_clear(request: Request, c: Any) -> dict:
    return {"cleared": await c.telegram.control.clear_log()}
