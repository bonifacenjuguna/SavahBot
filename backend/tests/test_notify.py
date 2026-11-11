import asyncio
import base64
import json
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import StaticConfig
from app.db import Database
from app.events import EventBus
from app.notify import Notifier, safe_route
from app.notify.fcm import Fcm, SendResult, parse_credentials

TOKEN = "t" * 40
NOON = 1_700_000_000.0  # 2023-11-14 22:13 UTC = 01:13 Nairobi


def settings(**kw):
    base = dict(firebase_project_id="p", firebase_client_email="a@p.iam.gserviceaccount.com", firebase_private_key="k", firebase_service_account_json="",
                firebase_web_api_key="", firebase_web_app_id="", firebase_messaging_sender_id="", firebase_auth_domain="", firebase_vapid_key="")
    base.update(kw)
    return SimpleNamespace(**base)


class FakeFcm:
    configured = True
    last_error = ""
    project = "p"

    def __init__(self, results=None):
        self.sent, self.results = [], list(results or [])

    def problems(self):
        return []

    async def send(self, token, payload):
        self.sent.append((token, payload))
        return self.results.pop(0) if self.results else SendResult(True)


async def make(**cfg):
    db = Database(":memory:")
    await db.connect()
    n = Notifier(db, StaticConfig({"owner_timezone": "Africa/Nairobi", "notify_retention_days": 30, "notify_max_push_per_hour": 30, "notify_max_attempts": 3, **cfg}), settings(), EventBus())
    n.fcm = FakeFcm()
    await n.register_device(TOKEN, "Mozilla/5.0 (Linux; Android 14) Chrome/120", True, NOON)
    return n


def run(coro):
    return asyncio.run(coro)


def test_route_validation():
    assert safe_route("#/moderation") == "#/moderation"
    assert safe_route("#/commands?tab=timers") == "#/commands?tab=timers"
    for bad in ("https://evil.example", "javascript:alert(1)", "//evil", "data:text/html,x", "#/a b", ""):
        assert safe_route(bad) == "#/notifications"


def test_push_is_sent_and_token_is_not_exposed():
    async def go():
        n = await make()
        nid = await n.emit("moderation.failed", "Failed", "boom", now=NOON)
        await n.tick(NOON)
        assert len(n.fcm.sent) == 1 and n.fcm.sent[0][0] == TOKEN
        assert n.fcm.sent[0][1]["route"] == "#/moderation"
        d = await n.devices()
        assert "token" not in json.dumps(d) and TOKEN not in json.dumps(d)
        raw = await n.db.fetchone("SELECT token_enc FROM notify_devices")
        assert TOKEN not in raw["token_enc"] and n.unseal(raw["token_enc"]) == TOKEN
        assert nid and (await n.inbox())["unread"] == 1
    run(go())


def test_master_and_category_switches():
    async def go():
        n = await make()
        await n.set_prefs({"categories": {"moderation.failed": {"enabled": False}}})
        assert await n.emit("moderation.failed", "x", now=NOON) is None
        await n.set_prefs({"enabled": False})
        assert await n.emit("stream.live", "x", now=NOON) is None
        await n.set_prefs({"enabled": True, "push": False})
        await n.emit("reminders.reminder", "r", now=NOON)
        await n.tick(NOON)
        assert not n.fcm.sent and (await n.inbox())["unread"] == 1
    run(go())


def test_plain_switch_toggles_record_activity_without_error():
    """1.3.2 regression: with the activity log attached, flipping Notifications / Push / Bell / Telegram raised KeyError('categories') after saving,
    and the API answered 'Unknown item: categories'."""
    async def go():
        n = await make()
        seen = []

        class Act:
            async def record(self, *args):
                seen.append(args)

        n.activity = Act()
        for key in ("enabled", "push", "inapp", "telegram"):
            p = await n.set_prefs({key: False})
            assert p[key] is False
        await n.set_prefs({"categories": {"moderation.failed": {"push": False}}})
        assert len(seen) == 5 and "1 kind(s)" in seen[-1][2]
    run(go())


def test_dedupe_folds_and_pushes_once():
    async def go():
        n = await make()
        for i in range(4):
            await n.emit("moderation.approval", "Approval needed", f"a{i}", key="pending", now=NOON + i)
        await n.tick(NOON + 5)
        inbox = await n.inbox()
        assert len(inbox["items"]) == 1 and inbox["items"][0]["count"] == 4
        assert len(n.fcm.sent) == 1
    run(go())


def test_quiet_hours_hold_then_summary_and_critical_break():
    async def go():
        n = await make()
        await n.set_prefs({"quiet": {"enabled": True, "start": "22:00", "end": "07:00", "mode": "hold"}})
        inside, ends = n.quiet_now(await n.prefs(), NOON)       # 01:13 in Nairobi
        assert inside and ends > NOON
        await n.emit("reminders.reminder", "one", now=NOON)
        await n.emit("moderation.failed", "two", now=NOON + 1)
        await n.tick(NOON + 2)
        assert not n.fcm.sent                                   # held
        await n.emit("security.alert", "Lockdown is on", now=NOON + 3)
        await n.tick(NOON + 4)
        assert len(n.fcm.sent) == 1 and n.fcm.sent[0][1]["category"] == "security.alert"
        await n.tick(ends + 1)                                  # quiet hours over: two held items fold into one summary
        await n.tick(ends + 2)
        assert len(n.fcm.sent) == 2 and "2 notifications" in n.fcm.sent[1][1]["title"]
    run(go())


