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
from .moderation.bans import Bans
from .moderation import ACTION_RANK, ModerationEngine, ModInput, Verdict
from .sessions import Sessions
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
    async def unban(self, ban_ref: str) -> tuple[bool, str]: ...
    def status(self) -> dict[str, Any]: ...


class Hub:
    def __init__(self, cfg: Any, store: Store, bus: EventBus, engine: ModerationEngine, commands: CommandEngine) -> None:
        self.cfg = cfg
        self.store = store
        self.bans = Bans(store.db, cfg)
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
        self.shared: Any = None          # 1.1.8: set by the container when Redis is on
        self.active: Callable[[], bool] | None = None   # 1.1.8: a standby instance must not start a chat source
        self._notify_times: deque[float] = deque()
        self._suppressed = 0
        self.learning: Any = None   # app.intel.Learning: learns from approve/reject decisions (optional)
        self._mode_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        # 1.3.5: every livestream is its own session with its own chat (see sessions.py)
        self.sessions = Sessions(store.db)
        self.session: dict[str, Any] | None = None     # the stream that is running now
        self._session_lock = asyncio.Lock()            # begin/end run one at a time, in the order they were asked for
        self._session_pending: "asyncio.Future[Any] | None" = None

    # ------------------------------------------------------------------ sources and mode
    # 1.1.8: the "just punished" memory and the recent-message ids, as plain data
    def export_state(self, now: float) -> dict[str, Any]:
        return {"punish": {k: t for k, t in self._recent_punish.items() if now - t <= 3600}}

    def import_state(self, data: dict[str, Any]) -> None:
        for k, t in (data.get("punish") or {}).items():
            self._recent_punish[str(k)] = float(t)

    def register(self, source: ChatSource) -> None:
        self.sources[source.name] = source

    @property
    def mode(self) -> str:
        return self.cfg.get("bot_mode")

    def source_name_for_mode(self) -> str:
        return "demo" if self.mode == "demo" else "youtube"

    async def apply_mode(self) -> dict[str, Any]:
        """Start the chat source that matches bot_mode (demo | live), stopping the previous one."""
        if self.active is not None and not self.active():
            return self.status()
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
        await self.end_session()

    # ------------------------------------------------------------------ stream state
    def stream_state(self, live: bool, title: str = "") -> None:
        if live == self.stream_live and (not live or title == self.stream_title):
            return
        was_live = self.stream_live
        self.stream_live = live
        self.stream_title = title if live else ""
        self._stream_started = time.time() if live and not was_live else (self._stream_started if live else None)
        # A stream starting is a new session (with a fresh chat); a stream ending closes it. The work is queued, never blocking this call.
        if live and not was_live:
            demo, src = self.mode == "demo", self.source
            # what identifies the stream is read now: a moment later the source may already have let go of it
            self._session_pending = self._spawn(self._begin_session(title, "" if demo else str(getattr(src, "video_id", "") or ""), src.name if src else "", demo))
        elif live:
            self._spawn(self._retitle_session(title))
        elif was_live:
            self._spawn(self.end_session())
        self.bus.publish("stream", {"live": live, "title": self.stream_title})
        if self.mode == "live" and self.cfg.get("telegram_notify_stream_events"):
            self._spawn(self._notify(stream_card(live, title)))

    # ------------------------------------------------------------------ stream sessions
    @property
    def session_id(self) -> str:
        return self.session["id"] if self.session else ""

    async def _begin_session(self, title: str, video_id: str, platform: str, demo: bool) -> None:
        async with self._session_lock:
            if self.session is not None:       # one is already open (a repeated start): keep it
                return
            try:
                row, resumed = await self.sessions.begin(time.time(), title, video_id, platform, demo)
            except Exception:
                logger.exception("Could not start a stream session; chat will still work but will not be grouped")
                return
            self.session = row
            if resumed:
                # the same stream came back (a reconnect or a restart): carry on in its chat
                self.lines = int(((await self.sessions.compute(row, time.time())) or {}).get("messages", 0))
                self.buffer.clear()
                for m in (await self.sessions.chat(row["id"], limit=self.buffer.maxlen or 400))[-(self.buffer.maxlen or 400):]:
                    self.buffer.append(m)
            else:
                self.buffer.clear()            # a new stream starts with an empty chat
                self.lines = 0
            self.bus.publish("session", {"id": row["id"], "live": True, "resumed": resumed, "title": row.get("title", ""), "started": row["started"]})

    async def _retitle_session(self, title: str) -> None:
        async with self._session_lock:
            if self.session is not None and title:
                self.session["title"] = title
                try:
                    await self.sessions.set_title(self.session["id"], title)
                except Exception:
                    logger.exception("Could not update the stream title")

    async def end_session(self) -> None:
        async with self._session_lock:
            cur, self.session = self.session, None
            if cur is None:
                return
            try:
                done = await self.sessions.finish(cur["id"], time.time())
            except Exception:
                logger.exception("Could not close the stream session")
                done = None
            # the buffer is NOT cleared here: for a moment after the stream ends you can still read its last lines. The next stream's start clears it.
            self.bus.publish("session", {"id": cur["id"], "live": False, "kept": done is not None})

    async def _session_ready(self) -> None:
        """A message must not be filed before its stream's session exists."""
        p = self._session_pending
        if p is not None and not p.done():
            try:
                await asyncio.shield(p)
            except Exception:
                pass

    def uptime(self) -> float | None:
        return time.time() - self._stream_started if self.stream_live and self._stream_started else None

    def _spawn(self, coro: Awaitable[Any]) -> "asyncio.Future[Any]":
        task = asyncio.ensure_future(coro)
        task.add_done_callback(lambda t: t.cancelled() or t.exception() is None or logger.error("Background task failed: %s", t.exception()))
        return task

    # ------------------------------------------------------------------ outbound
    async def _notify(self, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> None:
        if self.notify is None:
            return
        try:
            await self.notify(text, buttons)
        except Exception:
            logger.exception("Notification failed")

    async def send_chat(self, text: str, render: bool = False) -> bool:
        """render=True expands $(variables) first. Only text typed by the owner is rendered, never text that was already rendered or came from chat."""
        if render and "$(" in (text or "") and self.commands is not None:
            from .commands.variables import Ctx
            text = await self.commands.renderer.render(text, Ctx(channel=self.commands.channel_fn() if getattr(self.commands, "channel_fn", None) else ""))
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
        if self._session_pending is not None and not self._session_pending.done():
            await self._session_ready()
        # With Redis on, a message id is claimed once: a restart, or a second instance overlapping during a hand-over,
        # never moderates or answers the same live message twice. (Demo and unlabelled messages are not tracked.)
        if self.shared is not None and self.shared.configured and msg.msg_id and not msg.demo:
            if not await self.shared.set(f"seen:{msg.platform}:{msg.msg_id}", "1", ex=600, nx=True):
                return msg
        # Regulars are promoted unless they already hold a higher level.
        if msg.level in ("everyone", "member") and self.store.is_regular(msg.author_id, msg.author_name):
            msg.level = "regular"
        if not msg.from_bot and msg.level in ("owner", "mod", "bot") and self._is_echo(msg.text, msg.ts):
            msg.from_bot = True

        verdict: Verdict | None = None
        if not msg.backfill and not msg.from_bot and self.cfg.get("mod_mode") != "off":
            verdict = self.engine.evaluate(ModInput(msg.platform, msg.author_id, msg.author_name, msg.text, msg.level, msg.ts))
            msg.score, msg.verdict = verdict.score, verdict.action
            intel = self.engine.intel
            if intel is not None and intel.pop_wave_started():
                self.bus.publish("intel_wave", {"ts": msg.ts, "demo": msg.platform == "demo"})
                if msg.platform != "demo":
                    await self._notify("\U0001f30a Raid wave: many brand-new accounts started chatting within seconds. "
                                       "I am watching messages from new accounts more closely for a few minutes.")
            if verdict.action != "allow":
                await self._handle_verdict(msg, verdict)

        try:
            msg.id = await self.store.add_chat(msg.to_dict() | {"text": msg.text, "session_id": self.session_id})
        except Exception:
            logger.exception("Could not store chat message")
        if self.learning is not None and not msg.backfill and not msg.from_bot:
            try:
                await self.learning.trusted(msg, verdict.action if verdict else "allow")
            except Exception:
                logger.exception("Learning from trusted chat failed")
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
        auto_mode = mode == "auto"
        action, duration, softened = await self.bans.limit(
            v.action, v.duration, [sg.name for sg in v.signals], msg.author_id, msg.author_name,
            auto_mode and v.action in split_csv(self.cfg.get("mod_auto_actions")), now)
        record: dict[str, Any] = {
            "ts": now, "platform": msg.platform, "author_id": msg.author_id, "author_name": msg.author_name,
            "message_ids": [msg.msg_id] if msg.msg_id else [], "text": msg.text, "action": action,
            "duration": duration, "score": v.score, "reasons": v.reasons + ([f"Softened: {softened}"] if softened else []), "mode": mode, "demo": msg.demo,
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
            await self._execute(id_, source="auto")
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

    async def _execute(self, id_: int, source: str = "approved") -> dict[str, Any]:
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
                await self.bans.record(
                    author_id=a["author_id"], author_name=a["author_name"], kind=a["action"], duration=a["duration"] if a["action"] == "timeout" else None,
                    ban_ref="" if simulated else str(getattr(src, "last_ban_id", "") or ""), action_id=id_, source=source,
                    reason=", ".join(a.get("reasons") or [])[:300], platform=a["platform"], demo=simulated)
                self.bus.publish("ban_made", {"author": a["author_name"], "kind": a["action"], "source": source})
        self.bus.publish("mod_resolved", {"id": id_, "status": status, "action": a["action"], "author": a["author_name"]})
        return {"ok": status != "failed", "status": status, "error": "; ".join(errors)}

    async def manual(self, chat_id: int, action: str, seconds: int = 300) -> dict[str, Any]:
        """Delete one message, or time out or ban its author, because the owner chose to from the chat. Uses the same permission and quota checks as an approval.
        The row is looked up here, so the page cannot ask for an action on someone who never wrote in the chat."""
        if action not in ("delete", "timeout", "ban"):
            return {"ok": False, "error": "Unknown action.", "code": 422}
        row = await self.store.db.fetchone("SELECT platform, msg_id, author_id, author_name, level, demo FROM chat_messages WHERE id = ?", (chat_id,))
        if not row:
            return {"ok": False, "error": "That message is no longer stored.", "code": 404}
        if row["level"] in ("owner", "bot"):
            return {"ok": False, "error": "The owner and the bot cannot be moderated.", "code": 400}
        simulated = bool(row["demo"])
        src = self.sources.get("demo" if simulated else row["platform"]) or self.source
        err = ""
        if not simulated:
            if src is None:
                return {"ok": False, "error": "The chat connection is not available right now."}
            pre = getattr(src, "preflight", None)
            if pre is not None:
                ok, err = await pre(1 if action == "delete" else 0, action)
                if not ok:
                    return {"ok": False, "error": err}
            if action == "delete":
                ok, err = await src.delete(row["msg_id"])
            elif action == "timeout":
                ok, err = await src.timeout(row["author_id"], seconds)
            else:
                ok, err = await src.ban(row["author_id"])
            if not ok:
                return {"ok": False, "error": err}
        ban_id = None
        if action in ("timeout", "ban"):
            ban_id = await self.bans.record(author_id=row["author_id"], author_name=row["author_name"], kind=action, duration=seconds if action == "timeout" else None,
                                            ban_ref="" if simulated else str(getattr(src, "last_ban_id", "") or ""), action_id=None, source="dashboard", reason="Chosen from the chat",
                                            platform=row["platform"], demo=simulated)
            self.bus.publish("ban_made", {"author": row["author_name"], "kind": action, "source": "dashboard"})
        else:
            self.bus.publish("chat_deleted", {"author": row["author_name"], "simulated": simulated})
        return {"ok": True, "ban_id": ban_id, "simulated": simulated}

    async def unban(self, ban_id: int, by: str = "dashboard") -> dict[str, Any]:
        """Lift one ban or timeout from the ledger. YouTube must confirm it before it is marked as lifted."""
        row = await self.bans.get(ban_id)
        if not row:
            return {"ok": False, "error": "That ban is not in the ledger.", "code": 404}
        if row["status"] != "active":
            return {"ok": False, "error": f"That ban is already {row['status']}."}
        if not row["demo"]:
            src = self.sources.get(row["platform"]) or self.source
            if src is None or not hasattr(src, "unban"):
                return {"ok": False, "error": "The chat connection is not available right now."}
            ok, err = await src.unban(row["ban_ref"])
            if not ok:
                await self.bans.mark_error(ban_id, err)
                return {"ok": False, "error": err}
        await self.bans.mark_lifted(ban_id, by)
        self.engine.strikes_clear(f"{row['platform']}:{row['author_id']}")
        self.bus.publish("ban_lifted", {"id": ban_id, "author": row["author_name"], "by": by})
        return {"ok": True}

    async def second_chance(self, now: float) -> None:
        """Lift permanent bans the bot made itself once they are older than your second-chance setting."""
        for row in await self.bans.due_second_chance(now):
            res = await self.unban(row["id"], by="second chance")
            if not res["ok"] and "quota" in res["error"].lower():
                break

    async def _learn(self, action: dict[str, Any] | None, label: str) -> None:
        """Every approve/reject is a training label ("spam" for Approve, "ham" for Reject). Learning must never get in the way of moderation."""
        if self.learning is None or action is None:
            return
        try:
            await self.learning.feedback(action, label)
        except Exception:
            logger.exception("Learning from a decision failed")

    async def approve(self, id_: int) -> dict[str, Any]:
        a = await self.store.get_action(id_)
        res = await self._execute(id_)
        if res.get("ok"):
            await self._learn(a, "spam")
        return res

    async def reject(self, id_: int) -> dict[str, Any]:
        a = await self.store.get_action(id_)
        if not a or a["status"] != "pending":
            return {"ok": False, "error": "This request is no longer pending."}
        await self.store.update_action(id_, status="rejected", resolved_ts=time.time())
        await self._learn(a, "ham")
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
            "session": {"id": self.session["id"], "started": self.session["started"], "title": self.session.get("title", ""), "resumed": bool(self.session.get("resumed"))} if self.session else None,
            "blacklist_size": self.engine.matcher.size,
        }
