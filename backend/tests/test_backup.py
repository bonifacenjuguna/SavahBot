"""Encrypted backup: the file format, hostile archives, and a full export / wipe / restore cycle over HTTP."""
import asyncio
import base64
import io
import json
import struct
import zipfile

import pytest

from app.backup import archive, container
from app.backup.container import BackupError
from test_api import PASSWORD, e2e


# ------------------------------------------------------------------ the file format
def test_seal_and_open_roundtrip_with_and_without_passphrase():
    key = container.new_key()
    plain = b"hello world " * 200_000                               # more than two chunks
    blob, fp = container.seal(plain, key)
    out, header = container.open_(blob, key)
    assert out == plain and header["fp"] == fp and not header["pass"]
    blob2, _ = container.seal(plain, key, "my passphrase")
    assert container.open_(blob2, key, "my passphrase")[0] == plain
    with pytest.raises(BackupError, match="passphrase"):
        container.open_(blob2, key)
    with pytest.raises(BackupError, match="does not match"):
        container.open_(blob2, key, "other")
    with pytest.raises(BackupError, match="does not match"):
        container.open_(blob, container.new_key())
    assert container.seal(plain[:100], key)[0] != container.seal(plain[:100], key)[0]   # fresh salt and nonces every time


def test_key_format_has_a_checksum_and_never_appears_in_the_file():
    key = container.new_key()
    text = container.format_key(key)
    assert text.startswith("SVK1-") and container.parse_key(text) == key and container.parse_key(text.lower().replace("-", " ")) == key
    bad = text[:-1] + ("A" if text[-1] != "A" else "B")
    with pytest.raises(BackupError, match="typo"):
        container.parse_key(bad)
    with pytest.raises(BackupError):
        container.parse_key("nonsense!!")
    blob, _ = container.seal(b"secret data", key)
    assert key not in blob and b"secret data" not in blob


def test_any_tampering_is_detected():
    key = container.new_key()
    blob, _ = container.seal(b"A" * (container.CHUNK * 2 + 10), key)
    for name, bad in {
        "flipped byte": blob[:-5] + bytes([blob[-5] ^ 1]) + blob[-4:],
        "truncated": blob[:-100],
        "garbage": b"nothing",
        "empty": b"",
    }.items():
        with pytest.raises(BackupError):
            container.open_(bad, key)
    hdr, hb, pos = container.read_header(blob)
    # edit the header (for example to claim a different creation time) -> every chunk fails
    edited = blob.replace(hb, hb.replace(b'"v":1', b'"v":1 '), 1)
    with pytest.raises(BackupError):
        container.open_(edited, key)
    # drop the last chunk but keep the file well-formed -> the "last chunk" flag no longer matches
    chunks, p = [], pos
    while p < len(blob):
        (n,) = struct.unpack(">I", blob[p:p + 4])
        chunks.append(blob[p:p + 16 + n])
        p += 16 + n
    assert len(chunks) == 3
    with pytest.raises(BackupError):
        container.open_(blob[:pos] + b"".join(chunks[:2]), key)
    with pytest.raises(BackupError):
        container.open_(blob[:pos] + chunks[1] + chunks[0] + chunks[2], key)          # reordered


# ------------------------------------------------------------------ hostile zips
def make_zip(files, compress=zipfile.ZIP_DEFLATED):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", compress) as z:
        for n, d in files.items():
            z.writestr(n, d)
    return b.getvalue()


def test_zip_protections():
    good = archive.build_zip({"commands": {"tables": {"commands": {"columns": ["name"], "rows": [["a"]]}}, "kv": {}}}, "1.2.0")
    manifest, parts = archive.read_zip(good)
    assert parts["commands"]["tables"]["commands"]["rows"] == [["a"]]
    for evil in ("../evil.json", "/abs.json", "data/../../x.json", "other.txt", "data/Commands.json"):
        with pytest.raises(BackupError):
            archive.read_zip(make_zip({"manifest.json": "{}", evil: "x"}))
    with pytest.raises(BackupError):                               # a file that expands more than 250 times
        archive.read_zip(make_zip({"manifest.json": "{}", "data/settings.json": b"0" * 40_000_000}))
    with pytest.raises(BackupError):
        archive.read_zip(b"not a zip")
    # a file edited after the manifest was written fails its checksum
    z = zipfile.ZipFile(io.BytesIO(good))
    files = {n: z.read(n) for n in z.namelist()}
    files["data/commands.json"] = files["data/commands.json"].replace(b'"a"', b'"b"')
    with pytest.raises(BackupError, match="checksum"):
        archive.read_zip(make_zip(files))


