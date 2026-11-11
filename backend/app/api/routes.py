"""REST API. Everything except /health, /auth/login, the Telegram webhook and the Google OAuth callback
requires the owner's bearer token."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

from ..access.service import AccessError
from .. import __version__
from ..analytics import summary
from ..commands import BUILTIN_NAMES, Ctx
from ..config import BY_NAME
from ..models import ChatMessage
from ..moderation import ModInput
from ..store import LEVELS, ValidationFailed
from ..timeparse import ReminderParseError, parse_reminder
from ..utils import to_epoch
from . import schemas as S

logger = logging.getLogger("savahbot.api")


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, code: str | None = None) -> None:
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


class Registry:
    def __init__(self) -> None:
        self.routes: list[Route] = []
        self.meta: list[tuple[str, list[str], bool, bool]] = []     # (path, methods, public, limited_ok): read by scripts/gen_api_doc.py

    def add(self, path: str, methods: list[str], public: bool = False, limited_ok: bool = False) -> Callable:
        def deco(fn: Callable[[Request, Any], Awaitable[Any]]) -> Callable:
            async def endpoint(request: Request) -> Response:
                c = request.app.state.c
                try:
                    if not public:
                        session = await c.access.authenticate(request.headers.get("authorization", ""), allow_limited=limited_ok)
                        if session is None:
                            raise ApiError("Sign in to continue.", 401)
                        request.state.session = session
                    result = await fn(request, c)
                    return result if isinstance(result, Response) else JSONResponse(result)
                except AccessError as exc:
                    return JSONResponse({"error": exc.message, **({"code": exc.code} if exc.code else {})}, status_code=exc.status)
                except ApiError as exc:
                    return JSONResponse({"error": exc.message, **({"code": exc.code} if exc.code else {})}, status_code=exc.status)
                except ValidationError as exc:
                    first = exc.errors()[0]
                    where = ".".join(str(p) for p in first["loc"])
                    return JSONResponse({"error": f"{where}: {first['msg']}" if where else first["msg"]}, status_code=422)
                except (ValidationFailed, ReminderParseError, ValueError) as exc:
                    return JSONResponse({"error": str(exc)}, status_code=400)
                except PermissionError as exc:
                    return JSONResponse({"error": str(exc)}, status_code=403)
                except KeyError as exc:
                    return JSONResponse({"error": f"Unknown item: {exc.args[0] if exc.args else ''}"}, status_code=404)
                except Exception:
                    logger.exception("Unhandled error in %s %s", request.method, request.url.path)
                    return JSONResponse({"error": "Something went wrong on the server. Check the logs."}, status_code=500)

            self.routes.append(Route("/api" + path, endpoint, methods=methods))
            self.meta.append(("/api" + path, list(methods), public, limited_ok))
            return fn

        return deco


R = Registry()


async def parse(request: Request, model: type[BaseModel]) -> Any:
    try:
        raw = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise ApiError("Send a JSON body.", 400) from None
    return model.model_validate(raw)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def need(found: bool, what: str = "item") -> None:
    if not found:
        raise ApiError(f"That {what} no longer exists.", 404)


def _is_builtin(name: str, prefix: str) -> bool:
    n = (name or "").strip().lower()
    return (n[len(prefix):] if prefix and n.startswith(prefix) else n) in BUILTIN_NAMES


def _demo_filter(c: Any) -> bool:
    return c.cfg.get("bot_mode") == "demo"


# ================================================================================= public
@R.add("/health", ["GET"], public=True)
async def health(request: Request, c: Any) -> dict:
    return {"ok": True, "app": c.cfg.get("app_name"), "version": __version__, "mode": c.cfg.get("bot_mode"),
            "database": c.db.backend, "uptime": round(time.time() - c.started_at), "redis": c.shared.mode}


@R.add("/telegram/webhook", ["POST"], public=True)
async def telegram_webhook(request: Request, c: Any) -> Any:
    try:
        update = await request.json()
    except ValueError:
        return JSONResponse({"ok": False}, status_code=400)
    ok = await c.telegram.handle_webhook(request.headers.get("x-telegram-bot-api-secret-token"), update)
    return JSONResponse({"ok": True}) if ok else JSONResponse({"error": "forbidden"}, status_code=403)


@R.add("/youtube/oauth/callback", ["GET"], public=True)
async def youtube_callback(request: Request, c: Any) -> Any:
    q = request.query_params
    front = c.settings.frontend_url.rstrip("/")

    def done(ok: bool, message: str) -> Response:
        if front:
            from urllib.parse import quote
            return RedirectResponse(f"{front}/setup?youtube={'connected' if ok else 'error'}&message={quote(message)}", status_code=303)
        return HTMLResponse(f"<h3>{'Connected' if ok else 'Could not connect'}</h3><p>{message}</p><p>You can close this tab.</p>")

    if q.get("error"):
        return done(False, f"Google said: {q.get('error')}")
    if not c.google.check_state(q.get("state", "")):
        return done(False, "This sign-in link expired or is not valid. Start again from the dashboard.")
    try:
        pending = await c.google.begin_login(q.get("code", ""))   # nothing is saved yet
        kept, message = await c.youtube.accept_login(pending)     # ask Google WHO signed in; only a checked login is kept
    except RuntimeError as exc:
        return done(False, str(exc))
    return done(kept, message)


# ================================================================================= session + status
@R.add("/auth/me", ["GET"])
async def me(request: Request, c: Any) -> dict:
    return {"ok": True, "app": c.cfg.get("app_name")}


@R.add("/status", ["GET"])
async def status(request: Request, c: Any) -> dict:
    return {
        "app": c.cfg.get("app_name"), "version": __version__, "timezone": c.cfg.get("owner_timezone"),
        "hub": c.hub.status(), "telegram": c.telegram.status(), "youtube": c.youtube.status(), "demo": c.demo.status(),
        "pending": len(await c.store.pending_actions(_demo_filter(c))), "database": c.db.backend, "uptime": round(time.time() - c.started_at),
        "sse_clients": c.bus.subscriber_count,
        "redis": c.shared.status() | {"leader": c.leader.is_leader, "snapshot": c.keeper.status()},
    }


@R.add("/setup", ["GET"])
async def setup(request: Request, c: Any) -> dict:
    return {
        "requirements": c.cfg.requirements_status(), "public_url": c.settings.public_url,
        "telegram_webhook_url": (c.settings.public_url + "/api/telegram/webhook") if c.settings.public_url else "",
        "google_redirect_uri": c.google.redirect_uri(), "youtube_connected": await c.google.connected(),
        "telegram_owner_bound": c.telegram.status()["owner_bound"], "telegram_bot": c.telegram.status()["bot_username"],
    }


# ================================================================================= settings
@R.add("/settings", ["GET"])
async def settings_get(request: Request, c: Any) -> dict:
    return {"items": c.cfg.snapshot()}


@R.add("/settings", ["PATCH"])
async def settings_patch(request: Request, c: Any) -> dict:
    body = await parse(request, S.SettingsPatch)
    for name in body.values:
        if name not in BY_NAME:
            raise ApiError(f"Unknown setting: {name}", 404)
    for name, value in body.values.items():
        await c.cfg.set(name, value)
    return {"items": [s for s in c.cfg.snapshot() if s["name"] in body.values]}


@R.add("/settings/{name}", ["DELETE"])
async def settings_reset(request: Request, c: Any) -> dict:
    await c.cfg.reset(request.path_params["name"])
    return {"ok": True}


# ================================================================================= commands
@R.add("/commands", ["GET"])
async def commands_list(request: Request, c: Any) -> dict:
    return {"items": await c.store.list_commands(), "builtin": sorted(BUILTIN_NAMES), "levels": list(LEVELS)}


@R.add("/commands", ["POST"])
async def commands_create(request: Request, c: Any) -> dict:
    b = await parse(request, S.CommandIn)
    if _is_builtin(b.name, c.cfg.get("command_prefix")):
        raise ApiError("That name is built in and cannot be used.", 400)
    id_ = await c.store.create_command(
        b.name, b.response, b.userlevel, b.cooldown if b.cooldown is not None else c.cfg.get("command_default_cooldown"),
        b.user_cooldown if b.user_cooldown is not None else c.cfg.get("command_user_cooldown"), b.enabled, b.aliases)
    return {"item": await c.store.get_command(id_)}


@R.add("/commands/preview", ["POST"])
async def commands_preview(request: Request, c: Any) -> dict:
    b = await parse(request, S.Preview)
    msg = ChatMessage("preview", "preview-user", b.user or "Viewer", "", b.level if b.level in LEVELS else "everyone")
    return {"output": await c.commands.preview(b.template, msg, b.args)}


@R.add("/commands/{id:int}", ["PATCH"])
async def commands_update(request: Request, c: Any) -> dict:
    id_ = request.path_params["id"]
    b = await parse(request, S.CommandPatch)
    fields = b.model_dump(exclude_unset=True)
    if _is_builtin(fields.get("name", ""), c.cfg.get("command_prefix")):
        raise ApiError("That name is built in and cannot be used.", 400)
    need(await c.store.get_command(id_), "command")
    await c.store.update_command(id_, **fields)
    return {"item": await c.store.get_command(id_)}


@R.add("/commands/{id:int}", ["DELETE"])
async def commands_delete(request: Request, c: Any) -> dict:
    need(await c.store.delete_command(request.path_params["id"]), "command")
    return {"ok": True}


# ================================================================================= timers
@R.add("/timers", ["GET"])
async def timers_list(request: Request, c: Any) -> dict:
    return {"items": await c.store.list_timers()}


@R.add("/timers", ["POST"])
async def timers_create(request: Request, c: Any) -> dict:
    b = await parse(request, S.TimerIn)
    lines = b.min_lines if b.min_lines is not None else (5 if b.interval_seconds else 0)
    await c.store.create_timer(b.name, b.message, b.interval_seconds, lines, b.enabled, b.match_mode, b.max_runs)
    return {"items": await c.store.list_timers()}


@R.add("/timers/{id:int}", ["PATCH"])
async def timers_update(request: Request, c: Any) -> dict:
    b = await parse(request, S.TimerPatch)
    need(await c.store.update_timer(request.path_params["id"], **b.model_dump(exclude_unset=True)), "timer")
    return {"items": await c.store.list_timers()}


@R.add("/timers/{id:int}", ["DELETE"])
async def timers_delete(request: Request, c: Any) -> dict:
    need(await c.store.delete_timer(request.path_params["id"]), "timer")
    return {"ok": True}


@R.add("/timers/{id:int}/send", ["POST"])
async def timers_send(request: Request, c: Any) -> dict:
    """Post a timer's message to chat right now, without touching its schedule."""
    t = await c.store.get_timer(request.path_params["id"])
    need(t, "timer")
    text = await c.hub.commands.renderer.render(t["message"], Ctx(channel=c.hub.commands.channel_fn(), now=time.time()))
    if not text or not await c.hub.send_chat(text):
        raise ApiError("Could not send. The stream has ended or the bot is not attached to a live chat. Standby will return once your next stream starts.", 409)
    return {"ok": True, "text": text}


