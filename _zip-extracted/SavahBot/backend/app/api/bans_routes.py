"""Dashboard API for ban management: the ledger, lifting, and the softening rules."""
from __future__ import annotations

import json
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


def _loads(text: Any, default: Any) -> Any:
    try:
        return json.loads(text) if isinstance(text, str) else default
    except ValueError:
        return default


async def _build_profile(c: Any, platform: str, aid: str, name: str, ban: dict[str, Any] | None, action: dict[str, Any] | None) -> dict[str, Any]:
    """The profile of one person. `ban` and `action` say which moment to explain; with neither the person simply has no sanction to explain
    (a viewer opened from the chat or Insights) and the sheet shows who they are, their messages and anything that happened to them."""
    db = c.store.db
    cols = "id, ts, body, verdict, score, level, msg_id, demo"
    at = (ban["ts"] if ban else action["ts"] if action else None)
    signals = _loads(action["reasons"], []) if action else []
    evidence: list[dict[str, Any]] = []
    how = "none"
    if action:
        ids = [str(i) for i in _loads(action["message_ids"], []) if i][:40]
        if ids:
            evidence = await db.fetchall(f"SELECT {cols} FROM chat_messages WHERE platform = ? AND author_id = ? AND msg_id IN ({', '.join('?' for _ in ids)}) ORDER BY ts, id",
                                         [platform, aid, *ids])
        how = "recorded"
        if not evidence and action["body"]:     # the lines were pruned from the chat store, but the action kept a copy of the text
            evidence = [{"id": 0, "ts": action["ts"], "body": action["body"], "verdict": "flag", "score": action["score"], "level": "everyone", "msg_id": "", "demo": action["demo"]}]
            how = "kept"
    if not evidence and at is not None:     # a ban chosen by hand records no single message: show what they said just before it, flagged lines first
        before = await db.fetchall(f"SELECT {cols} FROM chat_messages WHERE platform = ? AND author_id = ? AND ts <= ? AND level != 'bot' ORDER BY ts DESC, id DESC LIMIT 25",
                                   (platform, aid, at + 5))
        flagged = [m for m in before if m["verdict"] != "allow" and m["ts"] >= at - 900]
        evidence = sorted((flagged or before)[:5], key=lambda m: (m["ts"], m["id"]))
        how = "guess" if evidence else "none"

    context: list[dict[str, Any]] = []
    if at is not None:     # the chat around it (everyone's lines, so you can see what led up to it)
        start = (min(m["ts"] for m in evidence) if evidence else at) - 120
        around = await db.fetchall(f"SELECT {cols}, author_id, author_name FROM chat_messages WHERE platform = ? AND ts >= ? AND ts <= ? ORDER BY ts, id LIMIT 60", (platform, start, at + 15))
        ev_ids = {m["id"] for m in evidence}
        context = [{"id": m["id"], "ts": m["ts"], "name": m["author_name"], "body": m["body"], "verdict": m["verdict"], "mine": m["author_id"] == aid,
                    "evidence": m["id"] in ev_ids, "bot": m["level"] == "bot"} for m in around]

    stats = await db.fetchone("SELECT COUNT(*) AS n, MIN(ts) AS first, MAX(ts) AS last, MAX(author_name) AS name, SUM(CASE WHEN verdict != 'allow' THEN 1 ELSE 0 END) AS flagged "
                              "FROM chat_messages WHERE platform = ? AND author_id = ? AND level != 'bot'", (platform, aid))
    name = (ban or {}).get("author_name") or (action or {}).get("author_name") or stats["name"] or name or aid     # a name on record beats one a page guessed
    history = await db.fetchall("SELECT id, ts, kind, duration, source, reason, status, lifted_ts, lifted_by, action_id, demo FROM bans WHERE platform = ? AND author_id = ? ORDER BY ts DESC, id DESC LIMIT 50",
                                (platform, aid))
    actions = await db.fetchall("SELECT id, ts, action, duration, score, reasons, status, mode, body, demo FROM mod_actions WHERE platform = ? AND author_id = ? ORDER BY ts DESC, id DESC LIMIT 30",
                                (platform, aid))
    for a in actions:
        a["reasons"] = _loads(a["reasons"], [])
    recent = await db.fetchall(f"SELECT {cols} FROM chat_messages WHERE platform = ? AND author_id = ? AND level != 'bot' ORDER BY ts DESC, id DESC LIMIT 25", (platform, aid))
    low = (name or "").lower()
    notes = [n for n in await c.store.list_notes() if low and f"@{low}" in (n.get("body") or "").lower()][:5]
    active = next((b for b in history if b["status"] == "active"), None)
    return {"ban": {**ban, "can_lift": bool(ban["status"] == "active" and (ban["ban_ref"] or ban["demo"]))} if ban else None,
            "active_ban_id": active["id"] if active else None,
            "person": {"id": aid, "name": name, "platform": platform, "messages": stats["n"] or 0, "flagged": stats["flagged"] or 0, "first_seen": stats["first"], "last_seen": stats["last"],
                       "regular": bool(c.store.is_regular(aid, name or "")), "notes": [{"id": n.get("id"), "body": n.get("body")} for n in notes]},
            "why": {"how": how, "at": at, "kind": ban["kind"] if ban else action["action"] if action else "", "duration": (ban or action or {}).get("duration"),
                    "status": ban["status"] if ban else action["status"] if action else "", "reason": (ban["reason"] if ban else "") or ", ".join(signals),
                    "source": ban["source"] if ban else (action["mode"] if action else ""), "score": action["score"] if action else None, "signals": signals, "evidence": evidence},
            "context": context, "history": history, "actions": actions, "recent": recent}


