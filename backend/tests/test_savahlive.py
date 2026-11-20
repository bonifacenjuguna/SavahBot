"""SavahLive (1.5.0): pairing, device keys, the overlay feed. The service is driven directly with a real database and event bus
(no HTTP needed); the route wiring is covered by the end-to-end test at the bottom."""
import asyncio
import time
from collections import deque
from types import SimpleNamespace

import app.savahlive as sl_mod
from app.config import StaticConfig
from app.db import Database
from app.events import EventBus
from app.savahlive import KEY_PREFIX, LiveError, SavahLive
from app.shared import Shared


class FakeAccess:
    def __init__(self):
        self.lockdown, self.audits, self.alerts = False, [], []

    async def audit(self, action, session=None, ip="", detail=""):
        self.audits.append((action, detail))

    async def _alert(self, text):
        self.alerts.append(text)


async def make(**cfg):
    db = Database(":memory:")
    await db.connect()
    c = SimpleNamespace(db=db, cfg=StaticConfig({"savahlive_max_devices": 2, **cfg}), bus=EventBus(), shared=Shared(), access=FakeAccess(),
                        hub=SimpleNamespace(mode="live", stream_live=True, stream_title="PUBG night", buffer=deque()),
                        extras=SimpleNamespace(live={"viewers": 120, "likes": 45, "likes_hidden": False, "peak_viewers": 150, "updated": 1.0, "note": ""}))
    return SavahLive(c), c


async def pair(sl, days=0, name="Pixel 8", ip="1.1.1.1"):
    made = await sl.new_code(days)
    return await sl.redeem(made["shown"], name, "1.5.0", ip)       # typed with the dash and in any case: both are accepted


def bearer(key):
    return f"Bearer {key}"


def run(coro):
    return asyncio.run(coro)


async def refused(coro, code):
    try:
        await coro
    except LiveError as e:
        assert e.code == code, (e.code, e.message)
        return e
    raise AssertionError(f"expected {code}")


async def next_events(gen, n=1, timeout=3):
    got = []
    while len(got) < n:
        chunk = await asyncio.wait_for(gen.__anext__(), timeout)
        if chunk.startswith(":") or chunk.startswith("retry"):
            continue
        got.append(chunk)
    return got


def kind(chunk):
    return chunk.split("\n", 1)[0][len("event: "):]


def body(chunk):
    import json
    return json.loads(chunk.split("data: ", 1)[1])


class FakeHub(SimpleNamespace):
    """The part of the hub the phone's send route touches: it records what was posted and can be told to fail."""

    async def send_chat(self, text, render=False):
        self.posted.append(text)
        return self.ok


def test_sending_chat_needs_both_switches_and_is_rate_limited():
    async def go():
        sl, c = await make()
        c.hub = FakeHub(mode="live", stream_live=True, stream_title="x", buffer=deque(), posted=[], ok=True)
        d = await pair(sl)
        dev = await sl.device(bearer(d["key"]))
        await refused(sl.send(dev, "hello"), "send_denied")                           # a new phone cannot send until you allow it
        assert sl._feed_settings(dev)["can_send"] is False
        assert await sl.edit(d["device_id"], None, None, can_send=True)
        dev = await sl.device(bearer(d["key"]))
        assert sl._feed_settings(dev)["can_send"] is True and (await sl.devices())[0]["can_send"] is True
        await sl.send(dev, "  hello\n\tthere  ", "1.1.1.1")
        assert c.hub.posted == ["hello there"]                                         # one clean line
        assert c.access.audits[-1][0] == "savahlive_sent" and "hello" not in c.access.audits[-1][1]   # the log has the length, not the words
        await refused(sl.send(dev, "again"), "slow")                                   # one message every couple of seconds
        sl._sent[d["device_id"]].clear()
        await refused(sl.send(dev, "   "), "empty")
        await sl.send(dev, "x" * 500)
        assert len(c.hub.posted[-1]) == 200
        c.cfg.set("savahlive_send_enabled", False)                                     # the master switch beats the phone's own permission
        assert sl._feed_settings(dev)["can_send"] is False
        sl._sent[d["device_id"]].clear()
        await refused(sl.send(dev, "hi"), "send_off")
        c.cfg.set("savahlive_send_enabled", True)
        sl._sent[d["device_id"]].clear()
        c.hub.ok = False
        await refused(sl.send(dev, "hi"), "send_failed")                               # YouTube said no: the phone is told, nothing is counted
        assert not sl._sent[d["device_id"]]
    run(go())