# ================================================================================= auto-replies (triggers)
@R.add("/triggers", ["GET"])
async def triggers_list(request: Request, c: Any) -> dict:
    return {"items": await c.store.list_triggers(), "levels": list(LEVELS), "enabled": c.cfg.get("triggers_enabled")}


@R.add("/triggers", ["POST"])
async def triggers_create(request: Request, c: Any) -> dict:
    b = await parse(request, S.TriggerIn)
    id_ = await c.store.create_trigger(
        b.phrase, b.response, b.match_type, b.mention, b.userlevel,
        b.cooldown if b.cooldown is not None else c.cfg.get("trigger_default_cooldown"),
        b.user_cooldown if b.user_cooldown is not None else c.cfg.get("trigger_user_cooldown"), b.enabled)
    return {"item": await c.store.get_trigger(id_)}


@R.add("/triggers/{id:int}", ["PATCH"])
async def triggers_update(request: Request, c: Any) -> dict:
    id_ = request.path_params["id"]
    b = await parse(request, S.TriggerPatch)
    need(await c.store.get_trigger(id_), "auto-reply")
    await c.store.update_trigger(id_, **b.model_dump(exclude_unset=True))
    return {"item": await c.store.get_trigger(id_)}


@R.add("/triggers/{id:int}", ["DELETE"])
async def triggers_delete(request: Request, c: Any) -> dict:
    need(await c.store.delete_trigger(request.path_params["id"]), "auto-reply")
    return {"ok": True}


