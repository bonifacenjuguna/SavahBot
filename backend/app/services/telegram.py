"""Telegram: owner-only control of SavahBot, via webhook (recommended on Railway) or long polling.

Security: only one Telegram account is ever obeyed. Everyone else is silently ignored (the bot does not
even reveal that it exists). The owner id comes from TELEGRAM_OWNER_ID, or is bound once with
/claim <OWNER_PASSWORD>. Webhook requests must carry the secret token Telegram was given.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
import time
from datetime import timezone
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from .. import __version__
from ..analytics import summary
from ..http import NetworkError, request_json
from ..timeparse import ReminderParseError, parse_reminder
from ..utils import format_duration, from_epoch, to_epoch, truncate
from . import telegram_ui as ui

logger = logging.getLogger("savahbot.telegram")
WEBHOOK_PATH = "/api/telegram/webhook"
Buttons = "list[list[tuple[str, str]]] | None"

HELP = ui.HELP_HTML  # kept for anything that imports it; the text itself lives in telegram_ui


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

    @staticmethod
    def _markup(buttons: Any) -> dict[str, Any]:
        return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]}

    async def send(self, chat_id: int, text: str, buttons: Any = None, html: bool = False) -> Any:
        params: dict[str, Any] = {"chat_id": chat_id, "text": truncate(text, 4000), "disable_web_page_preview": True}
        if html:
            params["parse_mode"] = "HTML"
        if buttons:
            params["reply_markup"] = self._markup(buttons)
        try:
            return await self.call("sendMessage", params)
        except TelegramError as exc:
            if html and "parse entities" in str(exc):  # never lose a message because of a formatting slip
                params.pop("parse_mode")
                params["text"] = truncate(ui.strip_tags(text), 4000)
                return await self.call("sendMessage", params)
            raise

    async def edit(self, chat_id: int, message_id: int, text: str, buttons: Any = None) -> Any:
        params: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": truncate(text, 4000),
                                  "parse_mode": "HTML", "disable_web_page_preview": True}
        if buttons:
            params["reply_markup"] = self._markup(buttons)
        return await self.call("editMessageText", params)


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
                {"command": "status", "description": "Overview"}, {"command": "pending", "description": "Requests waiting for you"},
                {"command": "mode", "description": "demo or live"}, {"command": "mod", "description": "off, suggest or auto"},
                {"command": "stats", "description": "Chat numbers"}, {"command": "menu", "description": "Open the menu"},
                {"command": "notes", "description": "Your notes"}, {"command": "reminders", "description": "Upcoming reminders"},
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
                rows = ([*buttons, ui.menu_button()] if buttons else None)
                await self.client.send(owner, ui.format_notice(text), rows, html=True)
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
            "start": self._start, "menu": self._start, "help": self._help, "status": self._status, "stats": self._stats,
            "quota": self._quota, "mode": self._mode, "mod": self._mod, "modes": self._modes, "tgmode": self._tgmode,
            "pending": self._pending, "approve": self._approve, "reject": self._reject, "permit": self._permit,
            "say": self._say, "demo": self._demo, "note": self._note, "notes": self._notes, "delnote": self._delnote,
            "remind": self._remind, "reminders": self._reminders, "delremind": self._delremind,
        }.get(cmd)
        if handler is None:
            await self.client.send(owner, "❔ Unknown command. Send /help for the list.", [ui.menu_button()], html=True)
            return
        result = await handler(arg)
        if isinstance(result, tuple):
            await self.client.send(owner, result[0], result[1], html=True)
        elif result:
            await self.client.send(owner, result, html=True)

    async def _claim(self, user_id: int, password: str) -> None:
        key = f"tg:{user_id}"
        auth = self.c.auth
        if auth.throttle.retry_after(key) or not auth.check_password(password):
            auth.throttle.fail(key)
            return
        auth.throttle.success(key)
        await self.c.db.kv_set("telegram_owner_id", str(user_id))
        self._owner = user_id
        await self.client.send(user_id, "✅ <b>You are now the owner of this bot.</b>\nOnly this account can use it. Tap a button or send /help.",
                               ui.home_keyboard(), html=True)

    async def _callback(self, q: dict[str, Any]) -> None:
        owner = await self.owner_id()
        if not owner or (q.get("from") or {}).get("id") != owner:
            return
        action, _, raw = (q.get("data") or "").partition(":")
        if action == "nav":
            await self._nav(q, raw)
            return
        if action == "set":
            await self._set(q, raw)
            return
        if action not in ("approve", "reject") or not raw.isdigit():
            await self.client.call("answerCallbackQuery", {"callback_query_id": q["id"]})
            return
        res = await (self.c.hub.approve(int(raw)) if action == "approve" else self.c.hub.reject(int(raw)))
        note = ("Done: " + res.get("status", "")) if res.get("ok") else res.get("error", "Failed")
        await self.client.call("answerCallbackQuery", {"callback_query_id": q["id"], "text": note[:150]})
        msg = q.get("message") or {}
        if msg.get("chat") and msg.get("message_id"):
            try:
                await self.client.edit(msg["chat"]["id"], msg["message_id"],
                                       esc_original(msg) + f"\n\n{'✅' if res.get('ok') else '⚠️'} <b>{ui.esc(action.capitalize())}: {ui.esc(note)}</b>",
                                       [ui.menu_button()])
            except TelegramError:
                pass

    async def _nav(self, q: dict[str, Any], view: str) -> None:
        """Menu navigation: the message the owner tapped is edited in place into the requested screen."""
        await self.client.call("answerCallbackQuery", {"callback_query_id": q["id"]})
        msg = q.get("message") or {}
        if view == "pending":  # the waiting requests are separate messages with their own buttons
            result = await self._pending("")
            await self.client.send(await self.owner_id(), result[0], result[1], html=True)
            return
        handler = {"home": self._start, "status": self._status, "stats": self._stats, "quota": self._quota, "modes": self._modes,
                   "notes": self._notes, "reminders": self._reminders, "help": self._help}.get(view)
        if handler is None or not (msg.get("chat") and msg.get("message_id")):
            return
        result = await handler("")
        text, buttons = result if isinstance(result, tuple) else (result, ui.back_keyboard())
        try:
            await self.client.edit(msg["chat"]["id"], msg["message_id"], text, buttons)
        except TelegramError as exc:
            if "not modified" not in str(exc):  # tapping Refresh on an unchanged screen is normal
                raise

    async def _set(self, q: dict[str, Any], raw: str) -> None:
        """Mode buttons. They do exactly what /mode and /mod do, then redraw the Modes screen."""
        kind, _, value = raw.partition(":")
        text, buttons = await (self._mode(value) if kind == "mode" else self._mod(value) if kind == "mod" else self._modes(""))
        await self.client.call("answerCallbackQuery", {"callback_query_id": q["id"]})
        msg = q.get("message") or {}
        if msg.get("chat") and msg.get("message_id"):
            try:
                await self.client.edit(msg["chat"]["id"], msg["message_id"], text, buttons)
            except TelegramError as exc:
                if "not modified" not in str(exc):
                    raise

    # ------------------------------------------------------------------ command handlers
    # Every handler returns HTML (all user content goes through ui.esc) or an (HTML, keyboard) pair.
    async def _start(self, _: str) -> Any:
        return ui.welcome(self.cfg.get("app_name"), __version__), ui.home_keyboard()

    async def _help(self, _: str) -> Any:
        return ui.HELP_HTML, ui.back_keyboard()

    async def _status(self, _: str) -> Any:
        c, hub = self.c, self.c.hub
        st = hub.status()
        pending = len(await c.store.pending_actions())
        yt = c.youtube.status()
        stream = (f"🔴 live for {format_duration(st['uptime'])}" + (f" · {ui.esc(st['stream_title'])}" if st["stream_title"] else "")
                  if st["stream_live"] else "⚫ offline")
        quota = yt["quota"]
        lines = [
            f"🛡 <b>{ui.esc(self.cfg.get('app_name'))}</b>  ·  mode: {ui.esc(st['mode'])}",
            "",
            ui.kv("Chat source", f"{ui.esc(st['source'] or 'none')} ({ui.esc(st['source_status'].get('state', '?'))})"),
            ui.kv("Stream", stream),
            ui.kv("Moderation", f"{ui.esc(st['mod_mode'])}  ·  <b>{pending}</b> waiting for you"),
            ui.kv("Telegram", ui.esc(self.cfg.get("telegram_mode"))),
            ui.kv("YouTube", f"{ui.dot(yt['connected'])} {'connected' if yt['connected'] else 'not connected'}  ·  quota {quota['used']}/{quota['daily']}"),
        ]
        return "\n".join(lines), ui.back_keyboard("nav:status")

    async def _stats(self, arg: str) -> Any:
        hours = float(arg) if arg.replace(".", "", 1).isdigit() else 1.0
        a = await summary(self.c.store, hours=hours, demo=self.cfg.get("bot_mode") == "demo")
        t = a["totals"]
        out = [ui.title("📈", f"Last {a['hours']:g}h", f"{self.cfg.get('bot_mode')} data"), "",
               ui.kv("Messages", f"<b>{t['messages']}</b> from {t['chatters']} chatters"),
               ui.kv("Flagged", f"<b>{t['flagged_messages']}</b>  ·  actions {t['actions']}  ·  pending {t['pending']}")]
        if a["signals"]:
            out.append(ui.kv("Top signals", ui.esc(", ".join(f"{s['name']} {s['count']}" for s in a["signals"][:5]))))
        if a["top_chatters"]:
            out.append(ui.kv("Top chatters", ui.esc(", ".join(f"{x['name']} {x['messages']}" for x in a["top_chatters"][:5]))))
        return "\n".join(out), ui.back_keyboard("nav:stats")

    async def _quota(self, _: str) -> Any:
        q = self.c.youtube.status()["quota"]
        used = q["used"] / q["daily"] if q["daily"] else 0
        return (ui.title("📺", "YouTube quota today") + f"\n<code>{ui.bar(used)}</code>  {q['used']} of {q['daily']} units ({q['remaining']} left)\n"
                f"<i>Chat reads cost {self.cfg.get('yt_cost_chat_list')}, deletes {self.cfg.get('yt_cost_chat_delete')}, "
                f"bans {self.cfg.get('yt_cost_ban')}.</i>"), ui.back_keyboard("nav:quota")

    async def _modes(self, _: str, note: str = "") -> Any:
        bot_mode, mod_mode = self.cfg.get("bot_mode"), self.cfg.get("mod_mode")
        lines = [ui.title("🎛", "Modes")]
        if note:
            lines += ["", ui.esc(note)]
        lines += ["", ui.kv("Chat source", f"<b>{ui.esc(bot_mode)}</b>"), ui.kv("Moderation", f"<b>{ui.esc(mod_mode)}</b>"),
                  ui.kv("Telegram", ui.esc(self.cfg.get("telegram_mode"))), "",
                  "<i>Demo uses simulated chat. Suggest asks you first, Auto acts on its own.</i>"]
        return "\n".join(lines), ui.modes_keyboard(bot_mode, mod_mode)

    async def _mode(self, arg: str) -> Any:
        if arg not in ("demo", "live"):
            return await self._modes("", f"Mode is {self.cfg.get('bot_mode')}. Use /mode demo or /mode live.")
        await self.cfg.set("bot_mode", arg)
        await self.c.hub.apply_mode()
        return await self._modes("", f"Mode is now {arg}.")

    async def _mod(self, arg: str) -> Any:
        if arg not in ("off", "suggest", "auto"):
            return await self._modes("", f"Moderation is {self.cfg.get('mod_mode')}. Use /mod off, /mod suggest or /mod auto.")
        await self.cfg.set("mod_mode", arg)
        return await self._modes("", f"Moderation is now {arg}.")

    async def _tgmode(self, arg: str) -> Any:
        if arg not in ("webhook", "polling"):
            return f"Telegram runs in <b>{ui.esc(self.cfg.get('telegram_mode'))}</b> mode. Use /tgmode webhook or /tgmode polling."
        await self.cfg.set("telegram_mode", arg)
        await self.apply_mode()
        return f"📡 Telegram now uses <b>{ui.esc(arg)}</b>." + (f"\n⚠️ {ui.esc(self.last_error)}" if self.last_error else "")

    async def _pending(self, _: str) -> Any:
        items = await self.c.store.pending_actions()
        if not items:
            return "✨ <b>Nothing is waiting for you.</b>", ui.back_keyboard("nav:pending")
        owner = await self.owner_id()
        for a in items[:5]:
            await self.client.send(owner, ui.approval_card(a), [[("Approve", f"approve:{a['id']}"), ("Reject", f"reject:{a['id']}")]], html=True)
        more = f"\n{len(items) - 5} more. Use /approve all or /reject all." if len(items) > 5 else ""
        return f"🛡 <b>{len(items)} waiting.</b>{more}", [ui.menu_button()]

    async def _resolve(self, arg: str, approve: bool) -> str:
        if arg == "all":
            r = await self.c.hub.resolve_all(approve)
            return f"{'✅ Approved' if approve else '🚫 Rejected'} {r['resolved']}" + (f", {r['failed']} failed" if r["failed"] else "")
        if not arg.isdigit():
            return f"Use /{'approve' if approve else 'reject'} &lt;id&gt; or all."
        res = await (self.c.hub.approve(int(arg)) if approve else self.c.hub.reject(int(arg)))
        return f"<code>#{arg}</code>  {ui.esc(res.get('status'))}" if res["ok"] else f"⚠️ {ui.esc(res['error'])}"

    async def _approve(self, arg: str) -> str:
        return await self._resolve(arg, True)

    async def _reject(self, arg: str) -> str:
        return await self._resolve(arg, False)

    async def _permit(self, arg: str) -> str:
        who, _, secs = arg.partition(" ")
        if not who:
            return "Use /permit &lt;user&gt; [seconds]."
        seconds = max(5, min(int(secs) if secs.strip().isdigit() else self.cfg.get("mod_permit_seconds"), 600))
        self.c.permits.permit(who, seconds)
        return f"🔗 <b>{ui.esc(who)}</b> can post links for {seconds}s."

    async def _say(self, arg: str) -> str:
        if not arg:
            return "Use /say &lt;text&gt;."
        return "✅ Sent." if await self.c.hub.send_chat(arg) else "⚠️ Could not send. Is the chat source running?"

    async def _demo(self, arg: str) -> str:
        demo = self.c.demo
        if not arg:
            return ui.title("🧪", "Demo scenarios") + "\n" + "\n".join(f"<code>/demo {ui.esc(s['name'])}</code>  {ui.esc(s['label'])}" for s in demo.scenarios())
        if self.cfg.get("bot_mode") != "demo":
            return "Switch to demo mode first with /mode demo."
        return f"▶️ Started <b>{ui.esc(arg)}</b>." if demo.start_scenario(arg) else "That scenario is unknown or already running."

    async def _note(self, arg: str) -> str:
        if not arg:
            return "Use /note &lt;text&gt;."
        return f"📝 <b>Saved note #{await self.c.store.add_note(arg)}.</b>"

    async def _notes(self, _: str) -> Any:
        notes = await self.c.store.list_notes()
        if not notes:
            return "📝 <b>No notes yet.</b>\n<i>Save one with /note &lt;text&gt;.</i>", ui.back_keyboard("nav:notes")
        rows = [f"<code>#{n['id']}</code> {'📌 ' if n['pinned'] else ''}{ui.esc(truncate(n['body'], 200))}" for n in notes[:15]]
        return "\n".join([ui.title("📝", "Notes", f"{len(notes)} saved"), "", *rows]), ui.back_keyboard("nav:notes")

    async def _delnote(self, arg: str) -> str:
        return "🗑 Deleted." if arg.isdigit() and await self.c.store.delete_note(int(arg)) else "No such note."

    async def _remind(self, arg: str) -> str:
        tz = self.cfg.get("owner_timezone")
        try:
            r = parse_reminder(arg, tz)
        except ReminderParseError as exc:
            return f"⚠️ {ui.esc(exc)}"
        id_ = await self.c.store.add_reminder(r.text, to_epoch(r.due_utc), r.repeat, r.interval_seconds)
        local = r.due_utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz))
        return (f"⏰ <b>Reminder #{id_} set</b> for {local:%a %d %b %H:%M} ({ui.esc(tz)})"
                + (f"\n<i>repeating {ui.esc(r.repeat)}</i>" if r.repeat != "none" else ""))

    async def _reminders(self, _: str) -> Any:
        tz = ZoneInfo(self.cfg.get("owner_timezone"))
        rows = await self.c.store.list_reminders("pending")
        if not rows:
            return "⏰ <b>No reminders.</b>\n<i>Set one with /remind 30m stretch.</i>", ui.back_keyboard("nav:reminders")
        lines = [f"<code>#{r['id']}</code> {from_epoch(r['due']).replace(tzinfo=timezone.utc).astimezone(tz):%d %b %H:%M}  {ui.esc(truncate(r['body'], 100))}"
                 + (f"  <i>({ui.esc(r['repeat_kind'])})</i>" if r["repeat_kind"] != "none" else "") for r in rows[:15]]
        return "\n".join([ui.title("⏰", "Reminders", f"{len(rows)} pending"), "", *lines]), ui.back_keyboard("nav:reminders")

    async def _delremind(self, arg: str) -> str:
        return "✅ Cancelled." if arg.isdigit() and await self.c.store.cancel_reminder(int(arg)) else "No such pending reminder."


def esc_original(msg: dict[str, Any]) -> str:
    """The text of the message a button was pressed on, made safe to place inside an HTML edit."""
    return ui.esc(truncate(msg.get("text") or "", 3500))