class ModHub(SimpleNamespace):
    async def manual(self, chat_id, action, seconds=300):
        self.done.append((chat_id, action, seconds))
        return {"ok": True} if self.ok else {"ok": False, "error": "The owner and the bot cannot be moderated.", "code": 400}


def test_moderating_needs_both_switches_is_limited_and_never_bans():
    async def go():
        sl, c = await make()
        c.hub = ModHub(mode="live", stream_live=True, stream_title="x", buffer=deque(), done=[], ok=True)
        d = await pair(sl)
        dev = await sl.device(bearer(d["key"]))
        c.cfg.set("savahlive_mod_enabled", True)
        await refused(sl.moderate(dev, 5, "delete"), "mod_denied")                   # a new phone cannot moderate until you allow it
        assert sl._feed_settings(dev)["can_mod"] is False
        assert await sl.edit(d["device_id"], None, None, can_mod=True)
        dev = await sl.device(bearer(d["key"]))
        assert sl._feed_settings(dev)["can_mod"] is True and (await sl.devices())[0]["can_mod"] is True
        await sl.moderate(dev, 5, "delete", "1.1.1.1")
        assert c.hub.done == [(5, "delete", 300)]
        assert c.access.audits[-1][0] == "savahlive_moderated"
        await refused(sl.moderate(dev, 6, "timeout"), "slow")                        # not twice in a second
        sl._modded[d["device_id"]].clear()
        await sl.moderate(dev, 6, "timeout")
        assert c.hub.done[-1] == (6, "timeout", 300)
        sl._modded[d["device_id"]].clear()
        await refused(sl.moderate(dev, 7, "ban"), "bad_action")                      # bans stay on the dashboard
        c.hub.ok = False
        await refused(sl.moderate(dev, 8, "delete"), "mod_failed")
        c.cfg.set("savahlive_mod_enabled", False)                                    # the master switch beats the phone's own permission
        assert sl._feed_settings(dev)["can_mod"] is False
        await refused(sl.moderate(dev, 5, "delete"), "mod_off")
    run(go())


def test_the_hello_tells_the_app_which_version_is_current():
    async def go():
        sl, c = await make()
        c.cfg.set("savahlive_download_url", "https://example.com/app.apk")
        d = await pair(sl)
        dev = await sl.device(bearer(d["key"]))
        gen = sl.stream(dev, 0, lambda: asyncio.sleep(0, False))
        hello = body((await next_events(gen))[0])
        from app import __version__
        assert hello["update"] == {"version": __version__, "url": "https://example.com/app.apk"}
        await gen.aclose()
    run(go())


def test_a_sent_message_shows_on_the_senders_own_feed():
    async def go():
        sl, c = await make()
        c.hub = FakeHub(mode="live", stream_live=True, stream_title="x", buffer=deque(), posted=[], ok=True)
        d = await pair(sl)
        await sl.edit(d["device_id"], None, None, can_send=True)
        dev = await sl.device(bearer(d["key"]))
        gen = sl.stream(dev, 0, lambda: asyncio.sleep(0, False))
        hello = body((await next_events(gen))[0])
        assert hello["settings"]["can_send"] is True
        await sl.send(dev, "gg everyone")
        chat = body((await next_events(gen))[0])
        assert chat["lines"][0]["text"] == "gg everyone" and chat["lines"][0]["name"] == "You"      # SavahBot hides its own account, the sender still sees theirs
        await gen.aclose()
    run(go())


def test_pairing_gives_a_working_key_once():
    async def go():
        sl, c = await make()
        dev = await pair(sl, name="  Pixel   8  ")
        assert dev["key"].startswith(KEY_PREFIX) and dev["name"] == "Pixel 8" and dev["expires"] is None
        row = await sl.device(bearer(dev["key"]))
        assert row["id"] == dev["device_id"]
        made = await sl.new_code()
        await sl.redeem(made["code"], "A", "", "2.2.2.2")
        await refused(sl.redeem(made["code"], "B", "", "2.2.2.2"), "bad_code")       # a code is good exactly once
        assert c.access.audits[0][0] == "savahlive_paired" and "Pixel 8" in c.access.alerts[0]
        raw = await c.db.fetchone("SELECT key_hash FROM live_devices WHERE id = ?", (dev["device_id"],))
        assert dev["key"] not in str(raw)                                            # only a hash is stored
    run(go())