# ================================================================================= quotes + regulars
@R.add("/quotes", ["GET"])
async def quotes_list(request: Request, c: Any) -> dict:
    return {"items": await c.store.list_quotes()}


@R.add("/quotes", ["POST"])
async def quotes_create(request: Request, c: Any) -> dict:
    b = await parse(request, S.QuoteIn)
    await c.store.add_quote(b.body, b.author)
    return {"items": await c.store.list_quotes()}


@R.add("/quotes/{id:int}", ["DELETE"])
async def quotes_delete(request: Request, c: Any) -> dict:
    need(await c.store.delete_quote(request.path_params["id"]), "quote")
    return {"ok": True}


@R.add("/regulars", ["GET"])
async def regulars_list(request: Request, c: Any) -> dict:
    return {"items": await c.store.list_regulars()}


@R.add("/regulars", ["POST"])
async def regulars_create(request: Request, c: Any) -> dict:
    b = await parse(request, S.RegularIn)
    await c.store.add_regular(b.ident, b.label)
    return {"items": await c.store.list_regulars()}


@R.add("/regulars/{id:int}", ["DELETE"])
async def regulars_delete(request: Request, c: Any) -> dict:
    need(await c.store.delete_regular(request.path_params["id"]), "regular")
    return {"ok": True}


# ================================================================================= blacklist + moderation

def _thresholds(c: Any) -> dict:
    """The score ladder, so the dashboard can show where a phrase or a message lands (flag, delete, timeout, ban)."""
    return {"flag": c.cfg.get("mod_score_flag"), "delete": c.cfg.get("mod_score_delete"), "timeout": c.cfg.get("mod_score_timeout"),
            "ban": c.cfg.get("mod_score_ban"), "default_weight": c.cfg.get("mod_blacklist_weight")}

@R.add("/blacklist", ["GET"])
async def blacklist_list(request: Request, c: Any) -> dict:
    return {"items": await c.store.list_blacklist(), "thresholds": _thresholds(c)}


@R.add("/blacklist", ["POST"])
async def blacklist_create(request: Request, c: Any) -> dict:
    b = await parse(request, S.BlacklistIn)
    await c.store.add_blacklist(b.phrase, b.is_regex, b.weight, b.enabled)
    await c.hub.reload_blacklist()
    return {"items": await c.store.list_blacklist()}


@R.add("/blacklist/{id:int}", ["PATCH"])
async def blacklist_update(request: Request, c: Any) -> dict:
    b = await parse(request, S.BlacklistPatch)
    need(await c.store.update_blacklist(request.path_params["id"], **b.model_dump(exclude_unset=True)), "phrase")
    await c.hub.reload_blacklist()
    return {"items": await c.store.list_blacklist()}


@R.add("/blacklist/{id:int}", ["DELETE"])
async def blacklist_delete(request: Request, c: Any) -> dict:
    need(await c.store.delete_blacklist(request.path_params["id"]), "phrase")
    await c.hub.reload_blacklist()
    return {"ok": True}


@R.add("/moderation/test", ["POST"])
async def moderation_test(request: Request, c: Any) -> dict:
    b = await parse(request, S.ModTest)
    level = b.level if b.level in (*LEVELS, "bot") else "everyone"
    v = c.engine.evaluate(ModInput("test", "tester", "tester", b.text, level), stateless=True)
    return {"verdict": v.to_dict(), "thresholds": _thresholds(c), "mode": c.cfg.get("mod_mode"),
            "note": "Content rules only. Rate, repeat, raid and timing checks need real chat history."}


@R.add("/moderation/pending", ["GET"])
async def moderation_pending(request: Request, c: Any) -> dict:
    return {"items": await c.store.pending_actions(_demo_filter(c))}


def _epoch(raw: str | None, name: str) -> float | None:
    """Reads a since/until query value: epoch seconds. Empty means no limit."""
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except ValueError:
        raise ApiError(f"'{name}' must be a time in epoch seconds.", 422) from None


@R.add("/moderation/history", ["GET"])
async def moderation_history(request: Request, c: Any) -> dict:
    q = request.query_params
    limit = max(1, min(int(q.get("limit", 100)), 500))
    items = await c.store.action_history(limit, q.get("status") or None, _demo_filter(c), since=_epoch(q.get("since"), "since"),
                                         until=_epoch(q.get("until"), "until"), q=(q.get("q") or "").strip()[:100] or None,
                                         offset=max(0, int(q.get("offset", 0))))
    return {"items": items}


@R.add("/moderation/{id:int}/{verb}", ["POST"])
async def moderation_resolve(request: Request, c: Any) -> dict:
    verb = request.path_params["verb"]
    if verb not in ("approve", "reject"):
        raise ApiError("Unknown action.", 404)
    id_ = request.path_params["id"]
    result = await (c.hub.approve(id_) if verb == "approve" else c.hub.reject(id_))
    if not result.get("ok"):
        raise ApiError(result.get("error") or "Could not complete that.", 409)
    return result | {"item": await c.store.get_action(id_)}


@R.add("/moderation/{verb}-all", ["POST"])
async def moderation_resolve_all(request: Request, c: Any) -> dict:
    verb = request.path_params["verb"]
    if verb not in ("approve", "reject"):
        raise ApiError("Unknown action.", 404)
    return await c.hub.resolve_all(verb == "approve", _demo_filter(c))


# ================================================================================= notes + reminders
@R.add("/notes", ["GET"])
async def notes_list(request: Request, c: Any) -> dict:
    return {"items": await c.store.list_notes()}


