"""SavahLive API (1.5.0): pairing, the phone's feed, and the Manage > SavahLive page.

Phone side (no dashboard sign-in; the phone proves itself with its own device key):
  GET  /api/live/pair/open   the page a QR code opens: one button that hands the code to the SavahLive app
  POST /api/live/pair        swap a one-time code for a device key
  GET  /api/live/feed        the overlay's Server-Sent Events stream
  POST /api/live/rotate      swap the device key for a fresh one
  POST /api/live/send        post one chat message (only for a phone you allowed to send)
  POST /api/live/mod         hide a message or time its author out (only for a phone you allowed to moderate)

Dashboard side (the usual owner sign-in):
  GET  /api/savahlive, POST /api/savahlive/pair-code, PATCH|DELETE /api/savahlive/devices/{id},
  POST /api/savahlive/devices/revoke-all, POST /api/savahlive/settings
"""
from __future__ import annotations

import html
import time
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, StreamingResponse

from ..access import qr
from ..savahlive import CODE_RE, EXPIRY_CHOICES, PROTOCOL, LiveError, _h, clean_code, show_code
from .routes import ApiError, R, client_ip, parse


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PairIn(_In):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(default="", max_length=80)
    app_version: str = Field(default="", max_length=20)


class NewCode(_In):
    expiry_days: int = 0


class DeviceEdit(_In):
    name: str | None = Field(default=None, max_length=40)
    expiry_days: int | None = None
    can_send: bool | None = None
    can_mod: bool | None = None


class ModIn(_In):
    id: int = Field(ge=1)
    action: str = Field(max_length=10)


class SendIn(_In):
    text: str = Field(min_length=1, max_length=400)


class SettingsIn(_In):
    enabled: bool | None = None
    max_devices: int | None = Field(default=None, ge=1, le=20)
    max_feeds: int | None = Field(default=None, ge=1, le=20)
    chat_lines: int | None = Field(default=None, ge=10, le=100)
    peek_seconds: int | None = Field(default=None, ge=2, le=15)
    font_size: int | None = Field(default=None, ge=11, le=22)
    hide_seconds: int | None = Field(default=None, ge=0, le=30)
    download_url: str | None = Field(default=None, max_length=300)
    hide_bots: bool | None = None
    hide_flagged: bool | None = None
    only_special: bool | None = None
    send_enabled: bool | None = None
    mod_enabled: bool | None = None
    rotate_days: int | None = Field(default=None, ge=0, le=365)
    idle_unpair_days: int | None = Field(default=None, ge=0, le=365)
    track_stats: bool | None = None


# setting field (above) -> config name
SETTING_KEYS = {"enabled": "savahlive_enabled", "max_devices": "savahlive_max_devices", "max_feeds": "savahlive_max_feeds", "chat_lines": "savahlive_chat_lines",
                "peek_seconds": "savahlive_peek_seconds", "font_size": "savahlive_font_size", "hide_seconds": "savahlive_hide_seconds", "download_url": "savahlive_download_url", "hide_bots": "savahlive_hide_bots", "hide_flagged": "savahlive_hide_flagged",
                "only_special": "savahlive_only_special", "send_enabled": "savahlive_send_enabled", "mod_enabled": "savahlive_mod_enabled", "rotate_days": "savahlive_rotate_days", "idle_unpair_days": "savahlive_idle_unpair_days", "track_stats": "yt_live_enabled"}


def _fail(err: LiveError) -> ApiError:
    return ApiError(err.message, err.status, err.code)


def server_url(request: Request, c: Any) -> str:
    return c.cfg.public_url or str(request.base_url).rstrip("/")


def _links(server: str, code: str) -> dict[str, str]:
    return {"link": f"{server}/api/live/pair/open?c={code}", "app_link": f"savahlive://pair?s={quote(server, safe='')}&c={code}"}


