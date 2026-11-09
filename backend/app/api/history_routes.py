"""History API: long-range series for the chart detail view, and what is stored."""
from __future__ import annotations

import time
from typing import Any

from starlette.requests import Request

from .routes import ApiError, R


def _float(request: Request, name: str, default: float) -> float:
    try:
        return float(request.query_params.get(name, default))
    except ValueError:
        raise ApiError(f"{name} must be a number.", 400) from None


@R.add("/history", ["GET"])
async def history(request: Request, c: Any) -> dict:
    now = time.time()
    until = min(_float(request, "until", now), now + 3600)
    since = _float(request, "since", until - 7 * 86400)
    if since >= until:
        raise ApiError("since must be before until.", 400)
    if until - since > 5 * 366 * 86400:
        raise ApiError("Ask for at most five years at a time.", 400)
    res = request.query_params.get("res", "auto")
    demo = request.query_params.get("demo", "0") == "1"
    return await c.rollups.series(since, until, res, demo, now)


@R.add("/history/storage", ["GET"])
async def history_storage(request: Request, c: Any) -> dict:
    out = await c.rollups.storage()
    out["retention"] = {"chat_days": c.cfg.get("chat_retention_days"), "action_days": c.cfg.get("action_retention_days")}
    out["database"] = c.db.backend
    return out