@R.add("/bans/{ban_id:int}/profile", ["GET"])
async def bans_profile(request: Request, c: Any) -> dict:
    """1.4.3: the profile of one banned or timed-out person, opened from the ledger. Who they are, WHY it happened (the message or messages that caused it,
    what flagged them, the chat around that moment), and everything that has happened to them before and since."""
    ban = await c.hub.bans.get(request.path_params["ban_id"])
    if not ban:
        raise ApiError("That entry is no longer in the ledger.", 404)
    action = await c.store.db.fetchone("SELECT * FROM mod_actions WHERE id = ?", (ban["action_id"],)) if ban["action_id"] else None
    return await _build_profile(c, ban["platform"], ban["author_id"], ban["author_name"], ban, action)


@R.add("/people/profile", ["GET"])
async def people_profile(request: Request, c: Any) -> dict:
    """1.4.3: the same profile for anyone, opened from the chat, Insights, Moderation or the Activity log. `ban_id` or `action_id` pick the moment to explain;
    without them the latest ban of that person is explained (if there is one), then their latest moderation action."""
    q = request.query_params
    aid, platform = q.get("author_id", ""), q.get("platform", "") or "youtube"
    if not aid:
        raise ApiError("author_id is required.", 422)
    db = c.store.db
    ban = action = None
    try:
        ban_id, action_id = int(q.get("ban_id", 0) or 0), int(q.get("action_id", 0) or 0)
    except ValueError:
        raise ApiError("ban_id and action_id must be numbers.", 422)
    if ban_id:
        ban = await c.hub.bans.get(ban_id)
    if not ban and action_id:
        action = await db.fetchone("SELECT * FROM mod_actions WHERE id = ?", (action_id,))
        ban = await db.fetchone("SELECT * FROM bans WHERE action_id = ? ORDER BY id DESC LIMIT 1", (action_id,)) if action else None
    if ban and not action and ban["action_id"]:
        action = await db.fetchone("SELECT * FROM mod_actions WHERE id = ?", (ban["action_id"],))
    if not ban and not action_id:
        ban = await db.fetchone("SELECT * FROM bans WHERE platform = ? AND author_id = ? ORDER BY ts DESC, id DESC LIMIT 1", (platform, aid))
        if ban and ban["action_id"]:
            action = await db.fetchone("SELECT * FROM mod_actions WHERE id = ?", (ban["action_id"],))
        elif not ban:
            action = await db.fetchone("SELECT * FROM mod_actions WHERE platform = ? AND author_id = ? ORDER BY ts DESC, id DESC LIMIT 1", (platform, aid))
    if ban and (ban["author_id"] != aid or ban["platform"] != platform):
        ban = None      # an id for somebody else is never explained under this person
    if action and (action["author_id"] != aid or action["platform"] != platform):
        action = None
    return await _build_profile(c, platform, aid, q.get("name", ""), ban, action)
