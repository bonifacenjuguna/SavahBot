"""What goes into a backup, how it is zipped, and how it is applied safely.

Never exported, whatever you tick: sign-in sessions and tickets, activity logs, push-notification device tokens, the server's
signing secret and every environment variable. Demo-mode sample rows (the `demo` flag) are never exported and never imported. Sign-in methods and tokens are only included when you tick "credentials"."""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
import zipfile
from typing import Any

from .container import BackupError

SCOPES: dict[str, dict[str, Any]] = {
    "settings": {"label": "Settings you changed in the dashboard", "default": True, "tables": ["settings"], "kv": []},
    "commands": {"label": "Commands, timers, auto replies, reminders and your variables", "default": True, "tables": ["commands", "timers", "triggers", "reminders", "custom_vars"], "kv": ["seeded"]},
    "community": {"label": "Quotes, regulars, blacklist and notebook", "default": True, "tables": ["quotes", "regulars", "blacklist", "notes"], "kv": []},
    "knowledge": {"label": "Knowledge packs, your phrases and everything learned", "default": True,
                  "tables": ["knowledge_packs", "knowledge_entries", "knowledge_feeds", "knowledge_suggestions", "knowledge_log", "intel_examples", "intel_packs",
                             "intel_user", "learning_lessons", "learning_snapshots"], "kv": ["intel_custom_feeds", "intel_scale", "intel_backfilled", "lessons_migrated"]},
    "moderation": {"label": "Moderation history and the ban ledger", "default": True, "tables": ["mod_actions", "bans"], "kv": []},
    "history": {"label": "Long-term chart history (daily and hourly totals)", "default": True, "tables": ["stats_hourly", "stats_daily", "stream_sessions"], "kv": ["history_rolled_until"]},
    "chat": {"label": "Raw chat messages (large)", "default": False, "tables": ["chat_messages"], "kv": []},
    "credentials": {"label": "Sign-in methods and connections (password, passkeys, authenticator, Google and Telegram links)", "default": False,
                    "tables": ["access_passkeys", "access_recovery", "access_totp"],
                    "kv": ["_owner_password_hash", "_owner_password_user_set", "telegram_owner_id", "youtube_refresh_token"]},
}
SECRETISH = re.compile(r"(secret|token|password|api_key|webhook_url)", re.I)
NAME_OK = re.compile(r"^(manifest\.json|data/[a-z_]+\.json)$")
MAX_FILE, MAX_TOTAL, MAX_RATIO, MAX_FILES = 300 * 1024 * 1024, 400 * 1024 * 1024, 250, 20


async def _columns(db: Any, table: str) -> list[str]:
    if db.backend == "sqlite":
        return [r["name"] for r in await db.fetchall(f"PRAGMA table_info({table})")]
    return [r["column_name"] for r in await db.fetchall("SELECT column_name FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position", (table,))]


async def _exists(db: Any, table: str) -> bool:
    return bool(await _columns(db, table))


async def _has_demo(db: Any, table: str) -> bool:
    """Tables that mix real rows with Demo-mode sample rows carry a `demo` column."""
    return "demo" in await _columns(db, table)


