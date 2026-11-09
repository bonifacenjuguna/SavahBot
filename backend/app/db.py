"""Database layer: one small interface, two backends.

  * SQLite  - local development and the test-suite (standard library, fully tested)
  * PostgreSQL via asyncpg - Railway production (set DATABASE_URL)

All timestamps are stored as unix seconds (double precision) and booleans as 0/1, so the exact same SQL
runs on both. SQL is written with '?' placeholders; the PostgreSQL adapter rewrites them to $1, $2...
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger("savahbot.db")

# {PK} -> auto-increment primary key, {REAL} -> 8-byte float, per backend.
SCHEMA: list[str] = [
    "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated {REAL} NOT NULL)",
    """CREATE TABLE IF NOT EXISTS commands (
        id {PK}, name TEXT NOT NULL UNIQUE, response TEXT NOT NULL, userlevel TEXT NOT NULL DEFAULT 'everyone',
        cooldown INTEGER NOT NULL DEFAULT 5, user_cooldown INTEGER NOT NULL DEFAULT 10,
        enabled INTEGER NOT NULL DEFAULT 1, aliases TEXT NOT NULL DEFAULT '', uses INTEGER NOT NULL DEFAULT 0,
        created {REAL} NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS timers (
        id {PK}, name TEXT NOT NULL UNIQUE, message TEXT NOT NULL, interval_seconds INTEGER NOT NULL,
        min_lines INTEGER NOT NULL DEFAULT 5, enabled INTEGER NOT NULL DEFAULT 1,
        last_fired {REAL} NOT NULL DEFAULT 0, fired INTEGER NOT NULL DEFAULT 0, created {REAL} NOT NULL,
        match_mode TEXT NOT NULL DEFAULT 'all', max_runs INTEGER NOT NULL DEFAULT 0, runs INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS triggers (
        id {PK}, phrase TEXT NOT NULL, match_type TEXT NOT NULL DEFAULT 'exact', response TEXT NOT NULL,
        mention INTEGER NOT NULL DEFAULT 1, userlevel TEXT NOT NULL DEFAULT 'everyone',
        cooldown INTEGER NOT NULL DEFAULT 30, user_cooldown INTEGER NOT NULL DEFAULT 60,
        enabled INTEGER NOT NULL DEFAULT 1, hits INTEGER NOT NULL DEFAULT 0, created {REAL} NOT NULL)""",
    "CREATE TABLE IF NOT EXISTS quotes (id {PK}, body TEXT NOT NULL, author TEXT NOT NULL DEFAULT '', created {REAL} NOT NULL)",
    "CREATE TABLE IF NOT EXISTS regulars (id {PK}, ident TEXT NOT NULL UNIQUE, label TEXT NOT NULL, created {REAL} NOT NULL)",
    """CREATE TABLE IF NOT EXISTS blacklist (
        id {PK}, phrase TEXT NOT NULL UNIQUE, is_regex INTEGER NOT NULL DEFAULT 0, weight INTEGER NOT NULL DEFAULT 0,
        enabled INTEGER NOT NULL DEFAULT 1, hits INTEGER NOT NULL DEFAULT 0, created {REAL} NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS notes (
        id {PK}, body TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '', pinned INTEGER NOT NULL DEFAULT 0,
        created {REAL} NOT NULL, updated {REAL} NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS reminders (
        id {PK}, body TEXT NOT NULL, due {REAL} NOT NULL, repeat_kind TEXT NOT NULL DEFAULT 'none',
        interval_seconds INTEGER, status TEXT NOT NULL DEFAULT 'pending', created {REAL} NOT NULL,
        fired_at {REAL})""",
    """CREATE TABLE IF NOT EXISTS chat_messages (
        id {PK}, platform TEXT NOT NULL, msg_id TEXT NOT NULL DEFAULT '', author_id TEXT NOT NULL,
        author_name TEXT NOT NULL, body TEXT NOT NULL, level TEXT NOT NULL DEFAULT 'everyone', ts {REAL} NOT NULL,
        score INTEGER NOT NULL DEFAULT 0, verdict TEXT NOT NULL DEFAULT 'allow', demo INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS mod_actions (
        id {PK}, ts {REAL} NOT NULL, platform TEXT NOT NULL, author_id TEXT NOT NULL, author_name TEXT NOT NULL,
        message_ids TEXT NOT NULL DEFAULT '[]', body TEXT NOT NULL DEFAULT '', action TEXT NOT NULL,
        duration INTEGER, score INTEGER NOT NULL DEFAULT 0, reasons TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'suggest', error TEXT NOT NULL DEFAULT '',
        resolved_ts {REAL}, demo INTEGER NOT NULL DEFAULT 0)""",
    "CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS quota_usage (day TEXT PRIMARY KEY, units INTEGER NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_chat_ts ON chat_messages (ts)",
    "CREATE INDEX IF NOT EXISTS idx_actions_status ON mod_actions (status, ts)",
    "CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders (status, due)",
    # 1.1.6 Knowledge (packs, feeds, suggestions, change log)
    "CREATE TABLE IF NOT EXISTS knowledge_packs (id TEXT PRIMARY KEY, mode TEXT NOT NULL DEFAULT '', scale {REAL} NOT NULL DEFAULT 1, updated {REAL})",
    """CREATE TABLE IF NOT EXISTS knowledge_entries (id {PK}, pack_id TEXT NOT NULL, phrase TEXT NOT NULL,
        is_regex INTEGER NOT NULL DEFAULT 0, weight INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
        source TEXT NOT NULL DEFAULT 'user', gen INTEGER NOT NULL DEFAULT 0, created {REAL},
        UNIQUE (pack_id, phrase, source, gen))""",
    "CREATE INDEX IF NOT EXISTS idx_kentries_pack ON knowledge_entries (pack_id)",
    """CREATE TABLE IF NOT EXISTS knowledge_feeds (id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1,
        gen INTEGER NOT NULL DEFAULT 0, last_run {REAL}, last_ok {REAL}, status TEXT NOT NULL DEFAULT '',
        entries INTEGER NOT NULL DEFAULT 0, prev_entries INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
        etag TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS knowledge_suggestions (id {PK}, kind TEXT NOT NULL, pack_id TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', weight INTEGER NOT NULL DEFAULT 0,
        evidence INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'new', created {REAL})""",
    """CREATE TABLE IF NOT EXISTS knowledge_log (id {PK}, ts {REAL} NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL,
        undo TEXT NOT NULL DEFAULT '', undone INTEGER NOT NULL DEFAULT 0)""",
    # Legacy 1.1.9 tables, kept so existing data survives the move to the 1.1.6 Knowledge engine (migrated, never deleted)
    # (1.1.9) what the bot learned, what its shadow detectors saw, and your pack choices
    """CREATE TABLE IF NOT EXISTS intel_examples (
        id {PK}, ts {REAL} NOT NULL, label TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'teach', body TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '', pred {REAL}, weight {REAL} NOT NULL DEFAULT 1, demo INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS intel_shadow (
        id {PK}, ts {REAL} NOT NULL, platform TEXT NOT NULL DEFAULT '', author_id TEXT NOT NULL DEFAULT '',
        author_name TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '', detector TEXT NOT NULL, signal TEXT NOT NULL,
        weight INTEGER NOT NULL, detail TEXT NOT NULL DEFAULT '', would TEXT NOT NULL DEFAULT 'allow',
        actual TEXT NOT NULL DEFAULT 'allow', label TEXT NOT NULL DEFAULT '', demo INTEGER NOT NULL DEFAULT 0)""",
    "CREATE TABLE IF NOT EXISTS intel_packs (id TEXT PRIMARY KEY, enabled INTEGER NOT NULL)",
    """CREATE TABLE IF NOT EXISTS intel_user (
        id {PK}, pack TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL, weight INTEGER NOT NULL DEFAULT 0,
        created {REAL} NOT NULL, UNIQUE (pack, kind, value))""",
    "CREATE INDEX IF NOT EXISTS idx_intel_examples_ts ON intel_examples (ts)",
    "CREATE INDEX IF NOT EXISTS idx_intel_shadow_ts ON intel_shadow (ts)",
    "CREATE INDEX IF NOT EXISTS idx_intel_shadow_author ON intel_shadow (author_id, ts)",
]


# Columns added after 1.0: (table, column, definition). Existing databases get them on start-up.
MIGRATIONS: list[tuple[str, str, str]] = [
    ("timers", "match_mode", "TEXT NOT NULL DEFAULT 'all'"),
    ("timers", "max_runs", "INTEGER NOT NULL DEFAULT 0"),
    ("timers", "runs", "INTEGER NOT NULL DEFAULT 0"),
]


# 1.2.0: subsystems (security, notifications, weather, bans, stats...) keep their own tables next to their code and register them here.
# Statements use the same {PK}/{REAL} placeholders and must be idempotent (CREATE ... IF NOT EXISTS).
_EXTRA_SCHEMA: list[str] = []
_EXTRA_COLUMNS: list[tuple[str, str, str]] = []
# Data migrations that need Python (backfills, conversions). Each runs exactly once, in version order, and is recorded in kv "schema_version".
_STEPS: list[tuple[int, str, Any]] = []


def register_schema(statements: Sequence[str] = (), columns: Sequence[tuple[str, str, str]] = ()) -> None:
    """Add tables, indexes and added columns. Safe to call more than once with the same text."""
    for stmt in statements:
        if stmt not in _EXTRA_SCHEMA:
            _EXTRA_SCHEMA.append(stmt)
    for col in columns:
        if col not in _EXTRA_COLUMNS:
            _EXTRA_COLUMNS.append(col)


def register_step(version: int, name: str, fn: Any) -> None:
    """Register `async def fn(db)` to run once when the stored schema version is lower than `version`."""
    if not any(v == version for v, _, _ in _STEPS):
        _STEPS.append((version, name, fn))
        _STEPS.sort(key=lambda t: t[0])


def all_schema() -> list[str]:
    return [*SCHEMA, *_EXTRA_SCHEMA]


def schema_phases() -> tuple[list[str], list[str]]:
    """(tables, indexes). Indexes run LAST, after missing columns were added, so a table left over from an older
    build (without a column an index needs) is repaired instead of stopping the whole startup."""
    stmts = all_schema()
    return [x for x in stmts if "INDEX" not in x.lstrip()[:30].upper()], [x for x in stmts if "INDEX" in x.lstrip()[:30].upper()]


def all_columns() -> list[tuple[str, str, str]]:
    return [*MIGRATIONS, *_EXTRA_COLUMNS]


async def _index(impl: Any, stmt: str) -> None:
    """An index is an optimisation: if one cannot be built (odd leftover table), say so and carry on starting."""
    try:
        await impl.run(stmt, (), "exec")
    except Exception as exc:
        if "UNIQUE" in stmt.upper():
            raise
        logger.warning("Could not create index (%s): %s", stmt[:80], exc)


class _SQLite:
    backend = "sqlite"

    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._lock = threading.Lock()

    def _exec(self, sql: str, params: Sequence[Any], mode: str) -> Any:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            if mode == "all":
                return [dict(r) for r in cur.fetchall()]
            if mode == "one":
                r = cur.fetchone()
                return dict(r) if r else None
            if mode == "insert":
                return cur.lastrowid
            return cur.rowcount

    async def run(self, sql: str, params: Sequence[Any], mode: str) -> Any:
        return await asyncio.to_thread(self._exec, sql, params, mode)

    async def init_schema(self) -> None:
        tables, indexes = schema_phases()
        fix = lambda st: st.replace("{PK}", "INTEGER PRIMARY KEY AUTOINCREMENT").replace("{REAL}", "REAL")
        for stmt in tables:
            await self.run(fix(stmt), (), "exec")
        for table, column, definition in all_columns():
            have = {r["name"] for r in await self.run(f"PRAGMA table_info({table})", (), "all")}
            if have and column not in have:
                await self.run(f"ALTER TABLE {table} ADD COLUMN {column} {definition}", (), "exec")
        for stmt in indexes:
            await _index(self, fix(stmt))

    async def close(self) -> None:
        with self._lock:
            self._conn.close()


class _Postgres:
    backend = "postgres"

    def __init__(self, dsn: str, pool_size: int) -> None:
        self._dsn = dsn
        self._pool_size = pool_size
        self._pool: Any = None

    async def connect(self) -> None:
        import asyncpg  # imported lazily so SQLite-only setups do not need it

        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=max(1, self._pool_size))

    @staticmethod
    def _q(sql: str) -> str:
        out, n = [], 0
        for ch in sql:
            if ch == "?":
                n += 1
                out.append(f"${n}")
            else:
                out.append(ch)
        return "".join(out)

    async def run(self, sql: str, params: Sequence[Any], mode: str) -> Any:
        q = self._q(sql)
        async with self._pool.acquire() as conn:
            if mode == "all":
                return [dict(r) for r in await conn.fetch(q, *params)]
            if mode == "one":
                r = await conn.fetchrow(q, *params)
                return dict(r) if r else None
            if mode == "insert":
                return await conn.fetchval(q + " RETURNING id", *params)
            status = await conn.execute(q, *params)  # e.g. "UPDATE 3"
            try:
                return int(status.split()[-1])
            except (ValueError, IndexError):
                return 0

    async def init_schema(self) -> None:
        tables, indexes = schema_phases()
        fix = lambda st: st.replace("{PK}", "SERIAL PRIMARY KEY").replace("{REAL}", "DOUBLE PRECISION")
        for stmt in tables:
            await self.run(fix(stmt), (), "exec")
        for table, column, definition in all_columns():
            await self.run(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}", (), "exec")
        for stmt in indexes:
            await _index(self, fix(stmt))

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()


class Database:
    def __init__(self, url: str = "", pool_size: int = 5, echo: bool = False) -> None:
        self.echo = echo
        url = (url or "").strip()
        if url.startswith(("postgres://", "postgresql://")):
            self._impl: _SQLite | _Postgres = _Postgres(url, pool_size)
        else:
            path = url[len("sqlite:///"):] if url.startswith("sqlite:///") else (url or "savahbot.db")
            self._impl = _SQLite(path)

    @property
    def backend(self) -> str:
        return self._impl.backend

    async def connect(self) -> None:
        if isinstance(self._impl, _Postgres):
            await self._impl.connect()
        await self._impl.init_schema()
        await self._run_steps()
        logger.info("Database ready (%s, schema v%s)", self.backend, await self.schema_version())

    async def close(self) -> None:
        await self._impl.close()

    async def schema_version(self) -> int:
        try:
            return int(await self.kv_get("schema_version", "0") or 0)
        except ValueError:
            return 0

    async def _run_steps(self) -> None:
        """Run each pending data migration once. A failing step stops the chain (later steps may depend on it) and is logged, never silently skipped."""
        current = await self.schema_version()
        for version, name, fn in _STEPS:
            if version <= current:
                continue
            try:
                await fn(self)
            except Exception:
                logger.exception("Migration %s (%s) failed; the app keeps running on the previous schema version", version, name)
                return
            await self.kv_set("schema_version", str(version))
            logger.info("Applied migration %s: %s", version, name)

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        if self.echo:
            logger.debug("SQL %s %s", sql, params)
        return await self._impl.run(sql, params, "exec")

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        if self.echo:
            logger.debug("SQL %s %s", sql, params)
        return await self._impl.run(sql, params, "all")

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        if self.echo:
            logger.debug("SQL %s %s", sql, params)
        return await self._impl.run(sql, params, "one")

    async def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        if self.echo:
            logger.debug("SQL %s %s", sql, params)
        return int(await self._impl.run(sql, params, "insert"))

    # ---- key/value helpers -----------------------------------------------------------------
    async def kv_get(self, key: str, default: str | None = None) -> str | None:
        row = await self.fetchone("SELECT value FROM kv WHERE key = ?", (key,))
        return row["value"] if row else default

    async def kv_set(self, key: str, value: str) -> None:
        await self.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    async def kv_delete(self, key: str) -> None:
        await self.execute("DELETE FROM kv WHERE key = ?", (key,))
