"""Storage layer: every read and write the bot makes goes through here."""
from __future__ import annotations

import json
import re
import time
from typing import Any

from .db import Database

NAME_RE = re.compile(r"^[a-z0-9_\-]{1,32}$")
LEVELS = {"everyone": 0, "member": 1, "regular": 2, "mod": 3, "owner": 4}


class ValidationFailed(ValueError):
    pass


def valid_level(level: str) -> str:
    level = (level or "everyone").lower()
    if level not in LEVELS:
        raise ValidationFailed(f"userlevel must be one of {', '.join(LEVELS)}")
    return level


def clean_name(name: str, prefix: str = "!") -> str:
    n = (name or "").strip().lower()
    if prefix and n.startswith(prefix):
        n = n[len(prefix):]
    if not NAME_RE.match(n):
        raise ValidationFailed("Name may use letters, numbers, - and _ (max 32 characters).")
    return n


class Store:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._regulars: set[str] = set()

    # ------------------------------------------------------------------ generic
    async def _update(self, table: str, id_: int, allowed: tuple[str, ...], fields: dict[str, Any]) -> bool:
        cols = [k for k in fields if k in allowed]
        if not cols:
            return False
        sql = f"UPDATE {table} SET " + ", ".join(f"{c} = ?" for c in cols) + " WHERE id = ?"
        return (await self.db.execute(sql, [fields[c] for c in cols] + [id_])) > 0

    async def _delete(self, table: str, id_: int) -> bool:
        return (await self.db.execute(f"DELETE FROM {table} WHERE id = ?", (id_,))) > 0

    # ------------------------------------------------------------------ commands
    @staticmethod
    def _cmd(r: dict | None) -> dict | None:
        if r:
            r["enabled"] = bool(r["enabled"])
            r["aliases"] = [a for a in (r["aliases"] or "").split(",") if a]
        return r

    async def list_commands(self) -> list[dict]:
        return [self._cmd(r) for r in await self.db.fetchall("SELECT * FROM commands ORDER BY name")]

    async def get_command(self, id_: int) -> dict | None:
        return self._cmd(await self.db.fetchone("SELECT * FROM commands WHERE id = ?", (id_,)))

    async def find_command(self, name: str) -> dict | None:
        name = name.lower()
        r = await self.db.fetchone("SELECT * FROM commands WHERE name = ?", (name,))
        if r:
            return self._cmd(r)
        for c in await self.db.fetchall("SELECT * FROM commands WHERE aliases <> ''"):
            if name in c["aliases"].split(","):
                return self._cmd(c)
        return None

    async def create_command(self, name: str, response: str, userlevel: str = "everyone", cooldown: int = 5,
                             user_cooldown: int = 10, enabled: bool = True, aliases: list[str] | None = None) -> int:
        name = clean_name(name)
        if not response.strip():
            raise ValidationFailed("Response cannot be empty.")
        if await self.find_command(name):
            raise ValidationFailed(f"!{name} already exists.")
        al = ",".join(clean_name(a) for a in (aliases or []))
        return await self.db.insert(
            "INSERT INTO commands (name, response, userlevel, cooldown, user_cooldown, enabled, aliases, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, response.strip(), valid_level(userlevel), max(0, cooldown), max(0, user_cooldown), int(enabled), al, time.time()),
        )

    async def update_command(self, id_: int, **fields: Any) -> bool:
        if "name" in fields:
            fields["name"] = clean_name(fields["name"])
        if "userlevel" in fields:
            fields["userlevel"] = valid_level(fields["userlevel"])
        if "aliases" in fields:
            fields["aliases"] = ",".join(clean_name(a) for a in fields["aliases"])
        if "enabled" in fields:
            fields["enabled"] = int(bool(fields["enabled"]))
        return await self._update("commands", id_, ("name", "response", "userlevel", "cooldown", "user_cooldown", "enabled", "aliases"), fields)

    async def delete_command(self, id_: int) -> bool:
        return await self._delete("commands", id_)

    async def bump_command(self, id_: int) -> None:
        await self.db.execute("UPDATE commands SET uses = uses + 1 WHERE id = ?", (id_,))

    # ------------------------------------------------------------------ timers
    @staticmethod
    def _timer(r: dict | None) -> dict | None:
        if r:
            r["enabled"] = bool(r["enabled"])
            r["done"] = bool(r.get("done", 0))
        return r

    @staticmethod
    def validate_timer(kind: str, interval_seconds: int, min_lines: int, trigger_mode: str, message: str) -> tuple[str, int, int, str]:
        """Trigger rules. recurring: at least one of time / lines. once: neither is used."""
        kind = (kind or "recurring").lower()
        trigger_mode = (trigger_mode or "all").lower()
        if kind not in ("recurring", "once"):
            raise ValidationFailed("Type must be recurring or once.")
        if trigger_mode not in ("all", "any"):
            raise ValidationFailed("Trigger mode must be all or any.")
        if not (message or "").strip():
            raise ValidationFailed("Message cannot be empty.")
        interval_seconds, min_lines = max(0, int(interval_seconds or 0)), max(0, int(min_lines or 0))
        if kind == "once":
            return kind, 0, 0, "all"
        if interval_seconds and interval_seconds < 60:
            raise ValidationFailed("Time between posts must be at least 60 seconds, or left empty.")
        if not interval_seconds and not min_lines:
            raise ValidationFailed("A recurring timer needs a time interval, a number of chat lines, or both.")
        return kind, interval_seconds, min_lines, trigger_mode

    async def list_timers(self) -> list[dict]:
        return [self._timer(r) for r in await self.db.fetchall("SELECT * FROM timers ORDER BY name")]

    async def get_timer(self, id_: int) -> dict | None:
        return self._timer(await self.db.fetchone("SELECT * FROM timers WHERE id = ?", (id_,)))

    async def create_timer(self, name: str, message: str, interval_seconds: int = 0, min_lines: int = 0, enabled: bool = True,
                           kind: str = "recurring", trigger_mode: str = "all", run_at: float | None = None) -> int:
        name = clean_name(name, prefix="")
        kind, interval_seconds, min_lines, trigger_mode = self.validate_timer(kind, interval_seconds, min_lines, trigger_mode, message)
        if await self.db.fetchone("SELECT id FROM timers WHERE name = ?", (name,)):
            raise ValidationFailed(f"A timer named {name} already exists.")
        return await self.db.insert(
            "INSERT INTO timers (name, message, interval_seconds, min_lines, enabled, created, kind, trigger_mode, run_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, message.strip(), interval_seconds, min_lines, int(enabled), time.time(), kind, trigger_mode, run_at if kind == "once" else None),
        )

    async def update_timer(self, id_: int, **fields: Any) -> bool:
        current = await self.get_timer(id_)
        if current is None:
            return False
        if "name" in fields:
            fields["name"] = clean_name(fields["name"], prefix="")
        merged = current | fields
        kind, iv, ml, mode = self.validate_timer(merged["kind"], merged["interval_seconds"], merged["min_lines"], merged["trigger_mode"], merged["message"])
        fields.update(kind=kind, interval_seconds=iv, min_lines=ml, trigger_mode=mode)
        if "message" in fields:
            fields["message"] = fields["message"].strip()
        if "enabled" in fields:
            fields["enabled"] = int(bool(fields["enabled"]))
            if fields["enabled"] and current["done"]:      # turning a finished one-time message back on re-arms it
                fields["done"] = 0
        if "done" in fields:
            fields["done"] = int(bool(fields["done"]))
        return await self._update("timers", id_, ("name", "message", "interval_seconds", "min_lines", "enabled", "kind", "trigger_mode", "run_at", "done", "last_error"), fields)

    async def delete_timer(self, id_: int) -> bool:
        await self.db.execute("DELETE FROM timer_runs WHERE timer_id = ?", (id_,))
        return await self._delete("timers", id_)

    async def mark_timer_fired(self, id_: int, ts: float, demo: bool = False) -> None:
        await self.db.execute("UPDATE timers SET last_fired = ?, fired = fired + 1, last_error = '' WHERE id = ?", (ts, id_))
        await self.add_timer_run(id_, ts, True, "", demo)

    async def finish_once_timer(self, id_: int) -> None:
        await self.db.execute("UPDATE timers SET done = 1, enabled = 0 WHERE id = ?", (id_,))

    async def mark_timer_failed(self, id_: int, ts: float, error: str, demo: bool = False) -> None:
        await self.db.execute("UPDATE timers SET last_error = ? WHERE id = ?", (error[:300], id_))
        await self.add_timer_run(id_, ts, False, error, demo)

    async def add_timer_run(self, timer_id: int, ts: float, ok: bool, error: str = "", demo: bool = False) -> None:
        await self.db.insert("INSERT INTO timer_runs (timer_id, ts, ok, error, demo) VALUES (?, ?, ?, ?, ?)", (timer_id, ts, int(ok), error[:300], int(demo)))

    async def timer_runs(self, timer_id: int | None = None, limit: int = 50, demo: bool | None = None) -> list[dict]:
        where, params = [], []
        if timer_id is not None:
            where.append("timer_id = ?"); params.append(timer_id)
        if demo is not None:
            where.append("demo = ?"); params.append(int(demo))
        sql = "SELECT * FROM timer_runs" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY ts DESC LIMIT ?"
        rows = await self.db.fetchall(sql, (*params, limit))
        for r in rows:
            r["ok"], r["demo"] = bool(r["ok"]), bool(r["demo"])
        return rows

    # ------------------------------------------------------------------ quotes
    async def list_quotes(self) -> list[dict]:
        return await self.db.fetchall("SELECT * FROM quotes ORDER BY id")

    async def add_quote(self, body: str, author: str = "") -> int:
        if not body.strip():
            raise ValidationFailed("Quote cannot be empty.")
        return await self.db.insert("INSERT INTO quotes (body, author, created) VALUES (?, ?, ?)", (body.strip(), author, time.time()))

    async def random_quote(self) -> dict | None:
        return await self.db.fetchone("SELECT * FROM quotes ORDER BY RANDOM() LIMIT 1")

    async def quote_number(self, n: int) -> dict | None:
        """1-based position in id order."""
        if n < 1:
            return None
        return await self.db.fetchone("SELECT * FROM quotes ORDER BY id LIMIT 1 OFFSET ?", (n - 1,))

    async def delete_quote(self, id_: int) -> bool:
        return await self._delete("quotes", id_)

    # ------------------------------------------------------------------ regulars
    async def load_regulars(self) -> None:
        self._regulars = {r["ident"] for r in await self.db.fetchall("SELECT ident FROM regulars")}

    def is_regular(self, *idents: str) -> bool:
        return any(i.lower().lstrip("@") in self._regulars for i in idents if i)

    async def list_regulars(self) -> list[dict]:
        return await self.db.fetchall("SELECT * FROM regulars ORDER BY label")

    async def add_regular(self, ident: str, label: str = "") -> int:
        ident = (ident or "").strip().lower().lstrip("@")
        if not ident:
            raise ValidationFailed("Enter a channel name or channel id.")
        existing = await self.db.fetchone("SELECT id FROM regulars WHERE ident = ?", (ident,))
        if existing:
            return existing["id"]
        id_ = await self.db.insert("INSERT INTO regulars (ident, label, created) VALUES (?, ?, ?)", (ident, label.strip() or ident, time.time()))
        await self.load_regulars()
        return id_

    async def delete_regular(self, id_: int) -> bool:
        ok = await self._delete("regulars", id_)
        await self.load_regulars()
        return ok

    # ------------------------------------------------------------------ blacklist
    @staticmethod
    def _bl(r: dict | None) -> dict | None:
        if r:
            r["enabled"] = bool(r["enabled"])
            r["is_regex"] = bool(r["is_regex"])
        return r

    async def list_blacklist(self) -> list[dict]:
        return [self._bl(r) for r in await self.db.fetchall("SELECT * FROM blacklist ORDER BY phrase")]

    BL_CATEGORIES = ("blocked_words", "blocked_phrases", "spam", "links", "suspicious", "custom")

    async def add_blacklist(self, phrase: str, is_regex: bool = False, weight: int = 0, enabled: bool = True, category: str = "blocked_phrases") -> int:
        phrase = (phrase or "").strip()
        if not phrase:
            raise ValidationFailed("Phrase cannot be empty.")
        if is_regex:
            try:
                re.compile(phrase)
            except re.error as exc:
                raise ValidationFailed(f"Invalid regular expression: {exc}") from exc
        if not 0 <= weight <= 100:
            raise ValidationFailed("Weight must be 0-100 (0 uses the default).")
        if category not in self.BL_CATEGORIES:
            raise ValidationFailed(f"Category must be one of {', '.join(self.BL_CATEGORIES)}.")
        if await self.db.fetchone("SELECT id FROM blacklist WHERE phrase = ?", (phrase,)):
            raise ValidationFailed("That phrase is already on the list.")
        return await self.db.insert(
            "INSERT INTO blacklist (phrase, is_regex, weight, enabled, created, category) VALUES (?, ?, ?, ?, ?, ?)",
            (phrase, int(is_regex), weight, int(enabled), time.time(), category),
        )

    async def preview_blacklist_import(self, items: list[dict]) -> dict:
        """Validate and de-duplicate without writing anything. Each item: phrase, is_regex, weight, category."""
        existing = {r["phrase"].lower() for r in await self.db.fetchall("SELECT phrase FROM blacklist")}
        seen: set[str] = set()
        ok, duplicates, invalid = [], [], []
        for raw in items:
            phrase = str(raw.get("phrase", "")).strip()
            is_regex, weight = bool(raw.get("is_regex", False)), int(raw.get("weight", 0) or 0)
            category = raw.get("category") or "blocked_phrases"
            reason = ""
            if not phrase:
                reason = "empty"
            elif len(phrase) > 200:
                reason = "longer than 200 characters"
            elif not 0 <= weight <= 100:
                reason = "weight must be 0-100"
            elif category not in self.BL_CATEGORIES:
                reason = f"unknown category {category}"
            elif is_regex:
                try:
                    re.compile(phrase)
                except re.error as exc:
                    reason = f"invalid regex ({exc})"
            if reason:
                invalid.append({"phrase": phrase[:60], "reason": reason})
            elif phrase.lower() in existing or phrase.lower() in seen:
                duplicates.append(phrase)
            else:
                seen.add(phrase.lower())
                ok.append({"phrase": phrase, "is_regex": is_regex, "weight": weight, "category": category})
        return {"new": ok, "duplicates": duplicates, "invalid": invalid}

    async def import_blacklist(self, items: list[dict], enabled: bool = True) -> dict:
        plan = await self.preview_blacklist_import(items)
        for it in plan["new"]:
            await self.add_blacklist(it["phrase"], it["is_regex"], it["weight"], enabled, it["category"])
        return {"added": len(plan["new"]), "duplicates": len(plan["duplicates"]), "invalid": plan["invalid"]}

    async def bulk_blacklist(self, ids: list[int], action: str, category: str | None = None) -> int:
        ids = [int(i) for i in ids][:5000]
        if not ids:
            return 0
        marks = ", ".join("?" for _ in ids)
        if action == "delete":
            return await self.db.execute(f"DELETE FROM blacklist WHERE id IN ({marks})", ids)
        if action in ("enable", "disable"):
            return await self.db.execute(f"UPDATE blacklist SET enabled = ? WHERE id IN ({marks})", [int(action == "enable"), *ids])
        if action == "move" and category in self.BL_CATEGORIES:
            return await self.db.execute(f"UPDATE blacklist SET category = ? WHERE id IN ({marks})", [category, *ids])
        raise ValidationFailed("Unknown bulk action.")

    async def update_blacklist(self, id_: int, **fields: Any) -> bool:
        for k in ("enabled", "is_regex"):
            if k in fields:
                fields[k] = int(bool(fields[k]))
        if "category" in fields and fields["category"] not in self.BL_CATEGORIES:
            raise ValidationFailed(f"Category must be one of {', '.join(self.BL_CATEGORIES)}.")
        return await self._update("blacklist", id_, ("phrase", "is_regex", "weight", "enabled", "category"), fields)

    async def delete_blacklist(self, id_: int) -> bool:
        return await self._delete("blacklist", id_)

    async def bump_blacklist(self, ids: list[int]) -> None:
        for i in ids:
            await self.db.execute("UPDATE blacklist SET hits = hits + 1 WHERE id = ?", (i,))

    # ------------------------------------------------------------------ notes
    @staticmethod
    def _note(r: dict | None) -> dict | None:
        if r:
            r["pinned"] = bool(r["pinned"])
            r["tags"] = [t for t in (r["tags"] or "").split(",") if t]
        return r

    async def list_notes(self) -> list[dict]:
        return [self._note(r) for r in await self.db.fetchall("SELECT * FROM notes ORDER BY pinned DESC, updated DESC")]

    async def add_note(self, body: str, tags: list[str] | None = None, pinned: bool = False) -> int:
        if not body.strip():
            raise ValidationFailed("Note cannot be empty.")
        now = time.time()
        return await self.db.insert(
            "INSERT INTO notes (body, tags, pinned, created, updated) VALUES (?, ?, ?, ?, ?)",
            (body.strip(), ",".join(t.strip() for t in (tags or []) if t.strip()), int(pinned), now, now),
        )

    async def update_note(self, id_: int, **fields: Any) -> bool:
        if "tags" in fields:
            fields["tags"] = ",".join(t.strip() for t in fields["tags"] if t.strip())
        if "pinned" in fields:
            fields["pinned"] = int(bool(fields["pinned"]))
        fields["updated"] = time.time()
        return await self._update("notes", id_, ("body", "tags", "pinned", "updated"), fields)

    async def delete_note(self, id_: int) -> bool:
        return await self._delete("notes", id_)

    # ------------------------------------------------------------------ reminders
    async def list_reminders(self, status: str | None = "pending") -> list[dict]:
        if status:
            return await self.db.fetchall("SELECT * FROM reminders WHERE status = ? ORDER BY due", (status,))
        return await self.db.fetchall("SELECT * FROM reminders ORDER BY due DESC LIMIT 200")

    async def add_reminder(self, body: str, due: float, repeat_kind: str = "none", interval_seconds: int | None = None) -> int:
        return await self.db.insert(
            "INSERT INTO reminders (body, due, repeat_kind, interval_seconds, status, created) VALUES (?, ?, ?, ?, 'pending', ?)",
            (body, due, repeat_kind, interval_seconds, time.time()),
        )

    async def due_reminders(self, now: float) -> list[dict]:
        return await self.db.fetchall("SELECT * FROM reminders WHERE status = 'pending' AND due <= ? ORDER BY due", (now,))

    async def finish_reminder(self, id_: int, now: float) -> None:
        await self.db.execute("UPDATE reminders SET status = 'done', fired_at = ? WHERE id = ?", (now, id_))

    async def reschedule_reminder(self, id_: int, due: float, now: float) -> None:
        await self.db.execute("UPDATE reminders SET due = ?, fired_at = ? WHERE id = ?", (due, now, id_))

    async def cancel_reminder(self, id_: int) -> bool:
        return (await self.db.execute("UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'", (id_,))) > 0

    # ------------------------------------------------------------------ chat log
    async def add_chat(self, m: dict) -> int:
        return await self.db.insert(
            "INSERT INTO chat_messages (platform, msg_id, author_id, author_name, body, level, ts, score, verdict, demo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (m["platform"], m.get("msg_id", ""), m["author_id"], m["author_name"], m["text"], m.get("level", "everyone"),
             m["ts"], m.get("score", 0), m.get("verdict", "allow"), int(m.get("demo", False))),
        )

    async def recent_chat(self, limit: int = 100, demo: bool | None = None) -> list[dict]:
        if demo is None:
            rows = await self.db.fetchall("SELECT * FROM chat_messages ORDER BY ts DESC, id DESC LIMIT ?", (limit,))
        else:
            rows = await self.db.fetchall("SELECT * FROM chat_messages WHERE demo = ? ORDER BY ts DESC, id DESC LIMIT ?", (int(demo), limit))
        return list(reversed(rows))

    async def chat_since(self, since: float, limit: int = 20000) -> list[dict]:
        return await self.db.fetchall(
            "SELECT ts, author_id, author_name, level, verdict, score, demo FROM chat_messages WHERE ts >= ? ORDER BY ts LIMIT ?",
            (since, limit),
        )

    async def clear_demo_data(self) -> None:
        await self.db.execute("DELETE FROM chat_messages WHERE demo = 1")
        await self.db.execute("DELETE FROM mod_actions WHERE demo = 1")

    # ------------------------------------------------------------------ moderation actions
    @staticmethod
    def _action(r: dict | None) -> dict | None:
        if r:
            r["message_ids"] = json.loads(r["message_ids"] or "[]")
            r["reasons"] = json.loads(r["reasons"] or "[]")
            r["demo"] = bool(r["demo"])
        return r

    async def create_action(self, a: dict) -> int:
        return await self.db.insert(
            "INSERT INTO mod_actions (ts, platform, author_id, author_name, message_ids, body, action, duration, score, "
            "reasons, status, mode, error, resolved_ts, demo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (a["ts"], a["platform"], a["author_id"], a["author_name"], json.dumps(a.get("message_ids", [])), a.get("text", ""),
             a["action"], a.get("duration"), a.get("score", 0), json.dumps(a.get("reasons", [])), a["status"],
             a.get("mode", "suggest"), a.get("error", ""), a.get("resolved_ts"), int(a.get("demo", False))),
        )

    async def get_action(self, id_: int) -> dict | None:
        return self._action(await self.db.fetchone("SELECT * FROM mod_actions WHERE id = ?", (id_,)))

    async def pending_actions(self, demo: bool | None = None) -> list[dict]:
        if demo is None:
            rows = await self.db.fetchall("SELECT * FROM mod_actions WHERE status = 'pending' ORDER BY ts")
        else:
            rows = await self.db.fetchall("SELECT * FROM mod_actions WHERE status = 'pending' AND demo = ? ORDER BY ts", (int(demo),))
        return [self._action(r) for r in rows]

    async def pending_for_author(self, platform: str, author_id: str) -> dict | None:
        return self._action(await self.db.fetchone(
            "SELECT * FROM mod_actions WHERE status = 'pending' AND platform = ? AND author_id = ? "
            "AND action IN ('timeout', 'ban') ORDER BY ts DESC LIMIT 1", (platform, author_id)))

    async def action_history(self, limit: int = 100, status: str | None = None, demo: bool | None = None) -> list[dict]:
        where, params = [], []
        if status:
            where.append("status = ?"); params.append(status)
        if demo is not None:
            where.append("demo = ?"); params.append(int(demo))
        sql = "SELECT * FROM mod_actions" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY ts DESC LIMIT ?"
        return [self._action(r) for r in await self.db.fetchall(sql, (*params, limit))]

    async def flagged_actions(self, limit: int = 200, demo: bool | None = None) -> list[dict]:
        """Every message the rules flagged or acted on: flag-only records AND blocked ones (pending or resolved).
        This is the single source for the Flagged view, so it can never disagree with Waiting for you."""
        sql = "SELECT * FROM mod_actions WHERE status <> 'rejected'" + (" AND demo = ?" if demo is not None else "") + " ORDER BY ts DESC LIMIT ?"
        params = ((int(demo),) if demo is not None else ()) + (limit,)
        return [self._action(r) for r in await self.db.fetchall(sql, params)]

    async def actions_since(self, since: float) -> list[dict]:
        return [self._action(r) for r in await self.db.fetchall("SELECT * FROM mod_actions WHERE ts >= ? ORDER BY ts", (since,))]

    async def update_action(self, id_: int, **fields: Any) -> bool:
        if "message_ids" in fields:
            fields["message_ids"] = json.dumps(fields["message_ids"])
        if "reasons" in fields:
            fields["reasons"] = json.dumps(fields["reasons"])
        return await self._update("mod_actions", id_, ("message_ids", "score", "reasons", "status", "error", "resolved_ts", "duration", "action"), fields)

    async def expire_pending(self, before: float) -> int:
        return await self.db.execute(
            "UPDATE mod_actions SET status = 'expired', resolved_ts = ? WHERE status = 'pending' AND ts < ?", (time.time(), before))

    # ------------------------------------------------------------------ notifications (system events, separate from moderation)
    async def add_notification(self, kind: str, title: str, body: str = "", level: str = "info", demo: bool = False, ts: float | None = None) -> int:
        return await self.db.insert(
            "INSERT INTO notifications (ts, kind, level, title, body, demo, read) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (ts if ts is not None else time.time(), kind, level, title[:200], body[:500], int(demo)))

    async def list_notifications(self, limit: int = 100, demo: bool | None = None, unread_only: bool = False) -> list[dict]:
        where, params = [], []
        if demo is not None:
            where.append("demo = ?"); params.append(int(demo))
        if unread_only:
            where.append("read = 0")
        sql = "SELECT * FROM notifications" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY ts DESC, id DESC LIMIT ?"
        rows = await self.db.fetchall(sql, (*params, limit))
        for r in rows:
            r["read"], r["demo"] = bool(r["read"]), bool(r["demo"])
        return rows

    async def unread_notifications(self, demo: bool | None = None) -> int:
        sql, params = "SELECT COUNT(*) AS n FROM notifications WHERE read = 0", ()
        if demo is not None:
            sql, params = sql + " AND demo = ?", (int(demo),)
        r = await self.db.fetchone(sql, params)
        return int(r["n"]) if r else 0

    async def mark_notifications_read(self, ids: list[int] | None = None, demo: bool | None = None) -> int:
        if ids:
            marks = ", ".join("?" for _ in ids)
            return await self.db.execute(f"UPDATE notifications SET read = 1 WHERE id IN ({marks})", [int(i) for i in ids])
        if demo is None:
            return await self.db.execute("UPDATE notifications SET read = 1 WHERE read = 0")
        return await self.db.execute("UPDATE notifications SET read = 1 WHERE read = 0 AND demo = ?", (int(demo),))

    async def clear_notifications(self, demo: bool | None = None) -> int:
        if demo is None:
            return await self.db.execute("DELETE FROM notifications")
        return await self.db.execute("DELETE FROM notifications WHERE demo = ?", (int(demo),))

    # ------------------------------------------------------------------ auto replies (foundation: stored and validated, not yet executed by the bot)
    AR_MATCH_TYPES = ("phrase", "word", "contains")

    @staticmethod
    def _ar(r: dict | None) -> dict | None:
        if r:
            r["triggers"] = json.loads(r["triggers"] or "[]")
            r["responses"] = json.loads(r["responses"] or "[]")
            r["enabled"], r["case_sensitive"] = bool(r["enabled"]), bool(r["case_sensitive"])
        return r

    @staticmethod
    def _clean_list(values: list[str], limit: int, each: int) -> list[str]:
        out: list[str] = []
        for v in values or []:
            v = str(v).strip()
            if v and v not in out:
                out.append(v[:each])
        return out[:limit]

    async def list_auto_replies(self) -> list[dict]:
        return [self._ar(r) for r in await self.db.fetchall("SELECT * FROM auto_replies ORDER BY priority, name")]

    async def create_auto_reply(self, name: str, triggers: list[str], responses: list[str], match_type: str = "phrase",
                                case_sensitive: bool = False, category: str = "general", priority: int = 100, enabled: bool = False) -> int:
        triggers, responses = self._clean_list(triggers, 20, 200), self._clean_list(responses, 10, 500)
        if not (name or "").strip():
            raise ValidationFailed("Give the rule a name.")
        if not triggers:
            raise ValidationFailed("Add at least one trigger.")
        if not responses:
            raise ValidationFailed("Add at least one reply.")
        if match_type not in self.AR_MATCH_TYPES:
            raise ValidationFailed(f"Match type must be one of {', '.join(self.AR_MATCH_TYPES)}.")
        wanted = {t if case_sensitive else t.lower() for t in triggers}
        for other in await self.list_auto_replies():
            clash = wanted & {t if other["case_sensitive"] else t.lower() for t in other["triggers"]}
            if clash and other["match_type"] == match_type:
                raise ValidationFailed(f'"{sorted(clash)[0]}" is already a trigger in "{other["name"]}".')
        return await self.db.insert(
            "INSERT INTO auto_replies (name, triggers, responses, match_type, case_sensitive, category, priority, enabled, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name.strip()[:80], json.dumps(triggers), json.dumps(responses), match_type, int(case_sensitive), (category or "general").strip()[:40], priority, int(enabled), time.time()))

    async def update_auto_reply(self, id_: int, **fields: Any) -> bool:
        for k in ("triggers", "responses"):
            if k in fields:
                fields[k] = json.dumps(self._clean_list(fields[k], 20 if k == "triggers" else 10, 200 if k == "triggers" else 500))
        for k in ("enabled", "case_sensitive"):
            if k in fields:
                fields[k] = int(bool(fields[k]))
        if "match_type" in fields and fields["match_type"] not in self.AR_MATCH_TYPES:
            raise ValidationFailed(f"Match type must be one of {', '.join(self.AR_MATCH_TYPES)}.")
        return await self._update("auto_replies", id_, ("name", "triggers", "responses", "match_type", "case_sensitive", "category", "priority", "enabled"), fields)

    async def delete_auto_reply(self, id_: int) -> bool:
        return await self._delete("auto_replies", id_)

    # ------------------------------------------------------------------ counters, quota, retention
    async def counter_add(self, name: str, by: int = 1) -> int:
        await self.db.execute(
            "INSERT INTO counters (name, value) VALUES (?, ?) ON CONFLICT (name) DO UPDATE SET value = counters.value + excluded.value",
            (name, by))
        return await self.counter_get(name)

    async def counter_get(self, name: str) -> int:
        r = await self.db.fetchone("SELECT value FROM counters WHERE name = ?", (name,))
        return int(r["value"]) if r else 0

    async def quota_add(self, day: str, units: int) -> int:
        await self.db.execute(
            "INSERT INTO quota_usage (day, units) VALUES (?, ?) ON CONFLICT (day) DO UPDATE SET units = quota_usage.units + excluded.units",
            (day, units))
        return await self.quota_get(day)

    async def quota_get(self, day: str) -> int:
        r = await self.db.fetchone("SELECT units FROM quota_usage WHERE day = ?", (day,))
        return int(r["units"]) if r else 0

    async def purge(self, chat_before: float, actions_before: float) -> None:
        await self.db.execute("DELETE FROM chat_messages WHERE ts < ?", (chat_before,))
        await self.db.execute("DELETE FROM mod_actions WHERE ts < ? AND status <> 'pending'", (actions_before,))
        await self.db.execute("DELETE FROM reminders WHERE status <> 'pending' AND created < ?", (actions_before,))
        await self.db.execute("DELETE FROM notifications WHERE ts < ?", (actions_before,))
        await self.db.execute("DELETE FROM timer_runs WHERE ts < ?", (actions_before,))