# ------------------------------------------------------------------ whole cycle over HTTP
async def step_up(api):
    assert (await api.call("POST", "/api/security/step-up", {"method": "password", "code": PASSWORD}))[0] == 200


@e2e
async def test_export_wipe_restore_merge_dry_run_and_undo(api):
    await api.call("POST", "/api/commands", {"name": "!hello", "response": "hi there"})
    async def cmd_names():
        return {r["name"] for r in await api.c.db.fetchall("SELECT name FROM commands")}
    orig = await cmd_names()
    q_before = (await api.c.db.fetchone("SELECT COUNT(*) AS n FROM quotes"))["n"]
    await api.call("POST", "/api/quotes", {"body": "a quote worth keeping"})
    await api.c.db.execute("UPDATE access_sessions SET step_up_until = 0")
    st, b = await api.call("POST", "/api/backup/export", {"scopes": ["commands", "community"]})
    assert st == 403 and b["code"] == "step_up_required"               # exporting needs a fresh confirmation
    await step_up(api)
    assert (await api.call("POST", "/api/backup/export", {"scopes": []}))[0] == 400
    st, exp = await api.call("POST", "/api/backup/export", {"scopes": ["commands", "community", "history"]})
    assert st == 200 and exp["key"].startswith("SVK1-") and exp["filename"].endswith(".svbak") and len(exp["fingerprint"]) == 14
    # the key is not stored anywhere, and the file does not contain data in the clear
    blob = base64.b64decode(exp["data"])
    assert b"hi there" not in blob and exp["key"].encode() not in blob
    rows = await api.c.db.fetchall("SELECT key, value FROM kv")
    assert all(exp["key"] not in (r["value"] or "") for r in rows)
    body = {"data": exp["data"], "key": exp["key"]}
    # verify never changes anything, and a wrong key is refused
    st, v = await api.call("POST", "/api/backup/verify", body)
    assert st == 200 and v["fingerprint"] == exp["fingerprint"] and {s["id"] for s in v["scopes"]} == {"commands", "community", "history"}
    wrong = (await api.call("POST", "/api/backup/export", {"scopes": ["commands"]}))[1]
    assert (await api.call("POST", "/api/backup/verify", {"data": exp["data"], "key": wrong["key"]}))[0] == 400
    # change the world, then restore
    await api.c.db.execute("DELETE FROM commands")
    await api.c.db.execute("DELETE FROM quotes")
    await api.call("POST", "/api/commands", {"name": "!other", "response": "something new"})
    st, dry = await api.call("POST", "/api/backup/import", {**body, "mode": "replace", "dry_run": True})
    assert st == 200 and dry["dry_run"] and dry["plan"]["commands"]["commands"] == len(orig)
    assert await cmd_names() == {"other"}                                                             # dry run changed nothing
    st, done = await api.call("POST", "/api/backup/import", {**body, "mode": "merge", "scopes": ["commands"]})
    assert st == 200 and done["applied"]["commands"]["added"] >= 1
    assert await cmd_names() == orig | {"other"}                                                              # merge keeps what was there
    assert (await api.c.db.fetchone("SELECT COUNT(*) AS n FROM quotes"))["n"] == 0                    # quotes were not ticked
    st, done = await api.call("POST", "/api/backup/import", {**body, "mode": "replace"})
    assert st == 200 and done["can_undo"]
    assert await cmd_names() == orig and (await api.c.db.fetchone("SELECT COUNT(*) AS n FROM quotes"))["n"] == q_before + 1
    # undo puts the world back as it was just before that replace
    st, _ = await api.call("POST", "/api/backup/undo")
    assert st == 200 and "other" in {r["name"] for r in await api.c.db.fetchall("SELECT name FROM commands")}
    assert (await api.call("POST", "/api/backup/undo"))[0] == 400
    st, act = await api.call("GET", "/api/security/activity")
    assert any(a["action"] == "backup_exported" for a in act["audit"]) and any(a["action"] == "backup_imported" for a in act["audit"])