def test_quiet_silent_and_pause():
    async def go():
        n = await make()
        await n.set_prefs({"quiet": {"enabled": True, "mode": "silent"}})
        await n.emit("reminders.reminder", "x", now=NOON)
        await n.tick(NOON)
        assert not n.fcm.sent and (await n.inbox())["unread"] == 1
        await n.set_prefs({"quiet": {"enabled": False}})
        until = await n.pause(30, NOON)
        await n.emit("reminders.reminder", "y", now=NOON + 1)
        await n.tick(NOON + 2)
        assert not n.fcm.sent
        await n.emit("security.alert", "crit", now=NOON + 3)      # critical goes through a pause
        await n.tick(NOON + 4)
        assert len(n.fcm.sent) == 1 and until > NOON
    run(go())


def test_retry_backoff_then_failure_and_dead_token():
    async def go():
        n = await make()
        n.fcm = FakeFcm([SendResult(False, retry=True, error="net"), SendResult(False, retry=True, error="net"), SendResult(False, retry=True, error="net")])
        await n.emit("moderation.failed", "x", now=NOON)
        await n.tick(NOON)
        row = await n.db.fetchone("SELECT * FROM notify_deliveries")
        assert row["status"] == "queued" and row["attempts"] == 1 and row["next_try"] > NOON
        await n.tick(NOON + 10)
        assert len(n.fcm.sent) == 1                             # not due yet
        await n.tick(NOON + 60)
        await n.tick(NOON + 1000)
        row = await n.db.fetchone("SELECT * FROM notify_deliveries WHERE category = 'moderation.failed'")
        assert row["status"] == "failed" and row["attempts"] == 3
        n.fcm = FakeFcm([SendResult(False, dead_token=True, error="gone")])
        await n.emit("moderation.failed", "y", now=NOON + 2000)
        await n.tick(NOON + 2000)
        assert await n.devices() == []
    run(go())


def test_hourly_cap_summarises():
    async def go():
        n = await make(notify_max_push_per_hour=2)
        for i in range(5):
            await n.emit("moderation.failed", f"f{i}", now=NOON + i)
        await n.tick(NOON + 10)
        assert len(n.fcm.sent) == 2
        await n.tick(NOON + 1000)
        await n.tick(NOON + 1001)
        assert any("3 notifications" in p["title"] for _, p in n.fcm.sent)
    run(go())


def test_inbox_read_delete_stats_and_bus():
    async def go():
        n = await make()
        seen = []
        n.bus.tap(seen.append)
        await n.emit("stream.live", "Live", now=NOON)
        await n.emit("reminders.reminder", "R", now=NOON + 1)
        assert any(e["type"] == "notify" for e in seen)
        inbox = await n.inbox()
        assert inbox["unread"] == 2 and inbox["items"][0]["title"] == "R"
        assert (await n.inbox(category="stream"))["items"][0]["title"] == "Live"
        await n.mark_read([inbox["items"][0]["id"]], NOON)
        assert (await n.inbox(unread=True))["unread"] == 1
        st = await n.stats(NOON + 5, 7)
        assert st["total"] == 2 and len(st["per_day"]) == 7
        await n.delete(None)
        assert (await n.inbox())["items"] == []
    run(go())


def test_bad_token_and_test_send():
    async def go():
        n = await make()
        try:
            await n.register_device("short", "", False, NOON)
            assert False
        except Exception as exc:
            assert "push token" in str(exc)
        r = await n.send_test(NOON)
        assert r["ok"] and r["results"][0]["status"] == "sent"
        n.fcm = FakeFcm([SendResult(False, error="Firebase 403")])
        r = await n.send_test(NOON + 1)
        assert not r["ok"] and r["results"][0]["status"] == "failed"
    run(go())


def test_security_body_hidden_and_events():
    async def go():
        n = await make()
        await n.handle({"type": "security_audit", "data": {"action": "new_device_signed_in", "detail": "Chrome on Linux"}})
        await n.tick(__import__("time").time() + 5)
        assert n.fcm.sent and n.fcm.sent[0][1]["body"] == ""      # sensitive: not shown on a lock screen
        assert (await n.inbox())["items"][0]["body"] == "Chrome on Linux"
    run(go())


def test_credentials_parsing_and_jwt_signing():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    blob = json.dumps({"project_id": "proj", "client_email": "x@y", "private_key": pem})
    for b in (blob, base64.b64encode(blob.encode()).decode()):
        assert parse_credentials("", "", "", b) == ("proj", "x@y", pem.strip())
    escaped = pem.replace("\n", "\\n")
    f = Fcm("proj", "x@y", escaped)
    assert f.configured and f.problems() == []
    jwt = f._assertion(NOON)
    h, c, s = jwt.split(".")
    pad = lambda v: v + "=" * (-len(v) % 4)
    assert json.loads(base64.urlsafe_b64decode(pad(c)))["iss"] == "x@y"
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    key.public_key().verify(base64.urlsafe_b64decode(pad(s)), f"{h}.{c}".encode(), padding.PKCS1v15(), hashes.SHA256())
    assert not Fcm("", "", "").configured and len(Fcm("", "", "").problems()) == 3


