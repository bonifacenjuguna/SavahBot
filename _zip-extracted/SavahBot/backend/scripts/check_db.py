"""Verify the database connection and schema. Run after deploying, especially on Railway Postgres:

    railway run python scripts/check_db.py        (or: DATABASE_URL=... python scripts/check_db.py)

Creates the schema, then round-trips a row through every kind of value the bot stores
(text, integer, boolean, float timestamp, JSON text, upsert) and cleans up after itself.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.store import Store  # noqa: E402


async def main() -> int:
    s = Settings()
    db = Database(s.database_url, s.db_pool_size, False)
    step = "connect"
    try:
        await db.connect()
        print(f"[ok] connected ({db.backend})")
        store = Store(db)
        step = "kv upsert"
        await db.kv_set("check_db", "one")
        await db.kv_set("check_db", "two")
        assert await db.kv_get("check_db") == "two"
        print("[ok] key/value upsert")
        step = "command insert"
        cid = await store.create_command("zz_check_db", "ok $(user)", "everyone", 1, 1, True, [])
        row = await store.get_command(cid)
        assert row and row["enabled"] in (True, 1) and row["response"] == "ok $(user)"
        print("[ok] insert + read with generated id")
        step = "float timestamp"
        due = time.time() + 3600
        rid = await store.add_reminder("check_db", due, "none", None)
        got = next(r for r in await store.list_reminders("pending") if r["id"] == rid)
        assert abs(got["due"] - due) < 0.01, got
        print("[ok] float timestamps")
        step = "integer upsert"
        await db.execute("INSERT INTO quota_usage (day, units) VALUES (?, ?) ON CONFLICT (day) DO UPDATE SET units = excluded.units", ("check-db", 5))
        await db.execute("INSERT INTO quota_usage (day, units) VALUES (?, ?) ON CONFLICT (day) DO UPDATE SET units = excluded.units", ("check-db", 7))
        assert (await db.fetchone("SELECT units FROM quota_usage WHERE day = ?", ("check-db",)))["units"] == 7
        print("[ok] integer upsert")
        step = "cleanup"
        await store.delete_command(cid)
        await db.execute("DELETE FROM quota_usage WHERE day = ?", ("check-db",))
        await db.execute("DELETE FROM reminders WHERE id = ?", (rid,))
        await db.kv_delete("check_db")
        print("[ok] cleanup")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAILED] at step '{step}': {type(exc).__name__}: {exc}")
        return 1
    finally:
        await db.close()
    print("Database is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