async def dump_scope(c: Any, scope: str) -> dict[str, Any]:
    """Demo-mode sample rows are never exported: the dashboard ships its own demo data, so a backup of it would only duplicate that."""
    db, spec = c.db, SCOPES[scope]
    out: dict[str, Any] = {"tables": {}, "kv": {}}
    for t in spec["tables"]:
        if not await _exists(db, t):
            continue
        rows = await db.fetchall(f"SELECT * FROM {t} WHERE demo = 0" if await _has_demo(db, t) else f"SELECT * FROM {t}")
        cols = list(rows[0].keys()) if rows else await _columns(db, t)
        if scope == "settings":
            rows = [r for r in rows if not SECRETISH.search(r["key"])]
        out["tables"][t] = {"columns": cols, "rows": [[r[k] for k in cols] for r in rows]}
    for k in spec["kv"]:
        v = await db.kv_get(k)
        if v not in (None, ""):
            out["kv"][k] = v
    if scope == "credentials":
        sec = await db.fetchall("SELECT key, value, updated FROM settings")
        out["tables"]["settings_secret"] = {"columns": ["key", "value", "updated"], "rows": [[r["key"], r["value"], r["updated"]] for r in sec if SECRETISH.search(r["key"])]}
        t = out["tables"].get("access_totp")
        if t and t["rows"]:   # the authenticator secret is stored encrypted with this server's key; inside the encrypted backup it travels as plain text
            from ..access import totp
            i = t["columns"].index("secret")
            t["rows"] = [[*r[:i], totp.unseal(c.access._secret, r[i]), *r[i + 1:]] for r in t["rows"]]
    return out


def build_zip(parts: dict[str, dict[str, Any]], app_version: str) -> bytes:
    buf = io.BytesIO()
    files: dict[str, bytes] = {f"data/{s}.json": json.dumps(d, separators=(",", ":"), default=str).encode() for s, d in parts.items()}
    manifest = {"format": "savahbot-backup", "version": 1, "app_version": app_version, "created": int(time.time()),
                "scopes": {s: {"tables": {t: len(v["rows"]) for t, v in d["tables"].items()}, "kv": sorted(d["kv"])} for s, d in parts.items()},
                "sha256": {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
        for n, b in files.items():
            z.writestr(n, b)
    return buf.getvalue()


def read_zip(blob: bytes) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Open the zip with every protection against hostile archives, check each file's checksum, and return (manifest, scope data)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise BackupError("The backup's contents are damaged.") from exc
    infos = z.infolist()
    if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_TOTAL:
        raise BackupError("The backup is larger than the safety limit.")
    for i in infos:
        if not NAME_OK.match(i.filename) or i.is_dir() or i.flag_bits & 0x1:
            raise BackupError("The backup contains something unexpected, so it was refused.")
        if i.file_size > MAX_FILE or (i.compress_size and i.file_size / i.compress_size > MAX_RATIO and i.file_size > 5_000_000):
            raise BackupError("The backup looks like a decompression bomb, so it was refused.")

    def read(name: str) -> bytes:
        with z.open(name) as f:
            data = f.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise BackupError("The backup is larger than the safety limit.")
        return data
    try:
        manifest = json.loads(read("manifest.json"))
        if manifest.get("format") != "savahbot-backup" or manifest.get("version") != 1:
            raise BackupError("That is not a SavahBot backup, or it is from a newer version.")
        parts: dict[str, dict[str, Any]] = {}
        for scope in manifest["scopes"]:
            name = f"data/{scope}.json"
            b = read(name)
            if hashlib.sha256(b).hexdigest() != manifest["sha256"].get(name) or scope not in SCOPES:
                raise BackupError("A file inside the backup does not match its checksum.")
            parts[scope] = json.loads(b)
    except BackupError:
        raise
    except (KeyError, ValueError) as exc:
        raise BackupError("The backup's contents are damaged.") from exc
    return manifest, parts


# ---------------------------------------------------------------------------------------------- applying
CHUNK = 400
_INT = {"integer", "bigint", "smallint"}
_FLT = {"double precision", "real", "numeric"}
_TXT = {"text", "character varying", "character"}


def _to_int(v: Any) -> Any:
    if v is None or isinstance(v, int):
        return None if v is None else int(v)
    if isinstance(v, float):
        return int(round(v))
    s = str(v).strip()
    try:
        return int(s)
    except ValueError:
        return int(round(float(s)))


def _to_text(v: Any) -> Any:
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return str(v)


def _converter(typ: str) -> Any:
    """Postgres is strict about column types (a whole number for a decimal column, text for a number), and a backup made on SQLite can hold either.
    Each value is brought to the type of the column it is going into. SQLite takes anything, so it needs no conversion."""
    if typ in _INT:
        return _to_int
    if typ in _FLT:
        return lambda v: None if v is None else float(v)
    if typ == "boolean":
        return lambda v: None if v is None else (v.strip().lower() in ("1", "true", "t", "yes") if isinstance(v, str) else bool(v))
    if typ in _TXT:
        return _to_text
    return lambda v: v


async def _types(db: Any, table: str) -> dict[str, str]:
    if db.backend == "sqlite":
        return {}
    return {r["column_name"]: r["data_type"] for r in await db.fetchall("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ?", (table,))}


async def _count(db: Any, table: str) -> int:
    return int((await db.fetchone(f"SELECT COUNT(*) AS n FROM {table}"))["n"])


async def write_rows(db: Any, table: str, cols: list[str], rows: list[list[Any]], *, keep_id: bool, strict: bool,
                     tick: Any = None, cancel: Any = None) -> dict[str, Any]:
    """Write rows in batches of CHUNK (far faster than one by one). A row that already exists is left alone.
    strict (replace, undo): any problem stops everything. Otherwise (merge) a batch with a bad row is retried row by row, so one bad row is counted
    and reported instead of silently losing its neighbours or stopping the restore."""
    out: dict[str, Any] = {"added": 0, "failed": 0, "error": ""}
    if not rows:
        return out
    keep = [i for i, c in enumerate(cols) if keep_id or c != "id"]
    names = [cols[i] for i in keep]
    types = await _types(db, table)
    conv = [_converter(types.get(n, "")) for n in names]
    sql = f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)}) ON CONFLICT DO NOTHING"
    prep = lambda r: [f(r[i]) for f, i in zip(conv, keep)]
    before = await _count(db, table)
    for n in range(0, len(rows), CHUNK):
        if cancel and cancel():
            raise BackupError("Restore cancelled.")
        chunk = rows[n:n + CHUNK]
        try:
            await db.executemany(sql, [prep(r) for r in chunk])
        except Exception:
            if strict:
                raise
            for r in chunk:
                try:
                    await db.execute(sql, prep(r))
                except Exception as exc:
                    out["failed"] += 1
                    out["error"] = out["error"] or f"{table}: {str(exc)[:160]}"
        if tick:
            tick(len(chunk))
    out["added"] = max(0, await _count(db, table) - before)
    return out