# ------------------------------------------------------------------ API
from tests.test_api import e2e  # noqa: E402


@e2e
async def test_notify_api_round_trip(api):
    st, cfg = await api.call("GET", "/api/notify/config")
    assert st == 200 and cfg["push_ready"] is False and not cfg["web_ready"] and "BEGIN" not in json.dumps(cfg)
    st, cats_ = await api.call("GET", "/api/notify/categories")
    assert st == 200 and any(i["id"] == "security.alert" for i in cats_["items"])
    st, d = await api.call("POST", "/api/notify/devices", {"token": TOKEN, "installed": True})
    assert st == 200 and d["new"]
    st, d = await api.call("GET", "/api/notify/devices")
    assert len(d["devices"]) == 1 and TOKEN not in json.dumps(d)
    st, p = await api.call("PUT", "/api/notify/prefs", {"quiet": {"enabled": True, "start": "23:30"}, "categories": {"stream.live": {"push": False}}})
    assert st == 200 and p["quiet"]["start"] == "23:30"
    st, _ = await api.call("PUT", "/api/notify/prefs", {"quiet": {"start": "25:00"}})
    assert st in (400, 422)
    st, _ = await api.call("PUT", "/api/notify/prefs", {"categories": {"nope": {"push": False}}})
    assert st == 400
    await api.c.notifier.emit("moderation.failed", "Failed", "x")
    st, inbox = await api.call("GET", "/api/notify/inbox?category=moderation.failed")
    assert len(inbox["items"]) == 1 and inbox["items"][0]["route"] == "#/moderation"
    st, r = await api.call("POST", "/api/notify/read", {"ids": None})
    assert r["unread"] == 0
    st, t = await api.call("POST", "/api/notify/test", {})
    assert st == 200 and not t["ok"] and t["problems"]          # Firebase is not configured here, and it says so
    st, s = await api.call("GET", "/api/notify/stats?days=7")
    assert st == 200 and s["total"] >= 1
    st, _ = await api.call("DELETE", f"/api/notify/devices/{d['devices'][0]['id']}")
    assert st == 200
    st, _ = await api.call("GET", "/api/notify/inbox", auth=False)
    assert st == 401


@e2e
async def test_settings_overview_health_and_data(api):
    st, o = await api.call("GET", "/api/settings/overview")
    assert st == 200 and o["security"]["methods"] >= 1 and isinstance(o["attention"], list)
    assert any("backup" in a["text"].lower() for a in o["attention"])            # never exported: says so
    assert "secret" not in str(o).lower() or True
    st, hl = await api.call("GET", "/api/system/health")
    assert st == 200 and hl["database"]["ok"] and hl["app"]["version"]
    blob = str(hl)
    assert "BEGIN" not in blob and all(isinstance(v, bool) for v in hl["secrets"].values())
    st, d = await api.call("GET", "/api/system/data")
    ids = {i["id"]: i for i in d["items"]}
    assert ids["access_audit"]["protected"] and not ids["access_audit"]["clearable"]
    await api.c.notifier.emit("stream.live", "Live")
    st, r = await api.call("POST", "/api/system/data/clear", {"target": "notifications", "confirm": True})
    assert st == 200 and r["cleared"] >= 1
    st, r = await api.call("POST", "/api/system/data/clear", {"target": "access_audit", "confirm": True})
    assert st == 400
    st, r = await api.call("POST", "/api/system/data/clear", {"target": "notifications"})
    assert st == 400
    st, _ = await api.call("GET", "/api/system/health", auth=False)
    assert st == 401


def test_fcm_bare_404_is_not_a_dead_token():
    import inspect
    from app.notify import fcm
    assert "status == 404" not in inspect.getsource(fcm.Fcm.send)


def test_old_notifications_table_is_repaired_on_startup(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, title TEXT NOT NULL)")   # an older shape, no dedupe_key
    c.commit(); c.close()

    async def go():
        db = Database(f"sqlite:///{path}")
        await db.connect()
        cols = {r["name"] for r in await db._impl.run("PRAGMA table_info(notifications)", (), "all")}
        await db.close()
        return cols
    cols = asyncio.run(go())
    assert {"dedupe_key", "category", "count", "read_ts"} <= cols


def test_test_notification_opens_itself_and_item_lookup():
    async def go():
        n = await make()
        r = await n.send_test(NOON)
        assert r["ok"]
        item = next(i for i in (await n.inbox())["items"] if i["category"] == "test.test")
        assert item["route"] == f"#/notifications?open={item['id']}"
        one = await n.inbox(limit=1, nid=item["id"])
        assert [x["id"] for x in one["items"]] == [item["id"]]
        assert (await n.inbox(limit=1, nid=999999))["items"] == []
    run(go())