@R.add("/notes", ["POST"])
async def notes_create(request: Request, c: Any) -> dict:
    b = await parse(request, S.NoteIn)
    await c.store.add_note(b.body, b.tags, b.pinned)
    return {"items": await c.store.list_notes()}


@R.add("/notes/{id:int}", ["PATCH"])
async def notes_update(request: Request, c: Any) -> dict:
    b = await parse(request, S.NotePatch)
    need(await c.store.update_note(request.path_params["id"], **b.model_dump(exclude_unset=True)), "note")
    return {"items": await c.store.list_notes()}


@R.add("/notes/{id:int}", ["DELETE"])
async def notes_delete(request: Request, c: Any) -> dict:
    need(await c.store.delete_note(request.path_params["id"]), "note")
    return {"ok": True}


@R.add("/reminders", ["GET"])
async def reminders_list(request: Request, c: Any) -> dict:
    status_ = request.query_params.get("status", "pending")
    return {"items": await c.store.list_reminders(None if status_ == "all" else status_), "timezone": c.cfg.get("owner_timezone")}


@R.add("/reminders", ["POST"])
async def reminders_create(request: Request, c: Any) -> dict:
    b = await parse(request, S.ReminderIn)
    r = parse_reminder(f"{b.when.strip()} {b.text.strip()}", c.cfg.get("owner_timezone"))
    await c.store.add_reminder(r.text, to_epoch(r.due_utc), r.repeat, r.interval_seconds)
    return {"items": await c.store.list_reminders("pending")}


@R.add("/reminders/{id:int}", ["DELETE"])
async def reminders_cancel(request: Request, c: Any) -> dict:
    need(await c.store.cancel_reminder(request.path_params["id"]), "reminder")
    return {"ok": True}


# ================================================================================= chat, mode, demo, analytics
@R.add("/chat/recent", ["GET"])
async def chat_recent(request: Request, c: Any) -> dict:
    """The chat of the stream that is running now. A new stream always starts empty; older streams are in /streams."""
    limit = max(1, min(int(request.query_params.get("limit", 100)), 500))
    want_demo = _demo_filter(c)  # only the chat of the mode you are in; demo and live never mix
    items = [m for m in c.hub.buffer if bool(m.get("demo")) == want_demo][-limit:]
    sid = c.hub.session_id
    if not items and sid:
        items = await c.hub.sessions.chat(sid, limit=limit)
    cur = c.hub.status()["session"]
    # With no stream running, `items` is only what was left of the stream that just ended (or nothing); `last` says which stream that was.
    return {"items": items, "session": cur, "last": None if cur else await c.hub.sessions.last_finished(want_demo)}


@R.add("/chat/search", ["GET"])
async def chat_search(request: Request, c: Any) -> dict:
    """Search the stored chat by text, date range (since/until, epoch seconds) and moderation outcome."""
    q = request.query_params
    verdict = q.get("verdict") if q.get("verdict") in ("flagged", "blocked") else None
    limit = max(1, min(int(q.get("limit", 200)), 500))
    rows = await c.store.search_chat((q.get("q") or "").strip()[:100] or None, _epoch(q.get("since"), "since"), _epoch(q.get("until"), "until"),
                                     verdict, _demo_filter(c), limit)
    items = []
    for m in rows:
        m["text"], m["demo"] = m.pop("body"), bool(m["demo"])
        items.append(m | {"from_bot": m["level"] == "bot", "reasons": []})
    return {"items": items, "retention_days": c.cfg.get("chat_retention_days")}


@R.add("/chat/send", ["POST"])
async def chat_send(request: Request, c: Any) -> dict:
    b = await parse(request, S.ChatSend)
    if not await c.hub.send_chat(b.text, render=True):
        raise ApiError("Could not send. The stream has ended or the bot is not attached to a live chat. Standby will return once your next stream starts.", 409)
    return {"ok": True}


@R.add("/chat/demo", ["DELETE"])
async def chat_clear_demo(request: Request, c: Any) -> dict:
    await c.store.clear_demo_data()
    for m in [m for m in c.hub.buffer if m.get("demo")]:
        c.hub.buffer.remove(m)
    return {"ok": True}


@R.add("/mode", ["POST"])
async def set_mode(request: Request, c: Any) -> dict:
    b = await parse(request, S.ModeIn)
    await c.cfg.set("bot_mode", b.mode)
    return {"hub": await c.hub.apply_mode()}


@R.add("/analytics", ["GET"])
async def analytics(request: Request, c: Any) -> dict:
    hours = float(request.query_params.get("hours", 24))
    demo = _demo_filter(c)
    # 1.1.8: with Redis on, a few seconds of caching means many open dashboards (or instances) share one heavy query
    return await c.shared.cached(f"analytics:{hours}:{demo}", c.cfg.get("shared_cache_seconds"), lambda: summary(c.store, hours, demo=demo))


@R.add("/demo", ["GET"])
async def demo_info(request: Request, c: Any) -> dict:
    return {"status": c.demo.status(), "scenarios": c.demo.scenarios(), "active": c.cfg.get("bot_mode") == "demo"}


@R.add("/demo/scenario", ["POST"])
async def demo_scenario(request: Request, c: Any) -> dict:
    b = await parse(request, S.ScenarioIn)
    if c.cfg.get("bot_mode") != "demo":
        raise ApiError("Switch to demo mode first.", 409)
    if not c.demo.start_scenario(b.name):
        raise ApiError("Unknown scenario, or it is already running.", 409)
    return {"ok": True}