async def snapshot_tables(c: Any, tables: list[str], kv: list[str]) -> dict[str, Any]:
    snap: dict[str, Any] = {"tables": {}, "kv": {}}
    for t in tables:
        if await _exists(c.db, t):
            rows = await c.db.fetchall(f"SELECT * FROM {t}")
            cols = list(rows[0].keys()) if rows else await _columns(c.db, t)
            snap["tables"][t] = {"columns": cols, "rows": [[r[k] for k in cols] for r in rows]}
    for k in kv:
        snap["kv"][k] = await c.db.kv_get(k)
    return snap


async def restore_snapshot(c: Any, snap: dict[str, Any]) -> None:
    for t, d in snap["tables"].items():
        await c.db.execute(f"DELETE FROM {t}")
        have = set(await _columns(c.db, t))
        idx = [i for i, k in enumerate(d["columns"]) if k in have]
        await write_rows(c.db, t, [d["columns"][i] for i in idx], [[r[i] for i in idx] for r in d["rows"]], keep_id=True, strict=True)
    for k, v in snap["kv"].items():
        await c.db.kv_set(k, v or "")
    await _fix_sequences(c, list(snap["tables"]))


async def _fix_sequences(c: Any, tables: list[str]) -> None:
    """After rows are written with their own ids (Postgres only), move each table's counter past the highest id so new rows do not collide.
    1.4.3: tables whose id is text (knowledge_packs, knowledge_feeds, intel_packs, stream_sessions) have no counter. The old code asked for MAX(id) of
    those and Postgres refused, which failed every restore that included Knowledge or History, and the rollback then failed the same way."""
    if c.db.backend == "sqlite":
        return
    for t in tables:
        if "id" not in await _columns(c.db, t):
            continue
        seq = await c.db.fetchone("SELECT pg_get_serial_sequence(?, 'id') AS seq", (t,))
        if not seq or not seq["seq"]:
            continue
        await c.db.execute(f"SELECT setval(?::text::regclass, COALESCE((SELECT MAX(id) FROM {t}), 1))", (seq["seq"],))