def test_bad_codes_expire_and_throttle():
    async def go():
        sl, c = await make()
        await refused(sl.redeem("NOPE", "x", "", "9.9.9.9"), "bad_code")
        made = await sl.new_code()
        await c.db.execute("UPDATE live_pair_codes SET expires = ?", (time.time() - 1,))
        await refused(sl.redeem(made["code"], "x", "", "9.9.9.9"), "bad_code")        # run out
        for _ in range(8):
            await refused(sl.redeem("ABCDEFGH", "x", "", "8.8.8.8"), "bad_code")
        good = await sl.new_code()
        await refused(sl.redeem(good["code"], "x", "", "8.8.8.8"), "throttled")      # this address is locked out, even with a right code
        await sl.redeem(good["code"], "x", "", "7.7.7.7")                            # another address is not
    run(go())


def test_device_limit_and_switch():
    async def go():
        sl, c = await make()
        await pair(sl)
        await pair(sl, ip="2.2.2.2")
        made = await sl.new_code()
        await refused(sl.redeem(made["code"], "x", "", "3.3.3.3"), "too_many")
        assert (await c.db.fetchone("SELECT used_ts FROM live_pair_codes"))["used_ts"] is None   # a refused pairing does not burn the code
        c.cfg.set("savahlive_enabled", False)
        await refused(sl.redeem(made["code"], "x", "", "3.3.3.3"), "disabled")
    run(go())


def test_revoke_expiry_lockdown_idle_and_edit():
    async def go():
        sl, c = await make()
        d = await pair(sl, days=7)
        assert abs(d["expires"] - (time.time() + 7 * 86400)) < 5
        key = bearer(d["key"])
        c.access.lockdown = True
        await refused(sl.device(key), "lockdown")                                    # 403: the phone keeps its pairing and retries
        c.access.lockdown = False
        await c.db.execute("UPDATE live_devices SET expires = ?", (time.time() - 5,))
        await refused(sl.device(key), "expired")
        assert await sl.edit(d["device_id"], "Spare phone", 0)                       # extending an expired pairing brings it back, no re-pairing
        assert (await sl.device(key))["name"] == "Spare phone"
        c.cfg.set("savahlive_idle_unpair_days", 3)
        await c.db.execute("UPDATE live_devices SET last_seen = ?", (time.time() - 4 * 86400,))
        await refused(sl.device(key), "idle")
        await refused(sl.device(key), "revoked")
        assert not await sl.edit(d["device_id"], "x", None)
        await refused(sl.device("Bearer sbs_dashboardtoken"), "unpaired")            # a dashboard sign-in is not a device key
        await refused(sl.device(""), "unpaired")
    run(go())


def test_key_rotation_never_locks_a_phone_out():
    async def go():
        sl, c = await make(savahlive_rotate_days=30)
        d = await pair(sl)
        old = d["key"]
        row = await sl.device(bearer(old))
        assert not sl.wants_rotation(row)
        await c.db.execute("UPDATE live_devices SET key_issued = ?", (time.time() - 31 * 86400,))
        row = await sl.device(bearer(old))
        assert sl.wants_rotation(row)
        new = await sl.rotate(row, sl_mod._h(old))
        assert (await sl.device(bearer(new)))["via_prev"] is False
        late = await sl.device(bearer(old))                                          # the reply never arrived: the old key still works...
        assert late["via_prev"] is True and sl.wants_rotation(late)                   # ...and the server asks for another swap
        await c.db.execute("UPDATE live_devices SET prev_until = ?", (time.time() - 1,))
        await refused(sl.device(bearer(old)), "unpaired")                            # ...for a day
    run(go())