@R.add("/demo/sample", ["POST"])
async def demo_sample(request: Request, c: Any) -> dict:
    """Fills Demo with a few hours of believable history (chat, a flagged message, bans in different states) so pages that need history are not empty.
    Everything is marked demo, so it never mixes with live data, and "Clear demo data" removes it."""
    if c.hub.mode != "demo":
        raise ApiError("Switch to demo mode first. Sample history is only added in demo.", 409)
    now = time.time()
    people = [("u-ana", "Ana"), ("u-ben", "Ben"), ("u-cy", "Cy"), ("u-dee", "Dee"), ("u-eli", "Eli"), ("u-fay", "Fay")]
    lines = ["hello everyone", "great stream today", "that was close", "gg", "can you play the new level?", "lol", "first time here, hi!", "love this song", "how long have you been streaming?", "nice one"]
    n = 0
    for i in range(120):
        pid, name = people[i % len(people)]
        flagged = i % 29 == 7
        await c.store.add_chat({"platform": "demo", "msg_id": f"sample-{i}", "author_id": pid, "author_name": name, "ts": now - (120 - i) * 90, "demo": True,
                                "text": "free followers at spammy-site.example now!!!" if flagged else lines[i % len(lines)], "score": 80 if flagged else 0, "verdict": "flag" if flagged else "allow"})
        n += 1
    made = []
    for who, kind, secs in (("u-ben", "timeout", 600), ("u-cy", "ban", None), ("u-dee", "timeout", 60), ("u-fay", "ban", None)):
        name = dict(people)[who]
        made.append(await c.hub.bans.record(author_id=who, author_name=name, kind=kind, duration=secs, ban_ref="", action_id=None, source="auto" if who == "u-cy" else "dashboard", reason="Sample", platform="demo", demo=True))
    await c.hub.unban(made[3])
    return {"chat_lines": n, "bans": len(made)}


@R.add("/demo/ambient", ["POST"])
async def demo_ambient(request: Request, c: Any) -> dict:
    b = await parse(request, S.AmbientIn)
    if c.cfg.get("bot_mode") != "demo":
        raise ApiError("Switch to demo mode first.", 409)
    c.demo.set_ambient(b.on)
    return {"ok": True, "status": c.demo.status()}


# ================================================================================= integrations
@R.add("/youtube/status", ["GET"])
async def youtube_status(request: Request, c: Any) -> dict:
    return c.youtube.status() | {"connected": await c.google.connected()}


@R.add("/youtube/quota", ["POST"])
async def youtube_quota_set(request: Request, c: Any) -> dict:
    """YouTube does not tell apps how much quota is left, so SavahBot keeps an estimate. This corrects it (0 restarts the count)."""
    body = await parse(request, S.QuotaSet)
    await c.quota.set_used(body.used)
    return {"ok": True, "quota": c.quota.status()}


@R.add("/youtube/diagnostics", ["GET"])
async def youtube_diagnostics(request: Request, c: Any) -> dict:
    """Shows exactly what will be sent to Google. The client ID is public by design; the secret is never returned."""
    cid = str(c.cfg.get("google_client_id") or "")
    secret = str(c.cfg.get("google_client_secret") or "")
    redirect = c.google.redirect_uri()

    def check(ok: bool, good: str, bad: str) -> dict:
        return {"ok": ok, "text": good if ok else bad}

    checks = [
        check(bool(cid), "Client ID is set.", "GOOGLE_CLIENT_ID is empty or still edit-me."),
        check(not cid.lower().startswith(("http://", "https://")), "Client ID is not a web address.",
              "The Client ID starts with http:// or https://. Delete that part: it must begin directly with the numbers."),
        check(cid.endswith(".apps.googleusercontent.com"), "Client ID has the usual ending (.apps.googleusercontent.com).",
              "Client ID should end in .apps.googleusercontent.com. If it starts with GOCSPX-, it is the secret, not the ID."),
        check(cid == cid.strip() and not any(ch in cid for ch in " \t\r\n\"'"), "No spaces or quote marks around the Client ID.",
              "The Client ID contains a space, line break or quote mark. Paste it again with nothing around it."),
        check(not secret or secret != cid, "Client ID and secret are different values.", "Client ID and secret are the same value."),
        check(bool(secret), "Client secret is set.", "GOOGLE_CLIENT_SECRET is empty or still edit-me."),
        check(not secret or secret.startswith("GOCSPX-"), "Client secret has the usual GOCSPX- start.",
              "The secret normally starts with GOCSPX-. Check the two values are not swapped."),
        check(redirect.startswith("https://") or redirect.startswith("http://localhost"), "Redirect address is https.",
              "Redirect address is missing or not https. Set PUBLIC_BASE_URL to your Railway address."),
        check(redirect.endswith("/api/youtube/oauth/callback") and "//api" not in redirect, "Redirect address ends correctly.",
              "Redirect address should end in /api/youtube/oauth/callback with no doubled slash."),
    ]
    yt = c.youtube.status()
    target_raw = str(c.cfg.get("youtube_target_channel_id") or c.cfg.get("youtube_channel_id") or "")
    checks.append(check(bool(target_raw) and not target_raw.lower().startswith("edit-me"), "A target channel is set.",
                        "No target channel is set. Put the channel to moderate in YOUTUBE_TARGET_CHANNEL_ID, or press 'Moderate my own channel'."))
    return {
        "account": yt["account"], "target": yt["target"], "target_setting": target_raw,
        "client_id": cid, "client_id_length": len(cid), "secret_set": bool(secret), "secret_length": len(secret),
        "redirect_uri": redirect, "scope": c.cfg.get("google_oauth_scope"),
        "sign_in_url": c.google.auth_url("preview") if cid and redirect else "", "checks": checks,
        "note": "If every check passes and Google still says the client was not found, the client is missing in Google Cloud or has not propagated yet (can take up to a few hours).",
    }


@R.add("/youtube/verify", ["POST"])
async def youtube_verify(request: Request, c: Any) -> dict:
    """Ask YouTube what the signed-in account can really do for the target channel. Changes and moderates nothing."""
    return await c.youtube.diagnose()


@R.add("/youtube/oauth/start", ["POST"])
async def youtube_start(request: Request, c: Any) -> dict:
    if not (c.cfg.get("google_client_id") and c.cfg.get("google_client_secret")):
        raise ApiError("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET first (see the Setup page).", 409)
    if not c.google.redirect_uri():
        raise ApiError("Set PUBLIC_BASE_URL so Google knows where to send you back.", 409)
    return {"url": c.google.auth_url(c.google.new_state()), "redirect_uri": c.google.redirect_uri()}