@e2e
async def test_failed_import_rolls_back_and_sessions_are_never_exported(api):
    await api.call("POST", "/api/commands", {"name": "!keep", "response": "stay"})
    await step_up(api)
    st, exp = await api.call("POST", "/api/backup/export", {"scopes": ["commands", "community", "credentials"], "passphrase": "pp pp pp"})
    assert st == 200 and exp["passphrase"]
    plain, _ = container.open_(base64.b64decode(exp["data"]), container.parse_key(exp["key"]), "pp pp pp")
    z = zipfile.ZipFile(io.BytesIO(plain))
    assert "access_sessions" not in b"".join(z.read(n) for n in z.namelist()).decode() and "sbs_" not in b"".join(z.read(n) for n in z.namelist()).decode()
    assert (await api.call("POST", "/api/backup/import", {"data": exp["data"], "key": exp["key"], "mode": "replace"}))[0] == 400     # passphrase needed
    real = archive.apply_scope
    calls = []

    async def flaky(c, scope, data, mode, tick=None, cancel=None):
        calls.append(scope)
        if len(calls) == 2:
            raise RuntimeError("disk on fire")
        return await real(c, scope, data, mode, tick, cancel)
    archive.apply_scope = flaky
    await api.c.db.execute("DELETE FROM commands")
    await api.call("POST", "/api/commands", {"name": "!before", "response": "x"})
    try:
        st, err = await api.call("POST", "/api/backup/import", {"data": exp["data"], "key": exp["key"], "passphrase": "pp pp pp", "mode": "replace"})
    finally:
        archive.apply_scope = real
    assert st == 400 and "put back" in err["error"]
    assert [r["name"] for r in await api.c.db.fetchall("SELECT name FROM commands")] == ["before"]


def test_first_run_restore_needs_the_one_time_token(tmp_path, caplog):
    from app.config import Settings
    from app.container import Container
    import logging

    async def go():
        c = Container(Settings(env={"DATABASE_URL": f"sqlite:///{tmp_path}/f.db", "OWNER_PASSWORD": PASSWORD, "BOT_MODE": "demo", "DEMO_AUTOSTART": "false"}, env_file=""))
        with caplog.at_level(logging.WARNING, logger="savahbot.backup"):
            await c.start()
        try:
            token = next(m.split("(shown once): ")[1].split()[0] for m in (r.getMessage() for r in caplog.records) if "one-time token" in m)
            assert await c.backup.fresh()
            with pytest.raises(BackupError):
                await c.backup.check_token("wrong", "1.1.1.1")
            await c.backup.check_token(token, "1.1.1.1")
            await c.access.new_session("1.1.1.1", "ua", ["password"])          # anyone signing in closes the window
            with pytest.raises(BackupError):
                await c.backup.check_token(token, "1.1.1.1")
        finally:
            await c.stop() if hasattr(c, "stop") else None
    asyncio.run(go())


@e2e
async def test_demo_rows_are_never_exported_or_imported(api):
    """The dashboard ships its own demo data, so Demo-mode sample rows stay out of backups in both directions."""
    db = api.c.db
    ins = "INSERT INTO chat_messages (platform, msg_id, author_id, author_name, body, ts, demo) VALUES ('youtube', ?, ?, ?, ?, 1000, ?)"
    await db.execute(ins, ("r1", "u1", "Real Person", "a real message", 0))
    await db.execute(ins, ("d1", "ud", "Demo Person", "a made up message", 1))
    await step_up(api)
    st, exp = await api.call("POST", "/api/backup/export", {"scopes": ["chat"]})
    assert st == 200
    plain, _ = container.open_(base64.b64decode(exp["data"]), container.parse_key(exp["key"]))
    manifest, parts = archive.read_zip(plain)
    rows = parts["chat"]["tables"]["chat_messages"]["rows"]
    assert len(rows) == 1 and "a real message" in json.dumps(rows) and "made up" not in json.dumps(rows)
    info = (await api.call("GET", "/api/backup/info"))[1]
    assert {s["id"]: s["rows"] for s in info["scopes"]}["chat"] == 1                        # the count shown to the owner is real rows only
    # an older or hand-made backup that does hold demo rows: they are skipped, the real ones come in
    cols = parts["chat"]["tables"]["chat_messages"]["columns"]
    di = cols.index("demo")
    mixed = {"tables": {"chat_messages": {"columns": cols, "rows": [
        [*rows[0][:cols.index("msg_id")], "r2", *rows[0][cols.index("msg_id") + 1:]],
        [*rows[0][:cols.index("msg_id")], "d2", *rows[0][cols.index("msg_id") + 1:]]]}}, "kv": {}}
    mixed["tables"]["chat_messages"]["rows"][0][di] = 0
    mixed["tables"]["chat_messages"]["rows"][1][di] = 1
    key = container.new_key()
    blob, _ = container.seal(archive.build_zip({"chat": mixed}, "test"), key, "", {"scopes": ["chat"], "app": "test"})
    body = {"data": base64.b64encode(blob).decode(), "key": container.format_key(key), "mode": "replace"}
    st, dry = await api.call("POST", "/api/backup/import", {**body, "dry_run": True})
    assert st == 200 and dry["plan"]["chat"]["chat_messages"] == 1
    st, done = await api.call("POST", "/api/backup/import", body)
    assert st == 200 and done["applied"]["chat"]["demo_skipped"] == 1 and done["applied"]["chat"]["added"] == 1
    left = {r["msg_id"]: r["demo"] for r in await db.fetchall("SELECT msg_id, demo FROM chat_messages")}
    assert left == {"r2": 0, "d1": 1}      # replace swapped the real rows only; the existing demo row was left alone; nothing demo came in