# ================================================================================= phone side
_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>SavahLive</title><style>
:root{color-scheme:light dark;--bg:#fff;--fg:#14161c;--mut:#5b6170;--red:#e5242b}@media(prefers-color-scheme:dark){:root{--bg:#0f1116;--fg:#f1f2f5;--mut:#9aa0b0}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;display:grid;min-height:100vh;place-items:center;padding:24px;box-sizing:border-box}
main{max-width:420px;width:100%;text-align:center}h1{margin:0 0 4px;font-size:28px}h1 b{color:var(--red)}p{color:var(--mut);margin:8px 0}
.btn{display:block;background:var(--red);color:#fff;text-decoration:none;font-weight:700;padding:16px;border-radius:14px;margin:22px 0 14px}
.code{font:700 30px/1.2 ui-monospace,monospace;letter-spacing:.12em;margin:6px 0}small{color:var(--mut);display:block;word-break:break-all}</style></head><body><main>
<h1>Savah<b>Live</b></h1>__BODY__</main></body></html>"""


@R.add("/live/pair/open", ["GET"], public=True)
async def pair_open(request: Request, c: Any) -> HTMLResponse:
    code = clean_code(request.query_params.get("c", ""))
    headers = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'",
               "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    if not CODE_RE.match(code):
        body = "<p>This pairing link is not complete. Make a new one in SavahBot (Manage &gt; SavahLive).</p>"
    else:
        server = server_url(request, c)
        body = (f'<p>Pair this phone with SavahBot</p><a class="btn" href="{html.escape(_links(server, code)["app_link"], quote=True)}">Open SavahLive</a>'
                f'<p>If the button does nothing, open SavahLive and type</p><div class="code">{html.escape(show_code(code))}</div>'
                f'<p>Server</p><small>{html.escape(server)}</small><p><small>The code works once and runs out in 5 minutes.</small></p>')
    return HTMLResponse(_PAGE.replace("__BODY__", body), headers=headers)


@R.add("/live/pair", ["POST"], public=True)
async def pair(request: Request, c: Any) -> dict:
    b = await parse(request, PairIn)
    try:
        return await c.savahlive.redeem(b.code, b.name, b.app_version, client_ip(request))
    except LiveError as err:
        raise _fail(err) from None


@R.add("/live/feed", ["GET"], public=True)
async def feed(request: Request, c: Any) -> Any:
    sl = c.savahlive
    try:
        dev = await sl.device(request.headers.get("authorization", ""))
        if not sl.can_open(dev["id"]):
            raise LiveError("Too many phones are connected right now. Close the overlay on another phone, or raise the limit in Manage > SavahLive.", 429, "busy")
    except LiveError as err:
        raise _fail(err) from None
    try:
        since = max(0, int(request.query_params.get("since", "0")))
    except ValueError:
        since = 0
    await sl.touch(dev["id"], request.query_params.get("app", ""))
    return StreamingResponse(sl.stream(dev, since, request.is_disconnected), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@R.add("/live/rotate", ["POST"], public=True)
async def rotate(request: Request, c: Any) -> dict:
    sl = c.savahlive
    header = request.headers.get("authorization", "")
    try:
        row, via_prev = await sl._row(header)
        await sl.check(row)
        row["via_prev"] = via_prev
        return {"key": await sl.rotate(row, _h(header[7:].strip()))}
    except LiveError as err:
        raise _fail(err) from None


@R.add("/live/send", ["POST"], public=True)
async def send(request: Request, c: Any) -> dict:
    b = await parse(request, SendIn)
    sl = c.savahlive
    try:
        dev = await sl.device(request.headers.get("authorization", ""))
        await sl.send(dev, b.text, client_ip(request))
    except LiveError as err:
        raise _fail(err) from None
    return {"ok": True}


@R.add("/live/mod", ["POST"], public=True)
async def moderate(request: Request, c: Any) -> dict:
    b = await parse(request, ModIn)
    sl = c.savahlive
    try:
        dev = await sl.device(request.headers.get("authorization", ""))
        await sl.moderate(dev, b.id, b.action, client_ip(request))
    except LiveError as err:
        raise _fail(err) from None
    return {"ok": True}


# ================================================================================= dashboard side
async def _overview(request: Request, c: Any) -> dict:
    sl = c.savahlive
    cfg = c.cfg
    state = sl.state()
    return {
        "enabled": sl.enabled, "protocol": PROTOCOL, "server": server_url(request, c), "server_is_public": bool(cfg.public_url),
        "devices": await sl.devices(), "connected": len(sl.feeds), "state": state,
        "settings": {**sl.overlay_settings(), "enabled": sl.enabled, "max_devices": sl.limit("savahlive_max_devices", 1, 20), "max_feeds": sl.limit("savahlive_max_feeds", 1, 20),
                     "rotate_days": sl.limit("savahlive_rotate_days", 0, 365), "idle_unpair_days": sl.limit("savahlive_idle_unpair_days", 0, 365),
                     "track_stats": bool(cfg.get("yt_live_enabled")), "send_enabled": bool(cfg.get("savahlive_send_enabled")), "mod_enabled": bool(cfg.get("savahlive_mod_enabled")), "download_url": str(cfg.get("savahlive_download_url") or "")},
        "stats_seconds": int(cfg.get("yt_live_seconds")), "dashboard_clients": c.bus.subscriber_count, "dashboard_limit": int(cfg.get("sse_max_clients")),
        "expiry_choices": list(EXPIRY_CHOICES), "now": time.time(),
    }


@R.add("/savahlive", ["GET"])
async def overview(request: Request, c: Any) -> dict:
    return await _overview(request, c)


@R.add("/savahlive/pair-code", ["POST"])
async def pair_code(request: Request, c: Any) -> dict:
    b = await parse(request, NewCode)
    server = server_url(request, c)
    if server.startswith("http://") and "localhost" not in server and "127.0.0.1" not in server:
        raise ApiError("Phones can only pair over HTTPS. Set PUBLIC_BASE_URL to your https:// backend address first.", 409, "no_https")
    if not c.savahlive.enabled:
        raise ApiError("SavahLive is switched off. Turn it on first.", 409, "disabled")
    try:
        made = await c.savahlive.new_code(b.expiry_days)
    except LiveError as err:
        raise _fail(err) from None
    links = _links(server, made["code"])
    return {**made, **links, "server": server, "qr": qr.svg(links["link"])}


@R.add("/savahlive/devices/{did}", ["PATCH"])
async def device_edit(request: Request, c: Any) -> dict:
    b = await parse(request, DeviceEdit)
    try:
        ok = await c.savahlive.edit(request.path_params["did"], b.name, b.expiry_days, b.can_send, b.can_mod)
    except LiveError as err:
        raise _fail(err) from None
    if not ok:
        raise ApiError("That phone is no longer paired.", 404)
    return {"ok": True}


@R.add("/savahlive/devices/{did}", ["DELETE"])
async def device_remove(request: Request, c: Any) -> dict:
    did = request.path_params["did"]
    if not await c.savahlive.revoke(did):
        raise ApiError("That phone is no longer paired.", 404)
    await c.access.audit("savahlive_removed", request.state.session, client_ip(request), did)
    return {"ok": True}


@R.add("/savahlive/devices/revoke-all", ["POST"])
async def device_remove_all(request: Request, c: Any) -> dict:
    n = await c.savahlive.revoke_all()
    await c.access.audit("savahlive_removed_all", request.state.session, client_ip(request), f"{n} phones")
    return {"removed": n}


@R.add("/savahlive/settings", ["POST"])
async def settings_save(request: Request, c: Any) -> dict:
    b = await parse(request, SettingsIn)
    data = b.model_dump(exclude_none=True)
    url = data.get("download_url")
    if url and not url.startswith("https://"):
        raise ApiError("The download link must start with https://", 422)
    for field, value in data.items():
        await c.cfg.set(SETTING_KEYS[field], value)
    return await _overview(request, c)