@R.add("/reader/rules", ["GET"])
async def reader_rules_get(request: Request, c: Any) -> dict:
    """The chat reader's rules, shared by every device you sign in on. Voice, speed and volume stay on each device."""
    import json
    raw = await c.db.kv_get("reader_rules")
    return {**S.ReaderRules().model_dump(), **(json.loads(raw) if raw else {})}


@R.add("/reader/rules", ["POST"])
async def reader_rules_set(request: Request, c: Any) -> dict:
    b = await parse(request, S.ReaderRules)
    clean_dict = []
    for d in b.dictionary:
        a, z = (d.get("from") or "").strip()[:40], (d.get("to") or "").strip()[:60]
        if a and z:
            clean_dict.append({"from": a, "to": z})
    data = {**b.model_dump(), "dictionary": clean_dict}
    import json
    await c.db.kv_set("reader_rules", json.dumps(data))
    await c.activity.record("settings", "reader", "Changed the chat reader rules", "routine")
    return data


@R.add("/voices", ["GET"])
async def voices_list(request: Request, c: Any) -> dict:
    """Uploaded voice packs, the storage status (is it a folder that survives a redeploy?) and the optional model host link."""
    return {**c.voices.status(), "packs": c.voices.packs(), "host": await c.db.kv_get("voice_host", "") or "",
            "files_base": (c.settings.public_url or "") + "/api/voices/files/"}


@R.add("/voices/file", ["POST"])
async def voices_file(request: Request, c: Any) -> dict:
    """One file, sent as the raw request body. ?pack=name&path=folder/file.onnx. Zips go to /voices/zip."""
    from ..voices import VoiceError
    try:
        n = await c.voices.save_stream(request.query_params.get("pack", ""), request.query_params.get("path", ""), request.stream())
    except VoiceError as exc:
        raise ApiError(exc.message, exc.status) from None
    await c.activity.record("settings", "voices", f"Uploaded a voice file to {request.query_params.get('pack')}", "routine")
    return {"bytes": n}


@R.add("/voices/zip", ["POST"])
async def voices_zip(request: Request, c: Any) -> dict:
    from ..voices import VoiceError
    data = b""
    async for chunk in request.stream():
        data += chunk
        if len(data) > c.voices.max_bytes:
            raise ApiError("That zip is bigger than the voice file limit.", 413)
    try:
        n = c.voices.save_zip(request.query_params.get("pack", ""), data)
    except VoiceError as exc:
        raise ApiError(exc.message, exc.status) from None
    await c.activity.record("settings", "voices", f"Uploaded a voice pack zip ({n} files) to {request.query_params.get('pack')}", "routine")
    return {"files": n}


@R.add("/voices/delete", ["POST"])
async def voices_delete(request: Request, c: Any) -> dict:
    from ..voices import VoiceError
    b = await parse(request, S.VoiceDelete)
    try:
        gone = c.voices.delete(b.pack)
    except VoiceError as exc:
        raise ApiError(exc.message, exc.status) from None
    if gone:
        await c.activity.record("settings", "voices", f"Deleted the voice pack {b.pack}", "notable")
    return {"deleted": gone}


@R.add("/voices/host", ["POST"])
async def voices_host(request: Request, c: Any) -> dict:
    """A link to voice files you host yourself (https only). The browser, not the server, downloads from it."""
    from urllib.parse import urlparse
    b = await parse(request, S.VoiceHost)
    url = b.url.strip().rstrip("/")
    if url:
        p = urlparse(url)
        if p.scheme != "https" or not p.hostname or "." not in p.hostname:
            raise ApiError("Use a full https:// address.", 422)
    await c.db.kv_set("voice_host", url)
    return {"host": url}


@R.add("/voices/files/{pack}/{path:path}", ["GET"], public=True)
async def voices_serve(request: Request, c: Any) -> Response:
    """Serves one stored voice file to your browser. Public on purpose (the model loader cannot send your sign-in) and harmless: voice models only."""
    from starlette.responses import FileResponse
    p = c.voices.path_for(request.path_params["pack"], request.path_params["path"])
    if p is None:
        raise ApiError("No such voice file.", 404)
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400", "Access-Control-Allow-Origin": "*"})


@R.add("/chat/act", ["POST"])
async def chat_act(request: Request, c: Any) -> dict:
    """Delete a message, or time out or ban its author, from the chat. Returns ban_id so the page can offer Undo (which lifts it)."""
    b = await parse(request, S.ChatAct)
    res = await c.hub.manual(b.id, b.action, b.seconds)
    if not res["ok"]:
        raise ApiError(res["error"], res.get("code", 400))
    return res


@R.add("/chat/person", ["GET"])
async def chat_person(request: Request, c: Any) -> dict:
    """The person card: who this is, how long they have been around, what they said lately, and what has happened to them."""
    aid = request.query_params.get("author_id", "")
    platform = request.query_params.get("platform", "youtube")
    if not aid:
        raise ApiError("author_id is required.", 422)
    db = c.store.db
    stats = await db.fetchone("SELECT COUNT(*) AS n, MIN(ts) AS first, MAX(ts) AS last, MAX(author_name) AS name FROM chat_messages WHERE platform = ? AND author_id = ? AND level != 'bot'", (platform, aid))
    recent = await db.fetchall("SELECT id, ts, body, verdict FROM chat_messages WHERE platform = ? AND author_id = ? ORDER BY ts DESC, id DESC LIMIT 12", (platform, aid))
    actions = await db.fetchall("SELECT id, ts, kind, status, source, ban_ref FROM bans WHERE platform = ? AND author_id = ? ORDER BY ts DESC LIMIT 10", (platform, aid))
    notes = [n for n in await c.store.list_notes() if stats["name"] and f"@{stats['name']}".lower() in (n.get("body") or "").lower()][:5]
    return {"name": stats["name"], "messages": stats["n"], "first_seen": stats["first"], "last_seen": stats["last"], "recent": recent, "actions": actions,
            "notes": notes, "regular": bool(c.store.is_regular(aid, stats["name"] or ""))}