def test_feed_snapshot_batches_filters_and_purge():
    async def go():
        sl, c = await make(savahlive_chat_lines=10)
        d = await pair(sl)
        dev = await sl.device(bearer(d["key"]))
        now = time.time()
        msg = lambda i, text, **kw: {"id": i, "author_id": f"u{i}", "author_name": f"N{i}", "text": text, "level": "everyone", "ts": now, "verdict": "allow", "from_bot": False, **kw}
        c.hub.buffer.extend([msg(1, "old one"), msg(2, "spam", verdict="delete"), msg(3, "bot", level="bot"), msg(4, "hello")])
        gen = sl.stream(dev, 0, lambda: asyncio.sleep(0, False))
        hello = body((await next_events(gen))[0])
        assert hello["v"] == 1 and hello["state"]["live"] and hello["stats"]["viewers"] == 120 and hello["rotate"] is False
        assert [m["id"] for m in hello["chat"]] == [1, 4]                            # bots and flagged messages stay out
        assert c.bus.subscriber_count == 0 and len(c.bus._subs) == 1                   # delivered to, but not counted against the dashboard limit
        for i in range(10, 13):
            c.bus.publish("chat", msg(i, f"line {i}"))
        c.bus.publish("chat", msg(20, "ancient", ts=now - 999))                       # backfilled history is never replayed as new chat
        c.bus.publish("chat", msg(21, "flagged", verdict="timeout"))
        chunk = (await next_events(gen))[0]
        assert kind(chunk) == "chat" and [m["id"] for m in body(chunk)["lines"]] == [10, 11, 12]   # a burst travels as one message
        c.bus.publish("ban_made", {"author_id": "u10", "author": "N10"})
        c.bus.publish("chat_deleted", {"id": 11, "author_id": "u11"})
        chunk = (await next_events(gen))[0]
        assert kind(chunk) == "purge" and body(chunk) == {"uids": ["u10"], "ids": [11]}
        await gen.aclose()
        assert d["device_id"] not in sl.feeds and c.bus.subscriber_count == 0         # nothing is left running after a disconnect
    run(go())


def test_feed_pushes_changes_and_cuts_off_revoked_phones():
    async def go():
        sl_mod.FEED_TICK, sl_mod.HEARTBEAT = 0.05, 0.2
        sl, c = await make()
        d = await pair(sl)
        dev = await sl.device(bearer(d["key"]))
        gen = sl.stream(dev, 0, lambda: asyncio.sleep(0, False))
        await next_events(gen)
        c.extras.live["viewers"] = 130
        c.cfg.set("savahlive_font_size", 18)
        got = await next_events(gen, 2)
        assert {kind(g) for g in got} == {"stats", "settings"}
        assert [body(g)["viewers"] for g in got if kind(g) == "stats"] == [130]
        c.hub.stream_live = False
        c.bus.publish("stream", {"live": False})
        state = (await next_events(gen))[0]
        assert kind(state) == "state" and body(state)["live"] is False
        stats = (await next_events(gen))[0]
        assert kind(stats) == "stats" and body(stats)["viewers"] is None             # off air: no stale numbers
        assert await sl.revoke(d["device_id"])
        end = (await next_events(gen))[0]
        assert kind(end) == "unpaired" and body(end)["code"] == "revoked"
        await refused(sl.device(bearer(d["key"])), "revoked")
        try:
            await gen.__anext__()
            raise AssertionError("the stream should have ended")
        except StopAsyncIteration:
            pass
    run(go())


def test_one_feed_per_phone_and_a_cap_across_phones():
    async def go():
        sl, c = await make(savahlive_max_feeds=1)
        a, b = await pair(sl), await pair(sl, ip="2.2.2.2")
        da, db_ = await sl.device(bearer(a["key"])), await sl.device(bearer(b["key"]))
        g1 = sl.stream(da, 0, lambda: asyncio.sleep(0, False))
        await next_events(g1)
        assert sl.can_open(da["id"]) and not sl.can_open(db_["id"])
        g2 = sl.stream(da, 0, lambda: asyncio.sleep(0, False))                       # the same phone reconnecting replaces its old connection
        await next_events(g2)
        end = (await next_events(g1))[0]
        assert kind(end) == "unpaired" and body(end)["code"] == "replaced"
        assert len(sl.feeds) == 1
        await g2.aclose()
        assert sl.can_open(db_["id"])
    run(go())


def test_overlay_settings_are_clamped_and_include_the_tab_hide_delay():
    async def go():
        sl, c = await make()
        assert sl.overlay_settings()["hide_seconds"] == 3                            # the default: the tab tucks away after three seconds
        c.cfg.set("savahlive_hide_seconds", 99)
        assert sl.overlay_settings()["hide_seconds"] == 30
        c.cfg.set("savahlive_hide_seconds", 0)
        assert sl.overlay_settings()["hide_seconds"] == 0                            # 0 = never tuck away
        d = await pair(sl)
        gen = sl.stream(await sl.device(bearer(d["key"])), 0, lambda: asyncio.sleep(0, False))
        hello = body((await next_events(gen))[0])
        assert hello["settings"]["hide_seconds"] == 0 and hello["settings"]["peek_seconds"] == 5
        await gen.aclose()
    run(go())


