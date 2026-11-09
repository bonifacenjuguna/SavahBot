"""Telegram: owner-only control of SavahBot, via webhook (recommended on Railway) or long polling.

Security: only one Telegram account is ever obeyed. Everyone else is silently ignored (the bot does not
even reveal that it exists). The owner id comes from TELEGRAM_OWNER_ID, or is bound once with
/claim <OWNER_PASSWORD>. Webhook requests must carry the secret token Telegram was given.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import re
import secrets
import time
from datetime import timezone
from html import unescape
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from ..analytics import summary
from ..http import NetworkError, request_json
from ..timeparse import ReminderParseError, parse_reminder
from ..utils import format_duration, from_epoch, to_epoch, truncate
from . import telegram_ui as ui
from .telegram_ui import Rich, esc

logger = logging.getLogger("savahbot.telegram")
WEBHOOK_PATH = "/api/telegram/webhook"
Buttons = "list[list[tuple[str, str]]] | None"

HELP = Rich(ui.card("SavahBot commands", [
    "📊 <b>Status</b>",
    "/status  overview    /stats [hours]  numbers    /quota  YouTube quota",
    "",
    "🎛 <b>Modes</b>",
    "/mode demo|live    /mod off|suggest|auto    /tgmode webhook|polling",
    "",
    "🛡 <b>Moderation</b>",
    "/pending  what waits for you",
    "/approve &lt;id|all&gt;    /reject &lt;id|all&gt;",
    "/permit &lt;user&gt; [seconds]  allow links briefly",
    "/lockdown  sign every dashboard device out now\n    /bans  active bans and timeouts    /unban &lt;id|name&gt;  lift one",
    "/history [date] [status]  what the bot did",
    "",
    "💬 <b>Chat</b>",
    "/say &lt;text&gt;  post in the stream chat",
    "/find &lt;text&gt; [date]  search saved chat",
    "/demo [scenario]  simulated chat",
    "",
    "🌦 <b>Weather</b>",
    "/weather [place]  now    /forecast [place]  days    /hourly [place]  next hours",
    "/locations [number]  saved places, set the default",
    "",
    "🗒 <b>Notes and reminders</b>",
    "/note &lt;text&gt;    /notes    /delnote &lt;id&gt;",
    "/remind &lt;when&gt; &lt;text&gt;    /reminders    /delremind &lt;id&gt;",
    "when: 30m, 2h, 18:30, tomorrow 09:00, 2026-11-05 14:00, daily 08:00, every 2h",
    "",
    "🗓 <b>Date words</b> (for /find and /history)",
    "<code>" + ui.RANGE_HELP + "</code>",
], "Tip: /menu opens buttons for all of this.", "🤖"))


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg

    async def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 15.0) -> Any:
        token = self.cfg.get("telegram_bot_token")
        if not token:
            raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
        url = f"{self.cfg.get('telegram_api_base').rstrip('/')}/bot{token}/{method}"
        try:
            status, data = await request_json("POST", url, json_body=params or {}, timeout=timeout)
        except NetworkError as exc:
            raise TelegramError(f"{method}: network error ({exc})") from None  # never include the URL: it holds the token
        if isinstance(data, dict) and data.get("ok"):
            return data.get("result")
        desc = data.get("description") if isinstance(data, dict) else str(data)[:100]
        raise TelegramError(f"{method}: {desc} (HTTP {status})")

    async def send(self, chat_id: int, text: str, buttons: Any = None) -> Any:
        params: dict[str, Any] = {"chat_id": chat_id, "text": truncate(text, 4000), "disable_web_page_preview": True}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]}
        return await self._deliver("sendMessage", params, text)

    async def edit(self, chat_id: int, message_id: int, text: str, buttons: Any = None) -> Any:
        params: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": truncate(text, 4000), "disable_web_page_preview": True}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]}
        return await self._deliver("editMessageText", params, text)

    async def _deliver(self, method: str, params: dict[str, Any], original: str) -> Any:
        """Rich text goes as Telegram HTML. If Telegram cannot parse it (a tag cut by the length limit, say) the same message is
        sent again as plain text with the tags removed, so a notification is never lost to formatting."""
        if not isinstance(original, Rich):
            return await self.call(method, params)
        try:
            return await self.call(method, params | {"parse_mode": "HTML"})
        except TelegramError as exc:
            if "parse entities" not in str(exc) and "can't parse" not in str(exc).lower():
                raise
            plain = unescape(re.sub(r"<[^>]+>", "", original))
            return await self.call(method, params | {"text": truncate(plain, 4000)})


class TelegramBot:
    def __init__(self, c: Any) -> None:
        self.c = c
        self.cfg = c.cfg
        self.client = TelegramClient(c.cfg)
        self.me: dict[str, Any] | None = None
        self.last_error = ""
        self.last_update = 0.0
        self.webhook_url = ""
        self._offset = 0
        self._poll_task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self._owner: int | None = None
        self._commands: dict[str, Callable[[str], Awaitable[Any]]] = {}

    # ------------------------------------------------------------------ lifecycle
    @property
    def configured(self) -> bool:
        return bool(self.cfg.get("telegram_bot_token"))

    async def start(self) -> None:
        if not self.configured:
            return
        self.last_error = ""
        try:
            self.me = await self.client.call("getMe")
            await self.client.call("setMyCommands", {"commands": [
                {"command": "menu", "description": "Open the button menu"}, {"command": "status", "description": "Overview"},
                {"command": "pending", "description": "Requests waiting for you"}, {"command": "mode", "description": "demo or live"},
                {"command": "mod", "description": "off, suggest or auto"}, {"command": "stats", "description": "Chat numbers"},
                {"command": "find", "description": "Search saved chat, with dates"}, {"command": "history", "description": "What the bot did"},
                {"command": "weather", "description": "Weather now (add a place)"}, {"command": "forecast", "description": "Daily forecast"},
                {"command": "hourly", "description": "Next hours"}, {"command": "locations", "description": "Saved weather places"},
                {"command": "help", "description": "All commands"}]})
            await self.apply_mode()  # sets last_error itself if the mode cannot be applied
        except TelegramError as exc:
            self.last_error = str(exc)
            logger.error("Telegram start failed: %s", exc)

    async def stop(self) -> None:
        await self._stop_polling()
        for t in list(self._tasks):
            t.cancel()

    async def _stop_polling(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            await asyncio.gather(self._poll_task, return_exceptions=True)
            self._poll_task = None

    async def webhook_secret(self) -> str:
        secret = self.cfg.get("telegram_webhook_secret") or await self.c.db.kv_get("telegram_webhook_secret")
        if not secret:
            secret = secrets.token_urlsafe(24)
            await self.c.db.kv_set("telegram_webhook_secret", secret)
        return secret

    async def apply_mode(self) -> None:
        if not self.configured:
            return
        mode = self.cfg.get("telegram_mode")
        try:
            if mode == "webhook":
                await self._stop_polling()
                base = self.cfg.public_url
                if not base:
                    self.last_error = "Set PUBLIC_BASE_URL (or deploy on Railway with a public domain) to use webhook mode."
                    return
                self.webhook_url = base + WEBHOOK_PATH
                await self.client.call("setWebhook", {
                    "url": self.webhook_url, "secret_token": await self.webhook_secret(),
                    "max_connections": max(1, min(100, self.cfg.get("telegram_webhook_max_connections"))),
                    "allowed_updates": [u.strip() for u in self.cfg.get("telegram_allowed_updates").split(",") if u.strip()],
                    "drop_pending_updates": self.cfg.get("telegram_drop_pending_updates")})
            else:
                await self.client.call("deleteWebhook", {"drop_pending_updates": self.cfg.get("telegram_drop_pending_updates")})
                self.webhook_url = ""
                if self._poll_task is None or self._poll_task.done():
                    self._poll_task = asyncio.ensure_future(self._poll_loop())
            self.last_error = ""
        except TelegramError as exc:
            self.last_error = str(exc)
            logger.error("Telegram mode change failed: %s", exc)

    async def _poll_loop(self) -> None:
        backoff = 2.0
        while True:
            try:
                timeout = self.cfg.get("telegram_poll_timeout")
                updates = await self.client.call("getUpdates", {
                    "offset": self._offset, "timeout": timeout,
                    "allowed_updates": [u.strip() for u in self.cfg.get("telegram_allowed_updates").split(",") if u.strip()],
                }, timeout=timeout + 10)
                backoff = 2.0
                for u in updates or []:
                    self._offset = max(self._offset, int(u["update_id"]) + 1)
                    await self.handle_update(u)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                logger.warning("Telegram polling error: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)

    async def handle_webhook(self, secret_header: str | None, update: dict[str, Any]) -> bool:
        """Returns False if the request is not from Telegram. Processing continues in the background."""
        expected = await self.webhook_secret()
        if not secret_header or not hmac.compare_digest(secret_header.encode(), expected.encode()):
            return False
        task = asyncio.ensure_future(self.handle_update(update))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured, "mode": self.cfg.get("telegram_mode"), "bot_username": (self.me or {}).get("username"),
            "owner_bound": bool(self._owner or self.cfg.get("telegram_owner_id")), "webhook_url": self.webhook_url,
            "polling": bool(self._poll_task and not self._poll_task.done()), "last_error": self.last_error,
            "last_update": self.last_update or None,
        }

    # ------------------------------------------------------------------ owner
    async def owner_id(self) -> int:
        if self.cfg.get("telegram_owner_id"):
            return int(self.cfg.get("telegram_owner_id"))
        if self._owner is None:
            self._owner = int(await self.c.db.kv_get("telegram_owner_id", "0") or 0)
        return self._owner

    async def notify(self, text: str, buttons: Any = None) -> None:
        owner = await self.owner_id()
        if owner and self.configured:
            try:
                await self.client.send(owner, text, buttons)
            except TelegramError as exc:
                self.last_error = str(exc)
                logger.warning("Could not notify owner: %s", exc)

    # ------------------------------------------------------------------ updates
    async def handle_update(self, u: dict[str, Any]) -> None:
        try:
            self.last_update = time.time()
            if "callback_query" in u:
                await self._callback(u["callback_query"])
            elif "message" in u:
                await self._message(u["message"])
        except Exception:
            logger.exception("Telegram update failed")

    async def _message(self, m: dict[str, Any]) -> None:
        user_id = (m.get("from") or {}).get("id")
        chat = m.get("chat") or {}
        text = (m.get("text") or "").strip()
        if not user_id or chat.get("type") != "private" or not text.startswith("/"):
            return
        cmd, _, arg = text.partition(" ")
        cmd = cmd[1:].split("@")[0].lower()
        arg = arg.strip()
        owner = await self.owner_id()
        if not owner:
            if cmd == "claim":
                await self._claim(user_id, arg)
            return
        if user_id != owner or chat.get("id") != owner:
            return  # not the owner: say nothing
        handler = {
            "start": self._home, "menu": self._home, "help": self._help, "status": self._status, "stats": self._stats, "quota": self._quota,
            "mode": self._mode, "mod": self._mod, "tgmode": self._tgmode, "pending": self._pending,
            "approve": self._approve, "reject": self._reject, "permit": self._permit, "say": self._say, "demo": self._demo,
            "note": self._note, "notes": self._notes, "delnote": self._delnote,
            "remind": self._remind, "reminders": self._reminders, "delremind": self._delremind,
            "history": self._history, "find": self._find, "bans": self._bans, "lockdown": self._lockdown, "unban": self._unban,
            "weather": self._weather, "forecast": self._forecast, "hourly": self._hourly, "locations": self._locations,
        }.get(cmd)
        if handler is None:
            await self.client.send(owner, "Unknown command. Send /help for the list, or /menu for buttons.")
            return
        result = await handler(arg)
        if isinstance(result, tuple):
            await self.client.send(owner, result[0], result[1])
        elif result:
            await self.client.send(owner, result)

    async def _claim(self, user_id: int, password: str) -> None:
        key = f"tg:{user_id}"
        auth = self.c.auth
        if await auth.throttle.retry_after(key) or not auth.check_password(password):
            await auth.throttle.fail(key)
            return
        await auth.throttle.success(key)
        await self.c.db.kv_set("telegram_owner_id", str(user_id))
        self._owner = user_id
        await self.client.send(user_id, Rich("🎉 <b>You are now the owner of this bot.</b>\nOnly your account can use it. Tap /menu to see what it can do."),
                               ui.home_keyboard())

    # ------------------------------------------------------------------ buttons
    #: views the menu buttons can open in place: name -> handler taking the part after the second colon
    def _views(self) -> dict[str, Callable[[str], Awaitable[Any]]]:
        return {"home": self._home, "status": self._status, "stats": self._stats, "modes": self._modes, "notes": self._notes,
                "rem": self._reminders, "history": self._history, "help": self._help_view}

    async def _callback(self, q: dict[str, Any]) -> None:
        owner = await self.owner_id()
        if not owner or (q.get("from") or {}).get("id") != owner:
            return
        data = q.get("data") or ""
        action, _, raw = data.partition(":")
        msg = q.get("message") or {}
        qid = q["id"]
        if action in ("approve", "reject") and raw.isdigit():
            await self._decide(q, action, int(raw))
            return
        try:
            if action == "m":
                name, _, part = raw.partition(":")
                if name == "pending":
                    await self.client.call("answerCallbackQuery", {"callback_query_id": qid})
                    await self._pending_cards()
                    return
                view = self._views().get(name)
                if view:
                    await self.client.call("answerCallbackQuery", {"callback_query_id": qid})
                    await self._show(msg, await view(part))
                    return
            elif action == "set":
                kind, _, value = raw.partition(":")
                note = await (self._mode(value) if kind == "bot" else self._mod(value))
                note = note[0] if isinstance(note, tuple) else note
                await self.client.call("answerCallbackQuery", {"callback_query_id": qid, "text": truncate(re.sub(r"\s*Use /.*$", "", str(note)), 150)})
                await self._show(msg, await self._modes(""))
                return
        except TelegramError as exc:
            if "not modified" not in str(exc):
                self.last_error = str(exc)
                logger.warning("Telegram menu failed: %s", exc)
        await self.client.call("answerCallbackQuery", {"callback_query_id": qid})

    async def _show(self, msg: dict[str, Any], view: Any) -> None:
        """Replaces the message a button was pressed on with a new view (text and buttons together)."""
        if not (msg.get("chat") and msg.get("message_id")):
            return
        text, buttons = view if isinstance(view, tuple) else (view, None)
        await self.client.edit(msg["chat"]["id"], msg["message_id"], text, buttons)

    async def _decide(self, q: dict[str, Any], action: str, id_: int) -> None:
        res = await (self.c.hub.approve(id_) if action == "approve" else self.c.hub.reject(id_))
        note = ("Done: " + res.get("status", "")) if res.get("ok") else res.get("error", "Failed")
        await self.client.call("answerCallbackQuery", {"callback_query_id": q["id"], "text": note[:150]})
        msg = q.get("message") or {}
        if msg.get("chat") and msg.get("message_id"):
            mark = "✅" if res.get("ok") and action == "approve" else "🚫" if res.get("ok") else "⚠️"
            try:
                await self.client.call("editMessageText", {
                    "chat_id": msg["chat"]["id"], "message_id": msg["message_id"],
                    "text": truncate((msg.get("text") or "") + f"\n\n{mark} {action.capitalize()}: {note}", 4000)})
            except TelegramError:
                pass

    # ------------------------------------------------------------------ views
    @property
    def _tz(self) -> str:
        return self.cfg.get("owner_timezone")

    async def _home(self, _: str = "") -> Any:
        pending = len(await self.c.store.pending_actions())
        st = self.c.hub.status()
        live = "🔴 on air" if st["stream_live"] else ("🧪 demo" if st["mode"] == "demo" else "⚫ standby")
        rows = [ui.kv("🛰", "Now", live), ui.kv("🛡", "Moderation", f"{ui.mode_dot(st['mod_mode'])} {esc(st['mod_mode'])}"),
                ui.kv("⏳", "Waiting", f"<b>{pending}</b>" if pending else "nothing")]
        return Rich(ui.card(str(self.cfg.get("app_name")), rows, "Pick something below.", "🤖")), ui.home_keyboard(pending)

    async def _help(self, _: str = "") -> Any:
        return HELP, [ui.back_row()]

    async def _help_view(self, _: str = "") -> Any:
        return await self._help()

    async def _status(self, _: str = "") -> Any:
        c, hub = self.c, self.c.hub
        st = hub.status()
        pending = len(await c.store.pending_actions())
        yt = c.youtube.status()
        q = yt["quota"]
        frac = q["used"] / q["daily"] if q["daily"] else 0
        stream = (f"live for {format_duration(st['uptime'])}" + (f" · {esc(st['stream_title'])}" if st["stream_title"] else "")) if st["stream_live"] else "offline"
        rows = [
            ui.kv("📡", "Chat source", f"{esc(st['source'] or 'none')} ({esc(st['source_status'].get('state', '?'))})"),
            ui.kv("🔴" if st["stream_live"] else "⚫", "Stream", stream),
            ui.kv("🛡", "Moderation", f"{ui.mode_dot(st['mod_mode'])} {esc(st['mod_mode'])} · {pending} waiting for you"),
            ui.kv("▶️", "YouTube", "connected" if yt["connected"] else "not connected"),
            f"      <code>{ui.bar(frac)}</code> {round(frac * 100)}% of quota ({q['used']}/{q['daily']})",
            ui.kv("✈️", "Telegram", f"{ui.mode_dot(self.cfg.get('telegram_mode'))} {esc(self.cfg.get('telegram_mode'))}"),
        ]
        head = f"🤖 <b>{esc(self.cfg.get('app_name'))}</b>  ·  mode: {esc(st['mode'])}\n{ui.RULE}\n"
        return Rich(head + "\n".join(rows)), [[("🔄 Refresh", "m:status"), ("⏳ Waiting", "m:pending")], ui.back_row()]

    async def _stats(self, arg: str = "") -> Any:
        hours = float(arg) if arg.replace(".", "", 1).isdigit() and float(arg) > 0 else 1.0
        a = await summary(self.c.store, hours=hours, demo=self.cfg.get("bot_mode") == "demo")
        t = a["totals"]
        msgs = t["messages"]
        rate = round(100 * t["flagged_messages"] / msgs, 1) if msgs else 0
        rows = [ui.kv("💬", "Messages", f"{msgs} from {t['chatters']} chatters"),
                ui.kv("🚩", "Flagged", f"{t['flagged_messages']} ({rate}%)  <code>{ui.bar(rate / 100)}</code>"),
                ui.kv("🛡", "Actions", f"{t['actions']} · {t['pending']} pending")]
        if a["signals"]:
            rows += ["", "<b>Top signals</b>", *(f"  {esc(s['name'])}  <b>{s['count']}</b>" for s in a["signals"][:5])]
        if a["top_chatters"]:
            rows += ["", "<b>Top chatters</b>", *(f"  {esc(x['name'])}  <b>{x['messages']}</b>" for x in a["top_chatters"][:5])]
        label = f"{a['hours']:g}h"
        pick = lambda h, name: (("• " if abs(h - a["hours"]) < 0.01 else "") + name, f"m:stats:{h}")
        keys = [[pick(1, "1h"), pick(6, "6h"), pick(24, "24h"), pick(168, "7d")], ui.back_row()]
        return Rich(ui.card(f"Last {label} · {self.cfg.get('bot_mode')} data", rows, "", "📈")), keys

    async def _quota(self, _: str) -> Any:
        q = self.c.youtube.status()["quota"]
        frac = q["used"] / q["daily"] if q["daily"] else 0
        rows = [f"<code>{ui.bar(frac, 12)}</code> {round(frac * 100)}%", f"{q['used']} of {q['daily']} units used, <b>{q['remaining']}</b> left",
                f"Chat reads cost {self.cfg.get('yt_cost_chat_list')}, deletes {self.cfg.get('yt_cost_chat_delete')}, bans {self.cfg.get('yt_cost_ban')}."]
        return Rich(ui.card("YouTube quota today", rows, "", "▶️")), [ui.back_row()]

    async def _modes(self, _: str = "") -> Any:
        bot, mod = self.cfg.get("bot_mode"), self.cfg.get("mod_mode")
        rows = [ui.kv(ui.mode_dot(bot), "Chat source", esc(bot)), ui.kv(ui.mode_dot(mod), "Moderation", esc(mod)),
                "", "Demo: simulated chat, nothing is sent.", "Suggest: ask me first.  Auto: act, then tell me."]
        return Rich(ui.card("Modes", rows, "", "🎛")), ui.modes_keyboard(bot, mod)

    async def _mode(self, arg: str) -> Any:
        if arg not in ("demo", "live"):
            return f"Mode is {self.cfg.get('bot_mode')}. Use /mode demo or /mode live.", ui.modes_keyboard(self.cfg.get("bot_mode"), self.cfg.get("mod_mode"))
        await self.cfg.set("bot_mode", arg)
        await self.c.hub.apply_mode()
        return f"{ui.mode_dot(arg)} Mode is now {arg}."

    async def _mod(self, arg: str) -> Any:
        if arg not in ("off", "suggest", "auto"):
            return f"Moderation is {self.cfg.get('mod_mode')}. Use /mod off, /mod suggest or /mod auto.", ui.modes_keyboard(self.cfg.get("bot_mode"), self.cfg.get("mod_mode"))
        await self.cfg.set("mod_mode", arg)
        return f"{ui.mode_dot(arg)} Moderation is now {arg}."

    async def _tgmode(self, arg: str) -> str:
        if arg not in ("webhook", "polling"):
            return f"Telegram runs in {self.cfg.get('telegram_mode')} mode. Use /tgmode webhook or /tgmode polling."
        await self.cfg.set("telegram_mode", arg)
        await self.apply_mode()
        return f"Telegram now uses {arg}." + (f" ({self.last_error})" if self.last_error else "")

    # ------------------------------------------------------------------ moderation
    async def _pending_cards(self) -> str:
        items = await self.c.store.pending_actions()
        if not items:
            return "Nothing is waiting for you."
        owner = await self.owner_id()
        for a in items[:5]:
            await self.client.send(owner, ui.approval_card(a["id"], a), ui.approval_keyboard(a["id"]))
        more = f"\n{len(items) - 5} more. Use /approve all or /reject all." if len(items) > 5 else ""
        return f"{len(items)} waiting.{more}"

    async def _pending(self, _: str) -> Any:
        text = await self._pending_cards()
        if text.startswith("Nothing"):
            return Rich("✅ <b>Nothing is waiting for you.</b>"), [ui.back_row()]
        return text

    async def _resolve(self, arg: str, approve: bool) -> str:
        if arg == "all":
            r = await self.c.hub.resolve_all(approve)
            return f"{'Approved' if approve else 'Rejected'} {r['resolved']}" + (f", {r['failed']} failed" if r["failed"] else "")
        if not arg.isdigit():
            return f"Use /{'approve' if approve else 'reject'} <id> or all."
        res = await (self.c.hub.approve(int(arg)) if approve else self.c.hub.reject(int(arg)))
        return f"#{arg}: {res.get('status')}" if res["ok"] else res["error"]

    async def _approve(self, arg: str) -> str:
        return await self._resolve(arg, True)

    async def _reject(self, arg: str) -> str:
        return await self._resolve(arg, False)

    async def _permit(self, arg: str) -> str:
        who, _, secs = arg.partition(" ")
        if not who:
            return "Use /permit <user> [seconds]."
        seconds = max(5, min(int(secs) if secs.strip().isdigit() else self.cfg.get("mod_permit_seconds"), 600))
        self.c.permits.permit(who, seconds)
        return f"{who} can post links for {seconds}s."

    # ------------------------------------------------------------------ history and search (with date words)
    async def _history(self, arg: str = "") -> Any:
        since, until, label, rest = ui.parse_range(arg.split(), self._tz)
        known = {"executed", "approved", "rejected", "failed", "pending", "simulated", "expired"}
        status = next((w.lower() for w in rest if w.lower() in known), None)
        demo = self.cfg.get("bot_mode") == "demo"
        rows_db = await self.c.store.action_history(9, status, demo, since=since, until=until)
        title = "Recent actions" + (f" · {label}" if label else "") + (f" · {status}" if status else "")
        if not rows_db:
            return Rich(ui.card(title, ["Nothing found."], f"Date words: {esc(ui.RANGE_HELP)}", "🕘")), [ui.back_row()]
        rows = []
        for a in rows_db[:8]:
            what = a["action"] + (f" {format_duration(a['duration'])}" if a["duration"] else "")
            rows.append(f"{ui.outcome_icon(a['status'])} <code>{ui.when(a['ts'], self._tz)}</code>  {esc(what)}  <b>{esc(a['author_name'])}</b>")
        more = "Showing the newest 8. Narrow it with a date word." if len(rows_db) > 8 else f"Date words: {esc(ui.RANGE_HELP)}"
        return Rich(ui.card(title, rows, more, "🕘")), [ui.back_row()]

    async def _find(self, arg: str = "") -> Any:
        since, until, label, rest = ui.parse_range(arg.split(), self._tz)
        needle = " ".join(rest).strip()
        if not needle and since is None:
            return Rich(ui.card("Search saved chat", ["/find &lt;text&gt; [date]", "", "Examples:", "<code>/find giveaway yesterday</code>", "<code>/find robux 2026-11-01..2026-11-05</code>",
                                                      "<code>/find today</code>  (everything today)", "", f"Date words: {esc(ui.RANGE_HELP)}"], "", "🔎"))
        rows_db = await self.c.store.search_chat(needle or None, since, until, None, self.cfg.get("bot_mode") == "demo", 11)
        title = "Chat" + (f" matching “{esc(needle)}”" if needle else "") + (f" · {esc(label)}" if label else "")
        if not rows_db:
            return Rich(f"🔎 <b>{title}</b>\n{ui.RULE}\nNo saved chat matches. Chat is kept for {self.cfg.get('chat_retention_days')} days.")
        shown = rows_db[-10:]
        rows = [f"<code>{ui.when(m['ts'], self._tz)}</code> {ui.level_icon(m['level'])}<b>{esc(m['author_name'])}</b>: {esc(truncate(m['body'], 90))}" + (" 🚩" if m["verdict"] not in ("allow", None) else "")
                for m in shown]
        foot = "Showing the newest 10. Add a date word to narrow it." if len(rows_db) > 10 else f"Chat is kept for {self.cfg.get('chat_retention_days')} days."
        return Rich(f"🔎 <b>{title}</b>\n{ui.RULE}\n" + "\n".join(rows) + f"\n\n<i>{esc(foot)}</i>")

    # ------------------------------------------------------------------ chat and demo
    async def _say(self, arg: str) -> str:
        if not arg:
            return "Use /say <text>."
        return "Sent." if await self.c.hub.send_chat(arg) else "Could not send. Is the chat source running?"

    async def _demo(self, arg: str) -> Any:
        demo = self.c.demo
        if not arg:
            return Rich(ui.card("Demo scenarios", [f"/demo <code>{esc(s['name'])}</code>  {esc(s['label'])}" for s in demo.scenarios()], "", "🧪"))
        if self.cfg.get("bot_mode") != "demo":
            return "Switch to demo mode first with /mode demo."
        return f"Started {arg}." if demo.start_scenario(arg) else "That scenario is unknown or already running."

    # ------------------------------------------------------------------ notes and reminders
    async def _note(self, arg: str) -> str:
        if not arg:
            return "Use /note <text>."
        return f"Saved note #{await self.c.store.add_note(arg)}."

    async def _notes(self, _: str = "") -> Any:
        notes = await self.c.store.list_notes()
        if not notes:
            return Rich("🗒 <b>No notes yet.</b>\nSave one with /note &lt;text&gt;."), [ui.back_row()]
        rows = [f"{'📌' if n['pinned'] else '▫️'} <code>#{n['id']}</code> {esc(truncate(n['body'], 200))}" for n in notes[:15]]
        return Rich(ui.card("Notes", rows, "Delete with /delnote &lt;id&gt;", "🗒")), [ui.back_row()]

    async def _delnote(self, arg: str) -> str:
        return "Deleted." if arg.isdigit() and await self.c.store.delete_note(int(arg)) else "No such note."

    async def _remind(self, arg: str) -> str:
        tz = self.cfg.get("owner_timezone")
        try:
            r = parse_reminder(arg, tz)
        except ReminderParseError as exc:
            return str(exc)
        id_ = await self.c.store.add_reminder(r.text, to_epoch(r.due_utc), r.repeat, r.interval_seconds)
        local = r.due_utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz))
        return f"⏰ Reminder #{id_} set for {local:%a %d %b %H:%M} ({tz})" + (f", repeating {r.repeat}" if r.repeat != "none" else "") + "."

    async def _reminders(self, _: str = "") -> Any:
        tz = ZoneInfo(self.cfg.get("owner_timezone"))
        rows_db = await self.c.store.list_reminders("pending")
        if not rows_db:
            return Rich("⏰ <b>No reminders.</b>\nSet one with /remind &lt;when&gt; &lt;text&gt;."), [ui.back_row()]
        rows = [f"<code>#{r['id']}</code> <code>{from_epoch(r['due']).replace(tzinfo=timezone.utc).astimezone(tz):%d %b %H:%M}</code>  {esc(truncate(r['body'], 100))}"
                + (f"  🔁 {esc(r['repeat_kind'])}" if r["repeat_kind"] != "none" else "") for r in rows_db[:15]]
        return Rich(ui.card("Reminders", rows, "Cancel with /delremind &lt;id&gt;", "⏰")), [ui.back_row()]

    # ---- weather: every answer comes from the central WeatherService (never a direct provider call from here)
    async def _wx(self, arg: str, render: Any) -> Any:
        from ..weather import WeatherServiceError
        from ..weather import format as wf
        try:
            loc = await self.c.weather.resolve(arg) if arg.strip() else await self.c.weather.get_location()
            if loc is None:
                return "No place found." if arg.strip() else "No default location yet. Add one on the dashboard (Weather), or send /weather <place>."
            return Rich(render(wf, await self.c.weather.overview_for(loc)))
        except WeatherServiceError as exc:
            return f"Weather is unavailable right now: {exc.message}"

    async def _weather(self, arg: str) -> Any:
        return await self._wx(arg, lambda wf, o: wf.now_text(o))

    async def _forecast(self, arg: str) -> Any:
        return await self._wx(arg, lambda wf, o: wf.forecast_text(o))

    async def _hourly(self, arg: str) -> Any:
        return await self._wx(arg, lambda wf, o: wf.hourly_text(o))

    async def _locations(self, arg: str) -> Any:
        from ..weather import WeatherServiceError
        from ..weather import format as wf
        locs = await self.c.weather.locations()
        if arg.strip().isdigit() and 1 <= int(arg) <= len(locs):
            try:
                await self.c.weather.set_default(locs[int(arg) - 1]["id"])
            except WeatherServiceError as exc:
                return exc.message
            locs = await self.c.weather.locations()
        return Rich(wf.locations_text(locs))

    async def _lockdown(self, arg: str) -> str:
        await self.c.access.set_lockdown(True, None, "telegram")
        return "🚨 Lockdown is ON. Every dashboard session was signed out. Sign in again on the dashboard (password plus a second method) and lift it on the Security page."

    async def _bans(self, arg: str) -> str:
        res = await self.c.hub.bans.search("active", arg, 0, 15)
        if not res["items"]:
            return "No active bans or timeouts in the ledger."
        lines = [f"#{b['id']}  {esc(b['author_name'] or b['author_id'])}  {'ban' if b['kind'] == 'ban' else 'timeout'}"
                 f"{'' if b['can_lift'] else ' (cannot be lifted from here)'}" for b in res["items"]]
        return "Active bans and timeouts:\n" + "\n".join(lines) + "\n\nLift one with /unban <id>."

    async def _unban(self, arg: str) -> str:
        arg = arg.strip()
        if not arg:
            return "Usage: /unban <id or name>. See /bans."
        rows = [await self.c.hub.bans.get(int(arg))] if arg.isdigit() else await self.c.hub.bans.find_active(arg)
        rows = [r for r in rows if r and r["status"] == "active"]
        if not rows:
            return "No active ban matches that. Bans made before 1.2.0 or in YouTube Studio must be lifted in YouTube Studio."
        done, problems = 0, []
        for r in rows[:5]:
            res = await self.c.hub.unban(r["id"], by="telegram")
            done += bool(res["ok"])
            if not res["ok"]:
                problems.append(res["error"])
        return (f"Lifted {done}." if done else "Nothing was lifted.") + ("\n" + "\n".join(problems[:2]) if problems else "")

    async def _delremind(self, arg: str) -> str:
        return "Cancelled." if arg.isdigit() and await self.c.store.cancel_reminder(int(arg)) else "No such pending reminder."
