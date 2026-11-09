"""Notification Centre API: config, preferences, inbox, devices, test, stats."""
from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request

from ..notify import NotifyError, categories as cats
from .routes import ApiError, R, need, parse


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatPrefs(_In):
    enabled: bool | None = None
    push: bool | None = None
    inapp: bool | None = None
    telegram: bool | None = None
    priority: str | None = Field(default=None, pattern="^(low|normal|high|critical)$")


class Quiet(_In):
    enabled: bool | None = None
    start: str | None = Field(default=None, max_length=5)
    end: str | None = Field(default=None, max_length=5)
    mode: str | None = Field(default=None, pattern="^(hold|silent)$")
    critical_breaks: bool | None = None


class Prefs(_In):
    enabled: bool | None = None
    push: bool | None = None
    inapp: bool | None = None
    telegram: bool | None = None
    hide_body_locked: bool | None = None
    quiet: Quiet | None = None
    categories: dict[str, CatPrefs] | None = None


class Ids(_In):
    ids: list[int] | None = Field(default=None, max_length=200)      # null means every notification


class Register(_In):
    token: str = Field(min_length=20, max_length=4096)
    installed: bool = False
    label: str = Field(default="", max_length=60)


class Token(_In):
    token: str = Field(min_length=20, max_length=4096)


class DevicePatch(_In):
    label: str | None = Field(default=None, max_length=60)
    enabled: bool | None = None


class Test(_In):
    device_id: int | None = None


class Pause(_In):
    minutes: int | None = Field(default=None, ge=1, le=7 * 1440)     # null resumes


def _f(request: Request, name: str) -> float | None:
    try:
        return float(request.query_params[name]) if request.query_params.get(name) else None
    except ValueError:
        return None


@R.add("/notify/config", ["GET"], limited_ok=True)
async def notify_config(request: Request, c: Any) -> dict:
    n = c.notifier
    return {"push_ready": n.fcm.configured, "web_ready": n.web_ready(), "web": n.web_config(), "vapid_key": c.settings.firebase_vapid_key, "checklist": n.checklist(),
            "problems": n.fcm.problems(), "app_version": __import__("app").__version__}


@R.add("/notify/check", ["POST"])
async def notify_check(request: Request, c: Any) -> dict:
    return await c.notifier.fcm.check()


@R.add("/notify/categories", ["GET"])
async def notify_categories(request: Request, c: Any) -> dict:
    prefs = await c.notifier.prefs()
    items = []
    for row in cats.listing():
        items.append({**row, "effective": c.notifier.effective(prefs, row["id"])})
    return {"groups": cats.GROUPS, "items": items}


@R.add("/notify/prefs", ["GET"])
async def notify_prefs(request: Request, c: Any) -> dict:
    p = await c.notifier.prefs()
    inside, ends = c.notifier.quiet_now(p, time.time())
    return {**p, "quiet_now": inside, "quiet_ends": ends or None, "paused": time.time() < p["pause_until"]}


@R.add("/notify/prefs", ["PUT", "PATCH"])
async def notify_prefs_set(request: Request, c: Any) -> dict:
    b = await parse(request, Prefs)
    try:
        p = await c.notifier.set_prefs(b.model_dump(exclude_none=True))
    except NotifyError as exc:
        raise ApiError(exc.message, exc.status) from None
    return p


@R.add("/notify/pause", ["POST"])
async def notify_pause(request: Request, c: Any) -> dict:
    b = await parse(request, Pause)
    return {"pause_until": await c.notifier.pause(b.minutes, time.time())}


@R.add("/notify/inbox", ["GET"])
async def notify_inbox(request: Request, c: Any) -> dict:
    q = request.query_params
    try:
        limit = int(q.get("limit", 50))
    except ValueError:
        limit = 50
    return await c.notifier.inbox(limit=limit, before=_f(request, "before"), unread=q.get("unread") in ("1", "true"), category=q.get("category", "")[:40],
                                  since=_f(request, "since"), until=_f(request, "until"))


@R.add("/notify/unread", ["GET"], limited_ok=True)
async def notify_unread(request: Request, c: Any) -> dict:
    return {"unread": await c.notifier.unread()}


@R.add("/notify/read", ["POST"])
async def notify_read(request: Request, c: Any) -> dict:
    b = await parse(request, Ids)
    n = await c.notifier.mark_read(b.ids, time.time())
    return {"changed": n, "unread": await c.notifier.unread()}


@R.add("/notify/delete", ["POST"])
async def notify_delete(request: Request, c: Any) -> dict:
    b = await parse(request, Ids)
    return {"deleted": await c.notifier.delete(b.ids), "unread": await c.notifier.unread()}


@R.add("/notify/devices", ["GET"])
async def notify_devices(request: Request, c: Any) -> dict:
    return {"devices": await c.notifier.devices()}


@R.add("/notify/devices", ["POST"])
async def notify_register(request: Request, c: Any) -> dict:
    b = await parse(request, Register)
    try:
        return await c.notifier.register_device(b.token, request.headers.get("user-agent", "")[:300], b.installed, time.time(), b.label)
    except NotifyError as exc:
        raise ApiError(exc.message, exc.status) from None


@R.add("/notify/devices/unregister", ["POST"])
async def notify_unregister(request: Request, c: Any) -> dict:
    b = await parse(request, Token)
    return {"removed": await c.notifier.unregister_token(b.token)}


@R.add("/notify/devices/{device_id:int}", ["PATCH"])
async def notify_device_patch(request: Request, c: Any) -> dict:
    b = await parse(request, DevicePatch)
    i = request.path_params["device_id"]
    if b.label is not None:
        need(await c.notifier.rename_device(i, b.label), "device")
    if b.enabled is not None:
        need(await c.notifier.set_device_enabled(i, b.enabled), "device")
    return {"devices": await c.notifier.devices()}


@R.add("/notify/devices/{device_id:int}", ["DELETE"])
async def notify_device_delete(request: Request, c: Any) -> dict:
    need(await c.notifier.forget_device(request.path_params["device_id"]), "device")
    return {"devices": await c.notifier.devices()}


@R.add("/notify/test", ["POST"])
async def notify_test(request: Request, c: Any) -> dict:
    b = await parse(request, Test)
    return await c.notifier.send_test(time.time(), b.device_id)


@R.add("/notify/stats", ["GET"])
async def notify_stats(request: Request, c: Any) -> dict:
    try:
        days = int(request.query_params.get("days", 7))
    except ValueError:
        days = 7
    return await c.notifier.stats(time.time(), days)


@R.add("/notify/log", ["GET"])
async def notify_log(request: Request, c: Any) -> dict:
    return {"items": await c.notifier.delivery_log(50)}