@R.add("/chat/costs", ["GET"])
async def chat_costs(request: Request, c: Any) -> dict:
    """What each chat action costs in YouTube quota today, so the page can show it before you confirm."""
    q = c.quota
    return {"delete": q.cost("chat_delete"), "timeout": q.cost("ban"), "ban": q.cost("ban"), "send": q.cost("chat_insert"), "remaining": q.remaining}


@R.add("/live/stats", ["GET"])
async def live_stats(request: Request, c: Any) -> dict:
    """Likes and viewers for the current stream, as YouTube last reported them, with how old that is."""
    out = await c.extras.stats()
    if c.hub.mode == "demo":
        out = demo_live_stats()
    return out


@R.add("/live/events", ["GET"])
async def live_events(request: Request, c: Any) -> dict:
    return {"items": await c.extras.recent_events(30)}


def demo_streams() -> list[dict]:
    """Three made-up past streams for Demo mode, so the Insights table and the per-stream graph can be tried."""
    now = time.time()
    return [{"video_id": f"demo-{i}", "started": now - (i + 1) * 86400 - 7200, "ended": now - (i + 1) * 86400, "peak_viewers": 60 + 25 * (3 - i), "likes": 140 + 60 * (3 - i), "samples": 120, "sample": True} for i in range(3)]


@R.add("/live/streams", ["GET"])
async def live_streams(request: Request, c: Any) -> dict:
    if c.hub.mode == "demo":
        return {"items": demo_streams(), "sample": True}
    return {"items": await c.extras.streams(20), "sample": False}


@R.add("/live/streams/{video_id}", ["GET"])
async def live_stream_detail(request: Request, c: Any) -> dict:
    """The recorded likes and viewers of one past stream, oldest first, for its graph."""
    import math
    vid = request.path_params["video_id"]
    if vid.startswith("demo-") and c.hub.mode == "demo":
        n = int(vid[5:] or 0) if vid[5:].isdigit() else 0
        base = time.time() - (n + 1) * 86400 - 7200
        return {"video_id": vid, "sample": True, "series": [{"ts": base + i * 60, "likes": 20 + i * (3 - n) * 2 + int(5 * math.sin(i / 5)), "viewers": 30 + int((20 + 10 * (3 - n)) * math.sin(i / 20 * math.pi / 2 + .3)) + i // 3} for i in range(120)]}
    rows = await c.db.fetchall("SELECT ts, likes, viewers FROM live_samples WHERE video_id = ? ORDER BY ts LIMIT 2000", (vid[:40],))
    return {"video_id": vid, "sample": False, "series": rows}


def demo_live_stats() -> dict:
    """Demo mode has no YouTube, so the live card shows a repeatable made-up stream and says so."""
    import math
    now = time.time()
    series = [{"ts": now - (59 - i) * 60, "likes": 120 + i * 3 + int(8 * math.sin(i / 4)), "viewers": 40 + int(25 * math.sin(i / 9) + i / 2)} for i in range(60)]
    return {"video_id": "demo", "likes": series[-1]["likes"], "viewers": series[-1]["viewers"], "updated": now - 12, "peak_viewers": max(p["viewers"] for p in series), "likes_hidden": False,
            "note": "", "likes_per_min": 3.4, "series": series, "sample": True, "subscribers": {"state": "demo", "note": "", "count": 1520, "checked": now - 60}, "cost_per_hour": 60, "enabled": True}


@R.add("/moderation/level", ["GET"])
async def moderation_level_get(request: Request, c: Any) -> dict:
    from ..moderation.levels import describe
    return describe(c.cfg)


@R.add("/moderation/level", ["POST"])
async def moderation_level_set(request: Request, c: Any) -> dict:
    """Apply a ready-made set of thresholds (basic, balanced, strict). The on/off mode is not changed."""
    from ..moderation.levels import LEVELS, describe
    b = await parse(request, S.ModLevel)
    if b.level not in LEVELS:
        raise ApiError("Pick basic, balanced or strict.", 422)
    for k, v in LEVELS[b.level]["values"].items():
        await c.cfg.set(k, v)
    await c.activity.record("moderation", "level", f"Auto-moderation level set to {LEVELS[b.level]['label']}", "notable")
    return describe(c.cfg)


@R.add("/activity", ["GET"])
async def activity_list(request: Request, c: Any) -> dict:
    """The activity log, newest first, filtered by area, importance, text and dates. `before` continues from the last id seen."""
    q = request.query_params

    def num(k: str, d: float = 0) -> float:
        try:
            return float(q.get(k, d))
        except ValueError:
            return d
    return await c.activity.query(q.get("area", ""), q.get("importance", ""), q.get("q", ""), num("since"), num("until"), int(num("before")), int(num("limit", 30)))


@R.add("/activity/export", ["GET"])
async def activity_export(request: Request, c: Any) -> Any:
    """Everything that matches, as a CSV file. Holds the same limited fields as the page, never secrets or message text."""
    import csv
    import io
    q = request.query_params
    res = await c.activity.query(q.get("area", ""), q.get("importance", ""), q.get("q", ""), 0, 0, 0, 200)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time", "area", "importance", "action", "summary", "before", "after"])
    for r in res["items"]:
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])), r["area"], r["importance"], r["action"], r["summary"], r["before_v"], r["after_v"]])
    from starlette.responses import Response
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=savahbot-activity.csv"})


@R.add("/variables", ["GET"])
async def variables_list(request: Request, c: Any) -> dict:
    """Your own variables with how many places use each, plus the built-ins their names must not clash with."""
    from ..variables import BUILTIN
    return {"variables": await c.variables.listing(), "builtin": [{"name": k, "help": v} for k, v in BUILTIN.items()]}


@R.add("/variables", ["POST"])
async def variables_save(request: Request, c: Any) -> dict:
    from ..variables import VariableError
    b = await parse(request, S.VariableIn)
    try:
        saved = await c.variables.save(b.name, b.value, b.kind, b.note, time.time())
    except VariableError as exc:
        raise ApiError(exc.message, exc.status) from None
    await c.activity.record("variables", "variable", f"{'Changed' if saved['replaced'] else 'Added'} $({saved['name']})", "routine", "", saved["value"] if saved["kind"] != "text" else "")
    return saved