# ------------------------------------------------------------------ 1.4.3: restoring on Postgres
class _FakePg:
    """Stands in for Postgres: tables with a text id (knowledge_packs) have no counter, and asking for MAX(id) of one is an error, as on the real thing."""
    backend = "postgres"

    def __init__(self):
        self.ran = []

    async def fetchall(self, sql, params=()):
        table = params[0] if params else ""
        return [{"column_name": "id"}] if table in ("knowledge_packs", "commands") else []

    async def fetchone(self, sql, params=()):
        return {"seq": "commands_id_seq" if params[0] == "commands" else None}

    async def execute(self, sql, params=()):
        if "knowledge_packs" in sql:
            raise AssertionError("must not ask for MAX(id) of a table with a text id")
        self.ran.append((sql, params))
        return 0


class _FakeCtx:
    def __init__(self):
        self.db = _FakePg()


async def test_sequence_repair_skips_tables_with_text_ids_on_postgres():
    c = _FakeCtx()
    await archive._fix_sequences(c, ["knowledge_packs", "commands", "quotes"])
    assert len(c.db.ran) == 1 and c.db.ran[0][1] == ("commands_id_seq",)


# ------------------------------------------------------------------ 1.4.3: batched writes, real progress, cancel
async def _mem_service():
    from types import SimpleNamespace as NS
    from app.backup.service import BackupService
    from app.db import Database
    db = Database("sqlite:///:memory:")
    await db.connect()

    async def noop(*a, **k):
        return None
    c = NS(db=db, bus=NS(publish=lambda *a, **k: None), access=NS(audit=noop, _alert=noop))
    c.backup = BackupService(c)
    return c


async def test_merge_and_replace_write_in_batches_and_report_bad_rows():
    c = await _mem_service()
    rows = [[i, f"q{i}", "a", 1.5] for i in range(1, 1501)]
    data = {"tables": {"quotes": {"columns": ["id", "body", "author", "created"], "rows": rows}}, "kv": {}}
    ticks = []
    r = await archive.apply_scope(c, "community", data, "merge", lambda n: ticks.append(n))
    assert r["added"] == 1500 and sum(ticks) == 1500
    assert (await archive.apply_scope(c, "community", data, "merge"))["skipped"] == 1500           # again: all already here
    bad = {"tables": {"quotes": {"columns": ["id", "body", "author", "created"], "rows": [[9001, "ok", "a", 1.0], [9002, None, "a", 1.0], [9003, "ok3", "a", 1.0]]}}, "kv": {}}
    r = await archive.apply_scope(c, "community", bad, "merge")
    assert r["added"] == 2 and r["failed"] == 1 and "quotes" in r["error"]                         # one bad row costs only itself
    r = await archive.apply_scope(c, "community", data, "replace")
    assert r["added"] == 1500 and (await c.db.fetchone("SELECT COUNT(*) AS n FROM quotes"))["n"] == 1500
    with pytest.raises(Exception):
        await archive.apply_scope(c, "community", bad, "replace")                                  # replace is all or nothing


async def test_import_reports_progress_and_can_be_cancelled_and_rolled_back():
    c = await _mem_service()
    svc = c.backup
    for i in range(1, 1201):
        await c.db.execute("INSERT INTO quotes (body, author, created) VALUES (?, ?, ?)", (f"q{i}", "a", 1.0))
    exp = await svc.export(["community"], "pw")
    await c.db.execute("DELETE FROM quotes")
    await svc.import_(exp["data"], exp["key"], "pw", "merge", [], False)
    p = svc.progress_info()
    assert p["state"] == "done" and p["pct"] == 100 and p["result"]["added"] == 1200 and p["scopes"][0]["done"] == p["scopes"][0]["total"] == 1200

    async def cancel_when_running():
        while not (svc._run and svc._run["state"] == "running" and svc._run["cancellable"]):
            await asyncio.sleep(0)
        assert svc.request_cancel()
    task = asyncio.create_task(cancel_when_running())
    with pytest.raises(BackupError, match="cancelled"):
        await svc.import_(exp["data"], exp["key"], "pw", "replace", [], False)
    await task
    assert svc.progress_info()["state"] == "failed"
    assert (await c.db.fetchone("SELECT COUNT(*) AS n FROM quotes"))["n"] == 1200                   # everything was put back
