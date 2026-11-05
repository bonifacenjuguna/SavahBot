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
        self._trigger_cache: list[dict] | None = None

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
        return r

    @staticmethod
    def _check_timer(interval_seconds: int, min_lines: int, match_mode: str, max_runs: int, message: str | None = None) -> None:
        """A timer needs a time, a number of chat lines, or both. A time is at least 60 seconds."""
        if interval_seconds < 0 or (0 < interval_seconds < 60):
            raise ValidationFailed("Interval must be at least 60 seconds, or 0 to post by chat lines only.")
        if interval_seconds > 86400:
            raise ValidationFailed("Interval can be at most 24 hours.")
        if min_lines < 0 or min_lines > 1000:
            raise ValidationFailed("Chat lines must be between 0 and 1000.")
        if interval_seconds == 0 and min_lines == 0:
            raise ValidationFailed("Set a time, a number of chat lines, or both.")
        if match_mode not in ("all", "any"):
            raise ValidationFailed("match_mode must be 'all' or 'any'.")
        if max_runs < 0 or max_runs > 1000:
            raise ValidationFailed("Number of posts must be between 0 (keep repeating) and 1000.")
        if message is not None and not message.strip():
            raise ValidationFailed("Message cannot be empty.")

    async def list_timers(self) -> list[dict]:
        return [self._timer(r) for r in await self.db.fetchall("SELECT * FROM timers ORDER BY name")]

    async def get_timer(self, id_: int) -> dict | None:
        return self._timer(await self.db.fetchone("SELECT * FROM timers WHERE id = ?", (id_,)))

    async def create_timer(self, name: str, message: str, interval_seconds: int = 0, min_lines: int = 0, enabled: bool = True,
                           match_mode: str = "all", max_runs: int = 0) -> int:
        name = clean_name(name, prefix="")
        min_lines = max(0, min_lines)
        self._check_timer(interval_seconds, min_lines, match_mode, max_runs, message)
        return await self.db.insert(
            "INSERT INTO timers (name, message, interval_seconds, min_lines, enabled, created, match_mode, max_runs) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, message.strip(), interval_seconds, min_lines, int(enabled), time.time(), match_mode, max_runs),
        )

    async def update_timer(self, id_: int, **fields: Any) -> bool:
        current = await self.get_timer(id_)
        if current is None:
            return False
        merged = current | fields
        self._check_timer(int(merged["interval_seconds"]), int(merged["min_lines"]), merged["match_mode"], int(merged["max_runs"]),
                          merged["message"] if "message" in fields else None)
        if "name" in fields:
            fields["name"] = clean_name(fields["name"], prefix="")
        if "message" in fields:
            fields["message"] = fields["message"].strip()
        if "enabled" in fields:
            fields["enabled"] = int(bool(fields["enabled"]))
            if fields["enabled"] and not current["enabled"]:
                fields["runs"] = 0  # a limited timer starts counting again each time it is switched on
        await self._update("timers", id_, ("name", "message", "interval_seconds", "min_lines", "enabled", "match_mode", "max_runs", "runs"), fields)
        return True

    async def delete_timer(self, id_: int) -> bool:
        return await self._delete("timers", id_)

    async def mark_timer_fired(self, id_: int, ts: float) -> None:
        await self.db.execute("UPDATE timers SET last_fired = ?, fired = fired + 1, runs = runs + 1 WHERE id = ?", (ts, id_))

    async def switch_off_timer(self, id_: int) -> None:
        await self.db.execute("UPDATE timers SET enabled = 0 WHERE id = ?", (id_,))

    # ------------------------------------------------------------------ auto-replies (triggers)
    TRIGGER_MATCHES = ("exact", "word")

    @staticmethod
    def phrase_key(text: str) -> str:
        """Case and spacing do not matter when comparing a viewer's message with a trigger phrase."""
        return " ".join((text or "").split()).casefold()

    @staticmethod
    def _trigger(r: dict | None) -> dict | None:
        if r:
            r["enabled"] = bool(r["enabled"])
            r["mention"] = bool(r["mention"])
        return r

    async def list_triggers(self) -> list[dict]:
        return [self._trigger(r) for r in await self.db.fetchall("SELECT * FROM triggers ORDER BY phrase")]

    async def get_trigger(self, id_: int) -> dict | None:
        return self._trigger(await self.db.fetchone("SELECT * FROM triggers WHERE id = ?", (id_,)))

    async def enabled_triggers(self) -> list[dict]:
        """Enabled triggers, longest phrase first, cached until a trigger is created, changed or deleted."""
        if self._trigger_cache is None:
            rows = [self._trigger(r) for r in await self.db.fetchall("SELECT * FROM triggers WHERE enabled = 1")]
            self._trigger_cache = sorted(rows, key=lambda r: -len(self.phrase_key(r["phrase"])))
        return self._trigger_cache

    async def _check_trigger(self, fields: dict[str, Any], ignore_id: int | None = None) -> None:
        if "phrase" in fields:
            if not self.phrase_key(fields["phrase"]):
                raise ValidationFailed("Phrase cannot be empty.")
            if len(fields["phrase"]) > 200:
                raise ValidationFailed("Phrase can be at most 200 characters.")
        if "response" in fields and not fields["response"].strip():
            raise ValidationFailed("Reply cannot be empty.")
        if "match_type" in fields and fields["match_type"] not in self.TRIGGER_MATCHES:
            raise ValidationFailed(f"Match must be one of {', '.join(self.TRIGGER_MATCHES)}.")
        if "userlevel" in fields:
            fields["userlevel"] = valid_level(fields["userlevel"])

    async def create_trigger(self, phrase: str, response: str, match_type: str = "exact", mention: bool = True, userlevel: str = "everyone",
                             cooldown: int = 30, user_cooldown: int = 60, enabled: bool = True) -> int:
        fields = {"phrase": phrase.strip(), "response": response.strip(), "match_type": match_type, "userlevel": userlevel}
        await self._check_trigger(fields)
        key = self.phrase_key(phrase)
        for t in await self.list_triggers():
            if self.phrase_key(t["phrase"]) == key and t["match_type"] == match_type:
                raise ValidationFailed("There is already an auto-reply for that phrase.")
        id_ = await self.db.insert(
            "INSERT INTO triggers (phrase, match_type, response, mention, userlevel, cooldown, user_cooldown, enabled, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fields["phrase"], match_type, fields["response"], int(mention), fields["userlevel"], max(0, cooldown), max(0, user_cooldown), int(enabled), time.time()))
        self._trigger_cache = None
        return id_

    async def update_trigger(self, id_: int, **fields: Any) -> bool:
        await self._check_trigger(fields)
        for k in ("enabled", "mention"):
            if k in fields:
                fields[k] = int(bool(fields[k]))
        if "phrase" in fields:
            fields["phrase"] = fields["phrase"].strip()
        if "response" in fields:
            fields["response"] = fields["response"].strip()
        ok = await self._update("triggers", id_, ("phrase", "match_type", "response", "mention", "userlevel", "cooldown", "user_cooldown", "enabled"), fields)
        self._trigger_cache = None
        return ok

    async def delete_trigger(self, id_: int) -> bool:
        ok = await self._delete("triggers", id_)
        self._trigger_cache = None
        return ok

    async def bump_trigger(self, id_: int) -> None:
        await self.db.execute("UPDATE triggers SET hits = hits + 1 WHERE id = ?", (id_,))

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

    async def add_blacklist(self, phrase: str, is_regex: bool = False, weight: int = 0, enabled: bool = True) -> int:
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
        if await self.db.fetchone("SELECT id FROM blacklist WHERE phrase = ?", (phrase,)):
            raise ValidationFailed("That phrase is already on the list.")
        return await self.db.insert(
            "INSERT INTO blacklist (phrase, is_regex, weight, enabled, created) VALUES (?, ?, ?, ?, ?)",
            (phrase, int(is_regex), weight, int(enabled), time.time()),
        )

    async def update_blacklist(self, id_: int, **fields: Any) -> bool:
        for k in ("enabled", "is_regex"):
            if k in fields:
                fields[k] = int(bool(fields[k]))
        return await self._update("blacklist", id_, ("phrase", "is_regex", "weight", "enabled"), fields)

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
            where.append("status = ?")
            params.append(status)
        if demo is not None:
            where.append("demo = ?")
            params.append(int(demo))
        sql = "SELECT * FROM mod_actions" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY ts DESC LIMIT ?"
        return [self._action(r) for r in await self.db.fetchall(sql, (*params, limit))]

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