@R.add("/variables/delete", ["POST"])
async def variables_delete(request: Request, c: Any) -> dict:
    """Without force, a variable that is still used is kept and the places using it are listed, so nothing breaks silently."""
    b = await parse(request, S.VariableDelete)
    used = await c.variables.delete(b.name, b.force)
    if used:
        names = ", ".join(f"{u['kind']} {u['name']}" for u in used[:6])
        raise ApiError(f"$({b.name}) is still used in {len(used)} place(s): {names}. Delete anyway and it will show as typed.", 409, "in_use")
    await c.activity.record("variables", "variable", f"Deleted $({b.name})", "notable")
    return {"deleted": b.name}


@R.add("/youtube/source", ["POST"])
async def youtube_source(request: Request, c: Any) -> dict:
    """Where the live stream comes from: search the channel automatically, a link you paste, or both (the link wins while it is live)."""
    from ..services.youtube import VIDEO_ID_RE, parse_video_id
    body = await parse(request, S.YoutubeSource)
    out: dict[str, Any] = {}
    if body.auto_detect is not None:
        await c.cfg.set("youtube_auto_detect_live", bool(body.auto_detect))
    if body.video is not None:
        raw = body.video.strip()
        if not raw:
            await c.cfg.set("youtube_video_id", "")
        else:
            vid = parse_video_id(raw)
            if not VIDEO_ID_RE.match(vid):
                raise ApiError("That does not look like a YouTube video link or ID. Paste the watch link, a youtu.be link, a /live/ link, or the 11-character ID.", 422)
            out["checked"] = False
            if await c.google.connected() and c.youtube.target and c.quota.can_afford("video_list"):
                await c.quota.spend(c.quota.cost("video_list"))
                status, data = await c.youtube._api("GET", "/videos", params={"part": "snippet,liveStreamingDetails", "id": vid})
                item = ((data.get("items") or [None])[0]) if status == 200 and isinstance(data, dict) else None
                if status == 200 and not item:
                    raise ApiError("YouTube does not know that video, or this account cannot see it.", 404)
                if item:
                    if (item.get("snippet") or {}).get("channelId") != c.youtube.target["channel_id"]:
                        raise ApiError("That video belongs to a different channel than the one you moderate, so SavahBot will not attach to it.", 409)
                    out.update(checked=True, title=(item.get("snippet") or {}).get("title", ""), live=bool((item.get("liveStreamingDetails") or {}).get("activeLiveChatId")))
            await c.cfg.set("youtube_video_id", vid)
        if c.youtube.chat_id and parse_video_id(c.cfg.get("youtube_video_id")) not in ("", c.youtube.video_id):
            c.youtube._detach()           # a different stream was chosen: leave the old chat
    c.youtube.nudge()
    return {**out, "ok": True, "source": c.youtube.source()}


@R.add("/youtube/use-own-channel", ["POST"])
async def youtube_use_own_channel(request: Request, c: Any) -> dict:
    """An explicit choice by the owner: moderate the signed-in account's own channel. SavahBot never assumes this by itself."""
    if not await c.google.connected():
        raise ApiError("Connect your Google account first.", 409)
    acct = c.youtube.account or await c.youtube.refresh_identity()
    if not acct or not acct.get("channel_id"):
        raise ApiError("This Google account has no YouTube channel of its own. Enter the target channel ID instead.", 409)
    await c.cfg.set("youtube_target_channel_id", acct["channel_id"])
    return {"ok": True, "target": acct["channel_id"], "title": acct.get("title", "")}


@R.add("/youtube/disconnect", ["POST"])
async def youtube_disconnect(request: Request, c: Any) -> dict:
    await c.google.disconnect()
    c.youtube.forget_identity()
    return {"ok": True}


@R.add("/telegram/status", ["GET"])
async def telegram_status(request: Request, c: Any) -> dict:
    return c.telegram.status()


@R.add("/telegram/mode", ["POST"])
async def telegram_mode(request: Request, c: Any) -> dict:
    b = await parse(request, S.ModeIn)
    await c.cfg.set("telegram_mode", b.mode)
    await c.telegram.apply_mode()
    return c.telegram.status()


@R.add("/telegram/test", ["POST"])
async def telegram_test(request: Request, c: Any) -> dict:
    if not c.telegram.configured:
        raise ApiError("Set TELEGRAM_BOT_TOKEN first.", 409)
    if not await c.telegram.owner_id():
        raise ApiError("Send /claim <your dashboard password> to the bot in Telegram first.", 409)
    await c.telegram.notify("Test message from the dashboard. Telegram is working.")
    if c.telegram.last_error:
        raise ApiError(c.telegram.last_error, 502)
    return {"ok": True}


# ================================================================================= live feed (Server-Sent Events)
@R.add("/events", ["GET"])
async def events(request: Request, c: Any) -> Any:
    if c.bus.subscriber_count >= c.cfg.get("sse_max_clients"):
        raise ApiError("Too many dashboards are connected.", 429)
    q = c.bus.subscribe()

    async def stream():
        try:
            yield "retry: 3000\n\n"
            yield f"data: {json.dumps({'type': 'hello', 'data': {'mode': c.cfg.get('bot_mode')}, 'ts': time.time()})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            c.bus.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


from . import knowledge_routes  # noqa: E402,F401  (Knowledge API, Settings > Knowledge)
from . import bans_routes  # noqa: E402,F401  (Ban management API)
from . import history_routes  # noqa: E402,F401  (long-range chart history)
from . import stream_routes  # noqa: E402,F401  (stream history: one session per livestream)
from . import access_routes  # noqa: E402,F401  (sign-in and Security & Access Centre)
from . import backup_routes  # noqa: E402,F401  (encrypted backup and restore)
from . import notify_routes  # noqa: E402,F401  (Notification Centre)
from . import weather_routes  # noqa: E402,F401  (Weather)
from . import system_routes  # noqa: E402,F401  (Settings hub, system health, data)
from . import telegram_routes  # noqa: E402,F401  (Telegram control)
