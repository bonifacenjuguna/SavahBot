"""The hub: every chat message, from any source, flows through here.

    source (demo / YouTube) -> ingest() -> moderation -> store + live feed -> commands -> replies

It also owns the approval workflow for moderation actions, the active chat source (demo or live),
and the stream state (live / offline / uptime).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, Awaitable, Callable, Protocol

from .commands import CommandEngine
from .events import EventBus
from .models import ChatMessage
from .services.telegram_ui import approval_card, approval_keyboard, flag_card, stream_card
from .moderation import ACTION_RANK, ModerationEngine, ModInput, Verdict
from .store import Store
from .utils import split_csv, truncate

logger = logging.getLogger("savahbot.hub")

Notifier = Callable[[str, "list[list[tuple[str, str]]] | None"], Awaitable[None]]


class ChatSource(Protocol):
    name: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, text: str) -> bool: ...
    async def delete(self, msg_id: str) -> tuple[bool, str]: ...
    async def timeout(self, author_id: str, seconds: int) -> tuple[bool, str]: ...
    async def ban(self, author_id: str) -> tuple[bool, str]: ...
    def status(self) -> dict[str, Any]: ...


class Hub:
    def __init__(self, cfg: Any, store: Store, bus: EventBus, engine: ModerationEngine, commands: CommandEngine) -> None:
        self.cfg = cfg
        self.store = store
        self.bus = bus
        self.engine = engine
        self.commands = commands
        self.sources: dict[str, ChatSource] = {}
        self.source: ChatSource | None = None
        self.notify: Notifier | None = None
        self.buffer: deque[dict] = deque(maxlen=max(50, cfg.get("chat_buffer_size")))
        self.lines = 0
        self.stream_live = False
        self.stream_title = ""
        self._stream_started: float | None = None
        self._sent: deque[tuple[str, float]] = deque(maxlen=50)
        self._recent_punish: dict[str, float] = {}
        self._notify_times: deque[float] = deque()
        self._suppressed = 0
        self._mode_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()

    # ------------------------------------------------------------------ sources and mode
    def register(self, source: ChatSource) -> None:
        self.sources[source.name] = source

    @property
    def mode(self) -> str:
        return self.cfg.get("bot_mode")

    def source_name_for_mode(self) -> str:
        return "demo" if self.mode == "demo" else "youtube"

    async def apply_mode(self) -> dict[str, Any]:
        """Start the chat source that matches bot_mode (demo | live), stopping the previous one."""
        async with self._mode_lock:
            wanted = self.sources.get(self.source_name_for_mode())
            if self.source is not None and self.source is not wanted:
                try:
                    await self.source.stop()
                except Exception:
                    logger.exception("Stopping %s failed", self.source.name)
                self.stream_state(False)
            if self.source is not wanted:
                self.lines = 0  # the "chat lines this session" counter belongs to one mode
            self.source = wanted
            if wanted is not None:
                try:
                    await wanted.start()
                except Exception:
                    logger.exception("Starting %s failed", wanted.name)
            self.bus.publish("mode", {"mode": self.mode})
            return self.status()

    async def shutdown(self) -> None:
        async with self._mode_lock:
            for s in self.sources.values():
                try:
                    await s.stop()
                except Exception:
                    logger.exception("Stopping %s failed", s.name)
            self.source = None

    # ------------------------------------------------------------------ stream state
    def stream_state(self, live: bool, title: str = "") -> None:
        if live == self.stream_live and (not live or title == self.stream_title):
            return
        was_live = self.stream_live
        self.stream_live = live
        self.stream_title = title if live else ""
        self._stream_started = time.time() if live and not was_live else (self._stream_started if live else None)
        self.bus.publish("stream", {"live": live, "title": self.stream_title})
        if self.mode == "live" and self.cfg.get("telegram_notify_stream_events"):
            self._spawn(self._notify(stream_card(live, title)))

    def uptime(self) -> float | None:
        return time.time() - self._stream_started if self.stream_live and self._stream_started else None

    def _spawn(self, coro: Awaitable[Any]) -> None:
        task = asyncio.ensure_future(coro)
        task.add_done_callback(lambda t: t.cancelled() or t.exception() is None or logger.error("Background task failed: %s", t.exception()))

    # ------------------------------------------------------------------ outbound
    async def _notify(self, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> None:
        if self.notify is None:
            return
        try:
            await self.notify(text, buttons)
        except Exception:
            logger.exception("Notification failed")

    async def send_chat(self, text: str) -> bool:
        text = truncate((text or "").strip(), self.cfg.get("youtube_message_max_length") if self.mode == "live" else 400)
        if not text or self.source is None:
            return False
        async with self._send_lock:
            self._sent.append((text, time.time()))
            try:
                ok = await self.source.send(text)
            except Exception:
                logger.exception("send failed")
                return False
        return ok

    def _is_echo(self, text: str, now: float) -> bool:
        while self._sent and now - self._sent[0][1] > 90:
            self._sent.popleft()
        for i, (t, _) in enumerate(self._sent):
            if t == text.strip():
                del self._sent[i]
                return True
        return False

    # ------------------------------------------------------------------ the pipeline
    async def ingest(self, msg: ChatMessage) -> ChatMessage:
        # Regulars are promoted unless they already hold a higher level.
        if msg.level in ("everyone", "member") and self.store.is_regular(msg.author_id, msg.author_name):
            msg.level = "regular"
        if not msg.from_bot and msg.level in ("owner", "mod", "bot") and self._is_echo(msg.text, msg.ts):
            msg.from_bot = True

        verdict: Verdict | None = None
        if not msg.backfill and not msg.from_bot and self.cfg.get("mod_mode") != "off":
            verdict = self.engine.evaluate(ModInput(msg.platform, msg.author_id, msg.author_name, msg.text, msg.level, msg.ts))
            msg.score, msg.verdict = verdict.score, verdict.action
            if verdict.action != "allow":
                await self._handle_verdict(msg, verdict)

        try:
            msg.id = await self.store.add_chat(msg.to_dict() | {"text": msg.text})
        except Exception:
            logger.exception("Could not store chat message")
        payload = msg.to_dict() | {"reasons": verdict.reasons if verdict else []}
        self.buffer.append(payload)
        self.bus.publish("chat", payload)

        if msg.from_bot or msg.backfill:
            return msg
        self.lines += 1
        if ACTION_RANK.get(msg.verdict, -1) < ACTION_RANK["delete"]:
            try:
                replies = await self.commands.handle(msg) or await self.commands.handle_triggers(msg)
                for reply in replies:
                    await self.send_chat(reply)
            except Exception:
                logger.exception("Command handling failed")
        return msg

    # ------------------------------------------------------------------ moderation workflow
    async def _handle_verdict(self, msg: ChatMessage, v: Verdict) -> None:
        mode = self.cfg.get("mod_mode")
        now = time.time()
        action = v.action
        record: dict[str, Any] = {
            "ts": now, "platform": msg.platform, "author_id": msg.author_id, "author_name": msg.author_name,
            "message_ids": [msg.msg_id] if msg.msg_id else [], "text": msg.text, "action": action,
            "duration": v.duration, "score": v.score, "reasons": v.reasons, "mode": mode, "demo": msg.demo,
        }
        if v.blacklist_ids:
            await self.store.bump_blacklist(v.blacklist_ids)

        if action == "flag":
            await self.store.create_action(record | {"status": "logged"})
            self.bus.publish("mod_logged", {"author": msg.author_name, "action": "flag", "score": v.score})
            if self.cfg.get("mod_notify_on_flag"):
                self._spawn(self._notify(flag_card(msg.author_name, v.score, msg.text)))
            return

        key = f"{msg.platform}:{msg.author_id}"
        auto = mode == "auto" and action in split_csv(self.cfg.get("mod_auto_actions"))
        if auto and action in ("timeout", "ban") and now - self._recent_punish.get(key, 0) < self.cfg.get("mod_action_cooldown_seconds"):
            action = record["action"] = "delete"  # already punished a moment ago: just remove this message
            record["duration"] = None
        if auto:
            id_ = await self.store.create_action(record | {"status": "pending"})
            await self._execute(id_)
            return

        if action in ("timeout", "ban"):
            existing = await self.store.pending_for_author(msg.platform, msg.author_id)
            if existing:
                ids = existing["message_ids"] + record["message_ids"]
                strongest = action if ACTION_RANK[action] > ACTION_RANK[existing["action"]] else existing["action"]
                await self.store.update_action(
                    existing["id"], message_ids=ids[-self.cfg.get("mod_max_deletes_per_action"):], score=max(existing["score"], v.score),
                    action=strongest, duration=record["duration"] if strongest == "timeout" else None,
                    reasons=sorted(set(existing["reasons"]) | set(v.reasons)))
                self.bus.publish("mod_pending", {"id": existing["id"], "merged": True})
                return
        id_ = await self.store.create_action(record | {"status": "pending"})
        self.bus.publish("mod_pending", {"id": id_, "author": msg.author_name, "action": action, "score": v.score})
        if self.cfg.get("telegram_notify_pending"):
            self._spawn(self._notify_pending(id_, record))

    async def _notify_pending(self, id_: int, r: dict[str, Any]) -> None:
        now = time.time()
        while self._notify_times and now - self._notify_times[0] > 60:
            self._notify_times.popleft()
        if len(self._notify_times) >= self.cfg.get("telegram_notify_max_per_min"):
            self._suppressed += 1
            return
        self._notify_times.append(now)
        extra = f"+{self._suppressed} more waiting, see /pending" if self._suppressed else ""
        self._suppressed = 0
        await self._notify(approval_card(id_, r, extra), approval_keyboard(id_))

    async def _execute(self, id_: int) -> dict[str, Any]:
        a = await self.store.get_action(id_)
        if not a or a["status"] != "pending":
            return {"ok": False, "error": "This request is no longer pending."}
        src = self.sources.get("demo" if a["demo"] else a["platform"]) or self.source
        errors: list[str] = []
        simulated = a["demo"] or src is None or src.name == "demo"
        if not simulated:
            ids = a["message_ids"][-self.cfg.get("mod_max_deletes_per_action"):]
            preflight = getattr(src, "preflight", None)
            if preflight is not None:
                ok, err = await preflight(len(ids), a["action"])
                if not ok:
                    errors.append(err)
            for mid in ids if not errors else []:
                ok, err = await src.delete(mid)
                if not ok:
                    errors.append(err)
                    if "quota" in err.lower() or "not allowed to" in err.lower():
                        break  # out of quota, or YouTube said this account may not do this: more tries cannot succeed
            if a["action"] == "timeout" and not errors:
                ok, err = await src.timeout(a["author_id"], a["duration"] or 300)
                if not ok:
                    errors.append(err)
            elif a["action"] == "ban" and not errors:
                ok, err = await src.ban(a["author_id"])
                if not ok:
                    errors.append(err)
        status = "failed" if errors else ("simulated" if simulated else "executed")
        await self.store.update_action(id_, status=status, error="; ".join(errors)[:300], resolved_ts=time.time())
        if status != "failed":
            key = f"{a['platform']}:{a['author_id']}"
            self.engine.add_strike(key)
            if a["action"] in ("timeout", "ban"):
                self._recent_punish[key] = time.time()
        self.bus.publish("mod_resolved", {"id": id_, "status": status, "action": a["action"], "author": a["author_name"]})
        return {"ok": status != "failed", "status": status, "error": "; ".join(errors)}

    async def approve(self, id_: int) -> dict[str, Any]:
        return await self._execute(id_)

    async def reject(self, id_: int) -> dict[str, Any]:
        a = await self.store.get_action(id_)
        if not a or a["status"] != "pending":
            return {"ok": False, "error": "This request is no longer pending."}
        await self.store.update_action(id_, status="rejected", resolved_ts=time.time())
        self.bus.publish("mod_resolved", {"id": id_, "status": "rejected", "action": a["action"], "author": a["author_name"]})
        return {"ok": True, "status": "rejected"}

    async def resolve_all(self, approve: bool, demo: bool | None = None) -> dict[str, int]:
        done = failed = 0
        for a in await self.store.pending_actions(demo):
            res = await (self.approve(a["id"]) if approve else self.reject(a["id"]))
            done += 1 if res.get("ok") else 0
            failed += 0 if res.get("ok") else 1
        return {"resolved": done, "failed": failed}

    async def reload_blacklist(self) -> None:
        self.engine.set_blacklist(await self.store.list_blacklist())

    # ------------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        src = self.source.status() if self.source else {"state": "stopped"}
        return {
            "mode": self.mode, "source": self.source.name if self.source else None, "source_status": src,
            "stream_live": self.stream_live, "stream_title": self.stream_title, "uptime": self.uptime(),
            "mod_mode": self.cfg.get("mod_mode"), "lines": self.lines,
            "blacklist_size": self.engine.matcher.size,
        }