async def apply_scope(c: Any, scope: str, data: dict[str, Any], mode: str, tick: Any = None, cancel: Any = None) -> dict[str, Any]:
    """Apply one scope. replace = the backup's rows become the only rows. merge = add what is missing, keep everything else.
    `tick(n)` is told how many of the backup's rows have been dealt with, so the screen can show real progress; `cancel()` says whether to stop."""
    db, report = c.db, {"added": 0, "skipped": 0, "demo_skipped": 0, "failed": 0, "error": ""}
    for t, d in data["tables"].items():
        raw = len(d["rows"])
        dealt = 0

        def step(n: int) -> None:
            nonlocal dealt
            dealt += n
            if tick:
                tick(n)
        target = "settings" if t == "settings_secret" else t
        if not await _exists(db, target):
            step(raw)
            continue
        have = set(await _columns(db, target))
        cols = [k for k in d["columns"] if k in have]
        idx = [d["columns"].index(k) for k in cols]
        rows = [[r[i] for i in idx] for r in d["rows"]]
        demo_table = "demo" in have
        if demo_table and "demo" in d["columns"]:     # an older backup may hold Demo-mode sample rows: they are left out, never imported
            di = cols.index("demo")
            kept = [r for r in rows if not int(r[di] or 0)]
            report["demo_skipped"] += len(rows) - len(kept)
            rows = kept
        if scope == "credentials" and t == "access_totp":
            from ..access import totp
            si = cols.index("secret")
            rows = [[*r[:si], totp.seal(c.access._secret, r[si]), *r[si + 1:]] for r in rows]
        if mode == "replace":
            if target == "settings":     # settings and secret overrides share a table but belong to different scopes
                for r in await db.fetchall("SELECT key FROM settings"):
                    if bool(SECRETISH.search(r["key"])) == (t == "settings_secret"):
                        await db.execute("DELETE FROM settings WHERE key = ?", (r["key"],))
            elif demo_table:             # replace only swaps the real rows; the Demo sample rows are not part of any backup
                await db.execute(f"DELETE FROM {target} WHERE demo = 0")
            else:
                await db.execute(f"DELETE FROM {target}")
        if mode == "merge" or t == "settings_secret":
            noid = [k for k in cols if k != "id"]
            existing = {tuple(str(r[k]) for k in noid) for r in await db.fetchall(f"SELECT {', '.join(noid)} FROM {target}")} if noid else set()
            if existing:
                fresh = [r for r in rows if tuple(str(v) for k, v in zip(cols, r) if k != "id") not in existing]
                report["skipped"] += len(rows) - len(fresh)
                step(len(rows) - len(fresh))
                rows = fresh
        got = await write_rows(db, target, cols, rows, keep_id=(mode == "replace"), strict=(mode == "replace"), tick=step, cancel=cancel)
        report["added"] += got["added"]
        report["failed"] += got["failed"]
        report["skipped"] += max(0, len(rows) - got["added"] - got["failed"])    # a unique name that already exists (for example a command): the existing one wins in merge mode
        report["error"] = report["error"] or got["error"]
        await _fix_sequences(c, [target])
        if tick and dealt < raw:
            tick(raw - dealt)
    for k, v in data["kv"].items():
        if mode == "replace" or not await db.kv_get(k):
            await db.kv_set(k, str(v))
    return report
