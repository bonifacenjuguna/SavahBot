"""1.2.0: subsystem schema registry and run-once data migrations."""
import asyncio

from app import db as D


def run(coro):
    return asyncio.run(coro)


def test_registered_schema_is_created_and_steps_run_once(monkeypatch):
    monkeypatch.setattr(D, "_EXTRA_SCHEMA", [])
    monkeypatch.setattr(D, "_STEPS", [])
    calls: list[str] = []

    async def step_a(db):
        calls.append("a")

    async def step_b(db):
        calls.append("b")

    D.register_schema(["CREATE TABLE IF NOT EXISTS t_reg (id {PK}, at {REAL} NOT NULL)"])
    D.register_step(2, "b", step_b)
    D.register_step(1, "a", step_a)

    async def main():
        db = D.Database(":memory:")
        await db.connect()
        assert await db.schema_version() == 2
        await db.connect()                      # a second start must not repeat the steps
        await db.insert("INSERT INTO t_reg (at) VALUES (?)", (1.0,))
        return await db.fetchall("SELECT * FROM t_reg")

    rows = run(main())
    assert calls == ["a", "b"] and len(rows) == 1


def test_failing_step_stops_the_chain_and_keeps_version(monkeypatch):
    monkeypatch.setattr(D, "_STEPS", [])
    seen: list[int] = []

    async def ok(db):
        seen.append(1)

    async def boom(db):
        raise RuntimeError("nope")

    async def after(db):
        seen.append(3)

    D.register_step(1, "ok", ok)
    D.register_step(2, "boom", boom)
    D.register_step(3, "after", after)

    async def main():
        db = D.Database(":memory:")
        await db.connect()
        return await db.schema_version()

    assert run(main()) == 1 and seen == [1]


def test_register_schema_is_idempotent(monkeypatch):
    monkeypatch.setattr(D, "_EXTRA_SCHEMA", [])
    D.register_schema(["CREATE TABLE IF NOT EXISTS t_i (id {PK})"])
    D.register_schema(["CREATE TABLE IF NOT EXISTS t_i (id {PK})"])
    assert len(D._EXTRA_SCHEMA) == 1
