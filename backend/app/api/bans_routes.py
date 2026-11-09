"""Dashboard API for ban management: the ledger, lifting, and the softening rules."""
from __future__ import annotations

from typing import Any

from starlette.requests import Request

from .routes import ApiError, R, need


def _int(request: Request, name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(request.query_params.get(name, default))))
    except ValueError:
        return default


@R.add("/bans", ["GET"])
async def bans_list(request: Request, c: Any) -> dict:
    q = request.query_params
    res = await c.hub.bans.search(q.get("status", ""), q.get("q", ""), _int(request, "offset", 0, 0, 1_000_000), _int(request, "limit", 40, 1, 200))
    return {**res, "counts": await c.hub.bans.counts(), "auto_today": await c.hub.bans.auto_count_today(__import__("time").time()),
            "rules": {k: c.cfg.get(k) for k in ("mod_max_punishment", "mod_never_punish", "mod_reason_caps", "mod_auto_punish_daily_cap", "mod_second_chance_hours")}}


@R.add("/bans/{ban_id:int}/lift", ["POST"])
async def bans_lift(request: Request, c: Any) -> dict:
    res = await c.hub.unban(request.path_params["ban_id"], by="dashboard")
    if not res["ok"]:
        raise ApiError(res["error"], res.get("code", 400))
    return {"ok": True, "counts": await c.hub.bans.counts()}


@R.add("/bans/preview", ["POST"])
async def bans_preview(request: Request, c: Any) -> dict:
    """Dry run: what would the softening rules do to this action? Changes nothing."""
    try:
        b = await request.json()
    except ValueError:
        raise ApiError("Send a JSON body.", 400) from None
    action = str(b.get("action", ""))
    need(action in ("timeout", "ban"), "action")
    out, dur, note = await c.hub.bans.limit(action, int(b.get("duration") or 300), [str(x) for x in b.get("signals", [])][:10],
                                            str(b.get("author_id", "")), str(b.get("author_name", "")), bool(b.get("auto", True)))
    return {"action": out, "duration": dur, "changed": out != action, "note": note}
