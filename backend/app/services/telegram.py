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

from ..analytics import summary
from ..http import NetworkError, request_json
from ..timeparse import ReminderParseError, parse_reminder
from ..utils import format_duration, from_epoch, to_epoch, truncate

logger = logging.getLogger("savahbot.telegram")
WEBHOOK_PATH = "/api/telegram/webhook"
Buttons = "list[list[tuple[str, str]]] | None"

HELP = """SavahBot commands

Status
/status  overview
/stats [hours]  chat and moderation numbers
/quota  YouTube quota

Modes
/mode demo|live  chat source
/mod off|suggest|auto  moderation mode
/tgmode webhook|polling  how Telegram reaches the bot

Moderation
/pending  requests waiting for you
/approve <id|all>   /reject <id|all>
/permit <user> [seconds]  allow links briefly

Chat
/say <text>  post in the stream chat
/demo [scenario]  list or run demo scenarios

Notes and reminders
/note <text>   /notes   /delnote <id>
/remind <when> <text>   /reminders   /delremind <id>
  when: 30m, 2h, 18:30, tomorrow 09:00, 2026-11-05 14:00, daily 08:00, every 2h"""


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
        return await self.call("sendMessage", params)


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
                {"command": "stats", "description": "Chat numbers"}, {"command": "help", "description": "All commands"}]})
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
            "start": self._help, "help": self._help, "status": self._status, "stats": self._stats, "quota": self._quota,
            "mode": self._mode, "mod": self._mod, "tgmode": self._tgmode, "pending": self._pending,
            "approve": self._approve, "reject": self._reject, "permit": self._permit, "say": self._say, "demo": self._demo,
            "note": self._note, "notes": self._notes, "delnote": self._delnote,
            "remind": self._remind, "reminders": self._reminders, "delremind": self._delremind,
        }.get(cmd)
        if handler is None:
            await self.client.send(owner, "Unknown command. Send /help for the list.")
            return
        result = await handler(arg)
        if isinstance(result, tuple):
            await self.client.send(owner, result[0], result[1])
        elif result:
            await self.client.send(owner, result)

    async def _claim(self, user_id: int, password: str) -> None:
        key = f"tg:{user_id}"
        auth = self.c.auth
        if auth.throttle.retry_after(key) or not auth.check_password(password):
            auth.throttle.fail(key)
            return
        auth.throttle.success(key)
        await self.c.db.kv_set("telegram_owner_id", str(user_id))
        self._owner = user_id
        await self.client.send(user_id, "You are now the owner of this bot. Send /help to see what it can do.")

    async def _callback(self, q: dict[str, Any]) -> None:
        owner = await self.owner_id()
        if not owner or (q.get("from") or {}).get("id") != owner:
            return
        action, _, raw = (q.get("data") or "").partition(":")
        if action not in ("approve", "reject") or not raw.isdigit():
            await self.client.call("answerCallbackQuery", {"callback_query_id": q["id"]})
            return
        res = await (self.c.hub.approve(int(raw)) if action == "approve" else self.c.hub.reject(int(raw)))
        note = ("Done: " + res.get("status", "")) if res.get("ok") else res.get("error", "Failed")
        await self.client.call("answerCallbackQuery", {"callback_query_id": q["id"], "text": note[:150]})
        msg = q.get("message") or {}
        if msg.get("chat") and msg.get("message_id"):
            try:
                await self.client.call("editMessageText", {
                    "chat_id": msg["chat"]["id"], "message_id": msg["message_id"],
                    "text": truncate((msg.get("text") or "") + f"\n\n{action.capitalize()}: {note}", 4000)})
            except TelegramError:
                pass

    # ------------------------------------------------------------------ command handlers
    async def _help(self, _: str) -> str:
        return HELP

    async def _status(self, _: str) -> str:
        c, hub = self.c, self.c.hub
        st = hub.status()
        pending = len(await c.store.pending_actions())
        yt = c.youtube.status()
        lines = [
            f"{self.cfg.get('app_name')}  mode: {st['mode']}",
            f"Chat source: {st['source'] or 'none'} ({st['source_status'].get('state', '?')})",
            "Stream: " + (f"live for {format_duration(st['uptime'])}" + (f" - {st['stream_title']}" if st["stream_title"] else "")
                          if st["stream_live"] else "offline"),
            f"Moderation: {st['mod_mode']}, {pending} waiting for you",
            f"Telegram: {self.cfg.get('telegram_mode')}",
            f"YouTube: {'connected' if yt['connected'] else 'not connected'}, quota {yt['quota']['used']}/{yt['quota']['daily']}",
        ]
        return "\n".join(lines)

    async def _stats(self, arg: str) -> str:
        hours = float(arg) if arg.replace(".", "", 1).isdigit() else 1.0
        a = await summary(self.c.store, hours=hours, demo=self.cfg.get("bot_mode") == "demo")
        t = a["totals"]
        out = [f"Last {a['hours']:g}h ({self.cfg.get('bot_mode')} data)",
               f"Messages {t['messages']} from {t['chatters']} chatters", f"Flagged {t['flagged_messages']}, actions {t['actions']}, pending {t['pending']}"]
        if a["signals"]:
            out.append("Top signals: " + ", ".join(f"{s['name']} {s['count']}" for s in a["signals"][:5]))
        if a["top_chatters"]:
            out.append("Top chatters: " + ", ".join(f"{x['name']} {x['messages']}" for x in a["top_chatters"][:5]))
        return "\n".join(out)

    async def _quota(self, _: str) -> str:
        q = self.c.youtube.status()["quota"]
        return (f"YouTube quota today: {q['used']} of {q['daily']} units used ({q['remaining']} left).\n"
                f"Chat reads cost {self.cfg.get('yt_cost_chat_list')}, deletes {self.cfg.get('yt_cost_chat_delete')}, bans {self.cfg.get('yt_cost_ban')}.")

    async def _mode(self, arg: str) -> str:
        if arg not in ("demo", "live"):
            return f"Mode is {self.cfg.get('bot_mode')}. Use /mode demo or /mode live."
        await self.cfg.set("bot_mode", arg)
        await self.c.hub.apply_mode()
        return f"Mode is now {arg}."

    async def _mod(self, arg: str) -> str:
        if arg not in ("off", "suggest", "auto"):
            return f"Moderation is {self.cfg.get('mod_mode')}. Use /mod off, /mod suggest or /mod auto."
        await self.cfg.set("mod_mode", arg)
        return f"Moderation is now {arg}."

    async def _tgmode(self, arg: str) -> str:
        if arg not in ("webhook", "polling"):
            return f"Telegram runs in {self.cfg.get('telegram_mode')} mode. Use /tgmode webhook or /tgmode polling."
        await self.cfg.set("telegram_mode", arg)
        await self.apply_mode()
        return f"Telegram now uses {arg}." + (f" ({self.last_error})" if self.last_error else "")

    async def _pending(self, _: str) -> Any:
        items = await self.c.store.pending_actions()
        if not items:
            return "Nothing is waiting for you."
        owner = await self.owner_id()
        for a in items[:5]:
            what = a["action"] + (f" {a['duration']}s" if a["duration"] else "")
            await self.client.send(owner, f"#{a['id']} {what} for {a['author_name']} (score {a['score']})\n“{truncate(a['body'], 120)}”\n"
                                          f"Why: {'; '.join(a['reasons'][:4])}", [[("Approve", f"approve:{a['id']}"), ("Reject", f"reject:{a['id']}")]])
        more = f"\n{len(items) - 5} more. Use /approve all or /reject all." if len(items) > 5 else ""
        return f"{len(items)} waiting.{more}"

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

    async def _say(self, arg: str) -> str:
        if not arg:
            return "Use /say <text>."
        return "Sent." if await self.c.hub.send_chat(arg) else "Could not send. Is the chat source running?"

    async def _demo(self, arg: str) -> str:
        demo = self.c.demo
        if not arg:
            return "Demo scenarios:\n" + "\n".join(f"/demo {s['name']}  {s['label']}" for s in demo.scenarios())
        if self.cfg.get("bot_mode") != "demo":
            return "Switch to demo mode first with /mode demo."
        return f"Started {arg}." if demo.start_scenario(arg) else "That scenario is unknown or already running."

    async def _note(self, arg: str) -> str:
        if not arg:
            return "Use /note <text>."
        return f"Saved note #{await self.c.store.add_note(arg)}."

    async def _notes(self, _: str) -> str:
        notes = await self.c.store.list_notes()
        return "\n".join(f"#{n['id']} {'(pinned) ' if n['pinned'] else ''}{truncate(n['body'], 200)}" for n in notes[:15]) or "No notes yet."

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
        return f"Reminder #{id_} set for {local:%a %d %b %H:%M} ({tz})" + (f", repeating {r.repeat}" if r.repeat != "none" else "") + "."

    async def _reminders(self, _: str) -> str:
        tz = ZoneInfo(self.cfg.get("owner_timezone"))
        rows = await self.c.store.list_reminders("pending")
        return "\n".join(f"#{r['id']} {from_epoch(r['due']).replace(tzinfo=timezone.utc).astimezone(tz):%d %b %H:%M} {truncate(r['body'], 100)}"
                         + (f" ({r['repeat_kind']})" if r["repeat_kind"] != "none" else "") for r in rows[:15]) or "No reminders."

    async def _delremind(self, arg: str) -> str:
        return "Cancelled." if arg.isdigit() and await self.c.store.cancel_reminder(int(arg)) else "No such pending reminder."
