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

from .. import __version__
from ..analytics import summary
from ..commands import BUILTIN_NAMES
from ..config import BY_NAME
from ..models import ChatMessage
from ..moderation import ModInput
from ..store import LEVELS, ValidationFailed
from ..timeparse import ReminderParseError, parse_reminder
from ..utils import to_epoch
from . import schemas as S

logger = logging.getLogger("savahbot.api")


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message, self.status = message, status


class Registry:
    def __init__(self) -> None:
        self.routes: list[Route] = []

    def add(self, path: str, methods: list[str], public: bool = False) -> Callable:
        def deco(fn: Callable[[Request, Any], Awaitable[Any]]) -> Callable:
            async def endpoint(request: Request) -> Response:
                c = request.app.state.c
                try:
                    if not public:
                        header = request.headers.get("authorization", "")
                        if not (header.lower().startswith("bearer ") and c.auth.verify(header[7:].strip())):
                            raise ApiError("Sign in to continue.", 401)
                    result = await fn(request, c)
                    return result if isinstance(result, Response) else JSONResponse(result)
                except ApiError as exc:
                    return JSONResponse({"error": exc.message}, status_code=exc.status)
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
            "database": c.db.backend, "uptime": round(time.time() - c.started_at)}


@R.add("/auth/login", ["POST"], public=True)
async def login(request: Request, c: Any) -> Any:
    body = await parse(request, S.Login)
    key = client_ip(request)
    wait = c.auth.throttle.retry_after(key)
    if wait:
        raise ApiError(f"Too many attempts. Try again in {wait} seconds.", 429)
    if not c.auth.check_password(body.password):
        c.auth.throttle.fail(key)
        await asyncio.sleep(0.4)
        raise ApiError("That password is not right.", 401)
    c.auth.throttle.success(key)
    token, ttl = c.auth.issue_token()
    return {"token": token, "expires_in": ttl}


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
            return RedirectResponse(f"{front}/#/setup?youtube={'connected' if ok else 'error'}&message={quote(message)}", status_code=303)
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
        "pending": len(await c.store.pending_actions()), "database": c.db.backend, "uptime": round(time.time() - c.started_at),
        "sse_clients": c.bus.subscriber_count,
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
    await c.store.create_timer(b.name, b.message, b.interval_seconds, b.min_lines, b.enabled)
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
@R.add("/blacklist", ["GET"])
async def blacklist_list(request: Request, c: Any) -> dict:
    return {"items": await c.store.list_blacklist()}


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
    return {"verdict": v.to_dict(), "note": "Content rules only. Rate, repeat, raid and timing checks need real chat history."}


@R.add("/moderation/pending", ["GET"])
async def moderation_pending(request: Request, c: Any) -> dict:
    return {"items": await c.store.pending_actions()}


@R.add("/moderation/history", ["GET"])
async def moderation_history(request: Request, c: Any) -> dict:
    q = request.query_params
    limit = max(1, min(int(q.get("limit", 100)), 500))
    return {"items": await c.store.action_history(limit, q.get("status") or None)}


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
    return await c.hub.resolve_all(verb == "approve")


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
    limit = max(1, min(int(request.query_params.get("limit", 100)), 500))
    items = list(c.hub.buffer)[-limit:]
    if not items:
        items = [m | {"from_bot": m["level"] == "bot", "reasons": []} for m in await c.store.recent_chat(limit)]
        for m in items:
            m["text"], m["demo"] = m.pop("body"), bool(m["demo"])
    return {"items": items}


@R.add("/chat/send", ["POST"])
async def chat_send(request: Request, c: Any) -> dict:
    b = await parse(request, S.ChatSend)
    if not await c.hub.send_chat(b.text):
        raise ApiError("Could not send. The chat source is not connected to a live chat.", 409)
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
    return await summary(c.store, hours, demo=_demo_filter(c))


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
