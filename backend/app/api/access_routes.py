"""Sign-in and the Security & Access Centre API."""
from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request

from ..access.service import describe_ua
from .routes import ApiError, R, client_ip, parse


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(_In):
    password: str = Field(min_length=1, max_length=200)
    ticket: str = Field(default="", max_length=100)


class Factor(_In):
    ticket: str = Field(min_length=1, max_length=100)
    method: Literal["totp", "recovery"]
    code: str = Field(min_length=1, max_length=40)


class PasskeyStart(_In):
    ticket: str = Field(default="", max_length=100)


class PasskeyFinish(_In):
    ticket: str = Field(min_length=1, max_length=100)
    credential: dict[str, Any]
    name: str = Field(default="", max_length=40)


class StepUp(_In):
    method: Literal["password", "totp", "recovery"] = "password"
    code: str = Field(min_length=1, max_length=200)


class ChangePassword(_In):
    current: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=1, max_length=200)


class Code(_In):
    code: str = Field(min_length=1, max_length=20)


class Name(_In):
    name: str = Field(max_length=40)


class Lockdown(_In):
    on: bool


def _ua(request: Request) -> str:
    return request.headers.get("user-agent", "")[:300]


# ---------------------------------------------------------------------------- sign-in (public)
@R.add("/auth/login", ["POST"], public=True)
async def login(request: Request, c: Any) -> dict:
    body = await parse(request, Login)
    ip = client_ip(request)
    try:
        return await c.access.login_password(body.password, ip, _ua(request), body.ticket)
    except Exception:
        await asyncio.sleep(0.3)      # slows guessing a little more; the real limit is the lockout in the throttle
        raise


@R.add("/auth/factor", ["POST"], public=True)
async def login_factor(request: Request, c: Any) -> dict:
    b = await parse(request, Factor)
    return await c.access.login_code(b.ticket, b.method, b.code, client_ip(request), _ua(request))


@R.add("/auth/passkey/options", ["POST"], public=True)
async def login_passkey_options(request: Request, c: Any) -> dict:
    b = await parse(request, PasskeyStart)
    return await c.access.passkey_options(client_ip(request), _ua(request), b.ticket)


@R.add("/auth/passkey/verify", ["POST"], public=True)
async def login_passkey_verify(request: Request, c: Any) -> dict:
    b = await parse(request, PasskeyFinish)
    return await c.access.login_passkey(b.ticket, b.credential, client_ip(request), _ua(request))


@R.add("/auth/logout", ["POST"], limited_ok=True)
async def logout(request: Request, c: Any) -> dict:
    await c.access.logout(request.state.session)
    return {"ok": True}


# ---------------------------------------------------------------------------- the Security page
@R.add("/security/overview", ["GET"], limited_ok=True)
async def overview(request: Request, c: Any) -> dict:
    s = request.state.session
    a = c.access
    e = await a.enrolled()
    return {
        "readiness": await a.readiness(s), "lockdown": a.lockdown, "enforced": await a.enforced(), "methods": await a.methods(),
        "totp": e["totp"], "recovery_left": e["recovery_left"],
        "passkeys": [{"id": p["id"], "name": p["name"], "created": p["created"], "last_used": p["last_used"], "synced": bool(p["backup_state"])} for p in e["passkeys"]],
        "step_up_seconds": max(0, int(s["step_up_until"] - __import__("time").time())),
        "passkey_site": {"rp_id": a.rp_id(), "origins": a.origins()},
        "this_device": describe_ua(s["ua"]),
    }


@R.add("/security/step-up", ["POST"], limited_ok=True)
async def step_up(request: Request, c: Any) -> dict:
    b = await parse(request, StepUp)
    return {"ok": True, "seconds": await c.access.step_up(request.state.session, b.method, b.code, client_ip(request))}


@R.add("/security/password", ["POST"], limited_ok=True)
async def change_password(request: Request, c: Any) -> dict:
    b = await parse(request, ChangePassword)
    return {"ok": True, "signed_out_elsewhere": await c.access.change_password(request.state.session, b.current, b.new, client_ip(request))}


@R.add("/security/totp/begin", ["POST"])
async def totp_begin(request: Request, c: Any) -> dict:
    return await c.access.totp_begin(request.state.session, "owner", c.cfg.get("app_name") or "SavahBot")


@R.add("/security/totp/confirm", ["POST"])
async def totp_confirm(request: Request, c: Any) -> dict:
    b = await parse(request, Code)
    return await c.access.totp_confirm(request.state.session, b.code)


@R.add("/security/totp", ["DELETE"])
async def totp_remove(request: Request, c: Any) -> dict:
    await c.access.totp_remove(request.state.session)
    return {"ok": True}


@R.add("/security/passkeys/options", ["POST"])
async def passkey_options(request: Request, c: Any) -> dict:
    return await c.access.passkey_register_options(request.state.session, c.cfg.get("app_name") or "SavahBot")


@R.add("/security/passkeys/register", ["POST"])
async def passkey_register(request: Request, c: Any) -> dict:
    b = await parse(request, PasskeyFinish)
    return await c.access.passkey_register(request.state.session, b.ticket, b.credential, b.name)


@R.add("/security/passkeys/{pid:int}", ["PATCH"])
async def passkey_rename(request: Request, c: Any) -> dict:
    b = await parse(request, Name)
    if not await c.access.passkey_rename(request.path_params["pid"], b.name):
        raise ApiError("That passkey no longer exists.", 404)
    return {"ok": True}


@R.add("/security/passkeys/{pid:int}", ["DELETE"])
async def passkey_remove(request: Request, c: Any) -> dict:
    if not await c.access.passkey_remove(request.state.session, request.path_params["pid"]):
        raise ApiError("That passkey no longer exists.", 404)
    return {"ok": True}


@R.add("/security/recovery", ["POST"])
async def recovery_new(request: Request, c: Any) -> dict:
    return {"codes": await c.access.regenerate_recovery(request.state.session)}


@R.add("/security/sessions", ["GET"], limited_ok=True)
async def sessions(request: Request, c: Any) -> dict:
    return {"sessions": await c.access.sessions(request.state.session["id"])}


@R.add("/security/sessions/{ref}", ["DELETE"], limited_ok=True)
async def session_revoke(request: Request, c: Any) -> dict:
    if not await c.access.revoke(request.path_params["ref"], request.state.session):
        raise ApiError("That session is already closed.", 404)
    return {"ok": True}


@R.add("/security/sessions/revoke-others", ["POST"], limited_ok=True)
async def session_revoke_others(request: Request, c: Any) -> dict:
    return {"closed": await c.access.revoke_others(request.state.session)}


@R.add("/security/activity", ["GET"], limited_ok=True)
async def activity(request: Request, c: Any) -> dict:
    kind = request.query_params.get("kind", "")
    return {"events": await c.access.events(60, kind if kind in ("login", "login_failed", "logout", "factor") else ""), "audit": await c.access.audit_log(60)}


@R.add("/security/lockdown", ["POST"], limited_ok=True)
async def lockdown(request: Request, c: Any) -> dict:
    b = await parse(request, Lockdown)
    if not b.on:
        c.access.require_fresh(request.state.session)       # turning it on is instant; turning it off needs a fresh confirmation
    await c.access.set_lockdown(b.on, request.state.session)
    return {"ok": True, "lockdown": c.access.lockdown}