def test_revoke_all_and_listing():
    async def go():
        sl, c = await make()
        await pair(sl)
        await pair(sl, ip="2.2.2.2")
        rows = await sl.devices()
        assert len(rows) == 2 and all(r["status"] == "active" and r["online"] is False for r in rows)
        assert await sl.revoke_all("password changed") == 2 and await sl.devices() == []
    run(go())


from tests.test_api import e2e  # noqa: E402


@e2e
async def test_http_pairing_and_feed(api):
    st, made = await api.call("POST", "/api/savahlive/pair-code", {"expiry_days": 7})
    assert st == 200 and made["qr"].startswith("<svg") and made["link"].endswith("/api/live/pair/open?c=" + made["code"])
    st, page = await api.call("GET", "/api/live/pair/open?c=" + made["code"], auth=False)
    assert st == 200 and "savahlive://pair" in page and made["shown"] in page
    st, bad = await api.call("GET", "/api/live/pair/open?c=%3Cscript%3E", auth=False)
    assert st == 200 and "<script>" not in bad
    st, dev = await api.call("POST", "/api/live/pair", {"code": made["shown"].lower(), "name": "Pixel 8", "app_version": "1.5.0"}, auth=False)
    assert st == 200 and dev["key"].startswith("sld_")
    st, again = await api.call("POST", "/api/live/pair", {"code": made["code"]}, auth=False)
    assert st == 400 and again["code"] == "bad_code"
    from app.http import request_json
    dev_auth = {"Authorization": "Bearer " + dev["key"]}
    st, no = await api.call("GET", "/api/live/feed", auth=False)
    assert st == 401 and no["code"] == "unpaired"
    st, _ = await request_json("GET", api.base + "/api/savahlive", headers=dev_auth)      # a device key does not open the dashboard
    assert st == 401
    import asyncio as aio
    host, port = api.base.replace("http://", "").split(":")
    r, w = await aio.open_connection(host, int(port))
    w.write(f"GET /api/live/feed HTTP/1.0\r\nHost: x\r\nAuthorization: Bearer {dev['key']}\r\n\r\n".encode())
    await w.drain()
    data = b""
    while b"event: hello" not in data or not data.endswith(b"\n\n"):
        data += await aio.wait_for(r.read(4096), 5)
    assert b"200" in data.split(b"\r\n")[0] and b"text/event-stream" in data
    w.close()
    st, ov = await api.call("GET", "/api/savahlive")
    assert st == 200 and len(ov["devices"]) == 1 and ov["devices"][0]["name"] == "Pixel 8" and ov["devices"][0]["expires"]
    assert ov["devices"][0]["can_send"] is False and ov["settings"]["send_enabled"] is True
    st, denied = await request_json("POST", api.base + "/api/live/send", json_body={"text": "hi"}, headers=dev_auth)
    assert st == 403 and denied["code"] == "send_denied"                                  # a phone cannot send until you allow it
    st, _ = await request_json("POST", api.base + "/api/live/send", json_body={"text": "hi"})
    assert st == 401                                                                       # and a request with no device key is nobody
    st, _ = await api.call("PATCH", "/api/savahlive/devices/" + ov["devices"][0]["id"], {"can_send": True})
    assert st == 200
    st, ov = await api.call("GET", "/api/savahlive")
    assert ov["devices"][0]["can_send"] is True
    assert ov["devices"][0]["can_mod"] is False and ov["settings"]["mod_enabled"] is False        # moderating from a phone is off until you allow it twice
    st, denied = await request_json("POST", api.base + "/api/live/mod", json_body={"id": 1, "action": "delete"}, headers=dev_auth)
    assert st == 403 and denied["code"] == "mod_off"
    st, _ = await api.call("PATCH", "/api/savahlive/devices/" + ov["devices"][0]["id"], {"can_mod": True})
    assert st == 200
    st, _ = await api.call("POST", "/api/savahlive/settings", {"mod_enabled": True})
    assert st == 200
    st, denied = await request_json("POST", api.base + "/api/live/mod", json_body={"id": 999999, "action": "ban"}, headers=dev_auth)
    assert st == 422 and denied["code"] == "bad_action"
    st, _ = await api.call("DELETE", "/api/savahlive/devices/" + ov["devices"][0]["id"])
    assert st == 200
    st, gone = await request_json("GET", api.base + "/api/live/feed", headers=dev_auth)
    assert st == 401 and gone["code"] == "revoked"
