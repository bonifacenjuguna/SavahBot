"""Stream history API: every livestream the bot has been attached to, with its own chat and numbers."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from . import schemas as S
from .routes import ApiError, R, _demo_filter, _epoch, need, parse


def _int(request: Request, name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(request.query_params.get(name, default))))
    except ValueError:
        return default


@R.add("/streams", ["GET"])
async def streams_list(request: Request, c: Any) -> dict:
    """Past and current streams of the mode you are in (Demo and Live never mix), newest first."""
    q = request.query_params
    res = await c.hub.sessions.search(_demo_filter(c), (q.get("q") or "").strip()[:80], _epoch(q.get("since"), "since"), _epoch(q.get("until"), "until"),
                                      _int(request, "limit", 30, 1, 100), _int(request, "offset", 0, 0, 1_000_000))
    res["current"] = c.hub.session_id or None
    res["retention_days"] = c.cfg.get("chat_retention_days")
    return res


@R.add("/streams/last", ["GET"])
async def streams_last(request: Request, c: Any) -> dict:
    return {"item": await c.hub.sessions.last_finished(_demo_filter(c))}


@R.add("/streams/{sid}", ["GET"])
async def streams_one(request: Request, c: Any) -> dict:
    row = await c.hub.sessions.get(request.path_params["sid"])
    need(row is not None, "stream")
    return {"item": row, "retention_days": c.cfg.get("chat_retention_days")}


@R.add("/streams/{sid}/chat", ["GET"])
async def streams_chat(request: Request, c: Any) -> dict:
    sid, q = request.path_params["sid"], request.query_params
    need(await c.hub.sessions.get(sid) is not None, "stream")
    verdict = q.get("verdict") if q.get("verdict") in ("flagged", "blocked") else None
    items = await c.hub.sessions.chat(sid, (q.get("q") or "").strip()[:100], verdict, _int(request, "limit", 1000, 1, 5000))
    return {"items": items}


@R.add("/streams/{sid}", ["PATCH"])
async def streams_rename(request: Request, c: Any) -> dict:
    b = await parse(request, S.StreamPatch)
    need(await c.hub.sessions.rename(request.path_params["sid"], b.label), "stream")
    return {"ok": True, "item": await c.hub.sessions.get(request.path_params["sid"])}


@R.add("/streams/{sid}", ["DELETE"])
async def streams_delete(request: Request, c: Any) -> dict:
    sid = request.path_params["sid"]
    if sid == c.hub.session_id:
        raise ApiError("That stream is running right now. Delete it after it ends.", 409)
    need(await c.hub.sessions.delete(sid), "stream")
    return {"ok": True}


@R.add("/streams/{sid}/export", ["GET"])
async def streams_export(request: Request, c: Any) -> Response:
    """The whole chat of one stream as a plain text file, oldest line first."""
    sid = request.path_params["sid"]
    row = await c.hub.sessions.get(sid)
    need(row is not None, "stream")
    lines = await c.hub.sessions.chat(sid, limit=5000)
    tz = None
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(c.cfg.get("owner_timezone") or "UTC")
    except Exception:
        tz = timezone.utc

    def stamp(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M:%S")

    head = [f"{row.get('label') or row.get('title') or 'Stream'}", f"Started {stamp(row['started'])}",
            f"Ended {stamp(row['ended'])}" if row.get("ended") else "Still running", f"{row['messages']} lines, {row['chatters']} chatters", ""]
    body = [f"[{stamp(m['ts'])}] {m['author_name']}: {m['text']}" + (f"   <{m['verdict']}>" if m.get("verdict") not in (None, "allow") else "") for m in lines]
    name = "savahbot-stream-" + datetime.fromtimestamp(row["started"], tz).strftime("%Y%m%d-%H%M") + ".txt"
    return Response("\n".join(head + body) + "\n", media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})
