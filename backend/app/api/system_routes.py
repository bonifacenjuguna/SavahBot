"""Settings hub and system information: what needs attention, service health, data inventory and safe clean-up.

Everything reported here is read from the running system. Nothing is guessed, and no secret value ever leaves the server: only
"set / not set" and short, non-sensitive facts.
"""
from __future__ import annotations

import platform
import sys
import time
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict
from starlette.requests import Request

from .. import __version__
from .routes import ApiError, R, client_ip, parse


class Clear(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str
    confirm: bool = False


def _host(url: str) -> str:
    return urlparse(url).netloc if url else ""


def validate(c: Any) -> list[dict[str, str]]:
    """Plain-language problems with the configuration. Each one says what is wrong and what to do."""
    s, out = c.settings, []

    def add(level: str, text: str, route: str = "#/setup") -> None:
        out.append({"level": level, "text": text, "route": route})

    if not s.frontend_url:
        add("warn", "FRONTEND_URL is not set. The dashboard may be blocked by CORS, and passkeys need it to know your site's address.")
    elif not s.frontend_url.startswith("https://") and s.app_env == "production":
        add("warn", "FRONTEND_URL is not https. Passkeys and push notifications only work on https sites.")
    if not (s.public_base_url or ""):
        add("info", "PUBLIC_BASE_URL is not set (Railway fills it from its own domain). The Telegram webhook and Google sign-in need it.")
    firebase = [bool(c.notifier.fcm.project), bool(c.notifier.fcm.email), bool(c.notifier.fcm._pem)]
    web = [bool(s.firebase_web_api_key), bool(s.firebase_web_app_id), bool(s.firebase_messaging_sender_id), bool(s.firebase_vapid_key)]
    if any(firebase + web) and not (all(firebase) and all(web)):
        add("warn", "Push notifications are only partly configured. Open Notifications to see which Firebase values are missing.", "#/notifications")
    if not c.shared.configured:
        add("info", "Redis is not configured. SavahBot works in memory; with more than one server instance, add Redis so they share state.", "#/settings?tab=developer")
    if int(c.settings.__dict__.get("redis_leader_ttl_seconds", 30)) < 10:
        add("warn", "REDIS_LEADER_TTL_SECONDS is very low. Leader election may flap.")
    return out


@R.add("/settings/overview", ["GET"])
async def settings_overview(request: Request, c: Any) -> dict:
    a, now = c.access, time.time()
    e = await a.enrolled()
    methods = await a.methods()
    sessions = len(await a.sessions(request.state.session["id"] if "id" in request.state.session else ""))
    yt, tg = c.youtube.status(), c.telegram.status()
    n = c.notifier
    devs = await n.devices()
    prefs = await n.prefs()
    wloc = await c.weather.get_location()
    wprefs = await c.weather.prefs()
    last_export = await c.db.kv_get("backup_last_export")
    unread = await n.unread()
    sec = {"methods": methods, "enforced": methods >= 2, "totp": e["totp"], "passkeys": len(e["passkeys"]), "recovery_left": e["recovery_left"], "lockdown": a.lockdown, "sessions": sessions}
    notif = {"push_ready": n.fcm.configured and n.web_ready(), "devices": sum(1 for d in devs if d["enabled"]), "unread": unread, "enabled": prefs["enabled"],
             "paused": now < prefs["pause_until"], "quiet_enabled": prefs["quiet"]["enabled"]}
    weather = {"location": wloc["name"] if wloc else None, "alerts": wprefs["alerts"]["enabled"], "units": f"{wprefs['temp'].upper()}"}
    backup = {"last_export": float(last_export) if last_export else None}
    integ = {"youtube": {"connected": bool(await c.google.connected()), "error": yt["last_error"] or "", "quota_fraction": yt["quota"]["fraction"]},
             "telegram": {"configured": tg["configured"], "owner_bound": tg["owner_bound"], "error": tg["last_error"] or ""},
             "firebase": {"configured": n.fcm.configured}, "weather": {"provider": c.weather.provider.name}}
    attention: list[dict[str, str]] = []

    def need(level: str, text: str, route: str) -> None:
        attention.append({"level": level, "text": text, "route": route})

    if methods < 2:
        need("warn", "Only the password protects sign-in. Add an authenticator app or a passkey to turn on two-method sign-in.", "#/security")
    if a.lockdown:
        need("bad", "Lockdown is on. Other devices are signed out until you lift it.", "#/security")
    elif methods >= 2 and e["recovery_left"] == 0:
        need("warn", "You have no recovery codes left. Create new ones so you can get back in if a device is lost.", "#/security")
    if not integ["youtube"]["connected"]:
        need("info", "YouTube is not connected. Live moderation needs it.", "#/setup")
    if integ["youtube"]["error"]:
        need("warn", f"YouTube reported: {integ['youtube']['error'][:120]}", "#/setup")
    if tg["last_error"]:
        need("warn", f"Telegram reported: {tg['last_error'][:120]}", "#/setup")
    if yt["quota"]["fraction"] >= 0.9:
        need("warn", "YouTube quota is above 90% for today.", "#/setup")
    if not backup["last_export"]:
        need("info", "You have never exported a backup. Make one so you can recover from a lost server.", "#/backup")
    elif now - backup["last_export"] > 30 * 86400:
        need("info", "Your last backup export is over 30 days old.", "#/backup")
    if not notif["devices"]:
        need("info", "No device receives push notifications yet.", "#/notifications")
    if wloc is None:
        need("info", "No weather place is set.", "#/weather")
    need_cfg = validate(c)
    attention.extend(need_cfg)
    order = {"bad": 0, "warn": 1, "info": 2}
    attention.sort(key=lambda x: order.get(x["level"], 3))
    return {"security": sec, "notifications": notif, "weather": weather, "backup": backup, "integrations": integ, "attention": attention,
            "system": {"db": c.db.backend, "redis": c.shared.status()["mode"], "version": __version__, "mode": c.cfg.get("bot_mode")}}


@R.add("/system/health", ["GET"])
async def system_health(request: Request, c: Any) -> dict:
    now = time.time()
    db_ok, db_ms = True, 0.0
    try:
        t = time.perf_counter()
        await c.db.fetchone("SELECT 1 AS ok")
        db_ms = round((time.perf_counter() - t) * 1000, 1)
    except Exception:
        db_ok = False
    sh = c.shared.status()
    sch = c.scheduler
    s = c.settings
    return {
        "app": {"name": c.cfg.get("app_name"), "version": __version__, "env": s.app_env, "python": platform.python_version(), "platform": platform.system(), "uptime": int(now - c.started_at),
                "mode": c.cfg.get("bot_mode")},
        "database": {"backend": c.db.backend, "ok": db_ok, "latency_ms": db_ms, "schema_version": await c.db.schema_version()},
        "redis": {"configured": sh["configured"], "mode": sh["mode"], "instance": sh["instance"], "error": sh["error"], "leader": bool(c.leader.is_leader)},
        "background": {"scheduler_last_tick": sch.last_tick or None, "scheduler_seconds_ago": int(now - sch.last_tick) if sch.last_tick else None, "hooks": len(sch.hooks),
                       "notifications_listening": c.notifier._task is not None and not c.notifier._task.done()},
        "events": {"subscribers": c.bus.subscriber_count},
        "cache": {"weather_entries": len(c.weather._mem), "weather_provider": c.weather.provider.name},
        "features": {"youtube": bool(await c.google.connected()), "telegram": bool(c.telegram.configured), "push": bool(c.notifier.fcm.configured and c.notifier.web_ready()), "weather": True,
                     "redis": sh["configured"], "passkeys": bool(s.frontend_url), "backup_encryption": True},
        "deployment": {"backend_host": _host(s.public_base_url), "frontend_host": _host(s.frontend_url), "python_executable_in_venv": sys.prefix != sys.base_prefix},
        "config_problems": validate(c),
        "secrets": {"jwt_secret_set": bool(getattr(c.access, "_secret", "")), "owner_password_set": bool(s.owner_password), "google_client_secret_set": bool(s.google_client_secret),
                    "telegram_bot_token_set": bool(c.cfg.get("telegram_bot_token")), "firebase_key_set": bool(c.notifier.fcm._pem)},
    }


# What the bot stores, in words. Counts come from the database.
INVENTORY = [
    ("chat_messages", "Chat history", "Messages from the stream chat, kept for the chat retention period. Daily totals are kept forever.", "chat_retention_days", True),
    ("mod_actions", "Moderation history", "What the bot did and why, kept for the action retention period.", "action_retention_days", True),
    ("notifications", "Notification history", "The bell and history on the Notifications page.", "notify_retention_days", True),
    ("notify_deliveries", "Push delivery log", "Which pushes were sent, retried or failed.", "notify_retention_days", True),
    ("notify_devices", "Push devices", "Registered browsers and phones (tokens are encrypted).", None, False),
    ("weather_locations", "Weather places", "Places you saved (rounded coordinates).", None, False),
    ("notes", "Notes", "Your notebook.", None, False),
    ("reminders", "Reminders", "Your reminders.", None, False),
    ("bans", "Ban ledger", "Bans and timeouts the bot made, so they can be lifted.", None, False),
    ("access_audit", "Security audit log", "Changes to how you sign in. Protected: cannot be cleared here.", "security_log_retention_days", False),
    ("access_events", "Sign-in activity", "Sign-in attempts and results. Protected: cannot be cleared here.", "security_log_retention_days", False),
]
CLEARABLE = {"notifications": "Notification history", "notify_deliveries": "Push delivery log", "weather_cache": "Weather cache"}


@R.add("/system/data", ["GET"])
async def system_data(request: Request, c: Any) -> dict:
    rows = []
    for table, label, text, retention, clearable in INVENTORY:
        n = (await c.db.fetchone(f"SELECT COUNT(*) AS n FROM {table}"))["n"]
        rows.append({"id": table, "label": label, "text": text, "count": n, "retention_days": c.cfg.get(retention) if retention else None, "clearable": clearable and table in CLEARABLE, "protected": table.startswith("access_")})
    rows.append({"id": "weather_cache", "label": "Weather cache", "text": "Recent forecasts kept so the page is fast. Rebuilt on demand.", "count": len(c.weather._mem), "retention_days": None, "clearable": True, "protected": False})
    return {"items": rows, "stored_where": {"database": c.db.backend, "cache": "Redis" if c.shared.configured else "memory only",
            "processors": ["YouTube (chat and moderation actions)", "Telegram (messages you receive)", "Open-Meteo (place coordinates for forecasts)", "Firebase (push messages, if you turn it on)"]},
            "export_note": "Use Backup to export settings, content and history in an encrypted file.", "never_collected": ["Passwords in plain text", "Authenticator secrets in logs", "Your precise location unless you press the button"]}


@R.add("/system/data/clear", ["POST"])
async def system_clear(request: Request, c: Any) -> dict:
    b = await parse(request, Clear)
    if b.target not in CLEARABLE:
        raise ApiError("That data cannot be cleared here. Security records are protected on purpose.", 400)
    if not b.confirm:
        raise ApiError("Confirm to clear this data.", 400)
    if b.target == "weather_cache":
        n = len(c.weather._mem)
        c.weather._mem.clear()
    else:
        n = await c.db.execute(f"DELETE FROM {b.target}")
    await c.access.audit("data_cleared", request.state.session, client_ip(request), b.target)
    return {"cleared": n}
