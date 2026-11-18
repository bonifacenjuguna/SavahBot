"""1.1.8: optional Redis. A tiny RESP server stands in for Redis, so the real wire client is what gets tested."""
import asyncio
import time

import pytest

from app.config import Settings
from app.container import Container
from app.db import Database
from app.events import EventBus
from app.models import ChatMessage
from app.security import SharedThrottle
from app.shared import Leader, Shared, _RELEASE_LUA, _RENEW_LUA


def run(coro):
    return asyncio.run(coro)


class FakeRedis:
    """Speaks enough RESP2 for SavahBot: strings with expiry, counters, the two lock scripts, pub/sub and AUTH."""

    def __init__(self, password: str = "") -> None:
        self.data: dict[str, tuple[str, float]] = {}
        self.password = password
        self.subs: dict[str, set] = {}
        self.server = None
        self.port = 0
        self.commands: list[list[str]] = []
        self.writers: set = set()

    async def start(self):
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    @property
    def url(self) -> str:
        return f"redis://{':' + self.password + '@' if self.password else ''}127.0.0.1:{self.port}/0"

    async def stop(self):
        self.server.close()
        for w in list(self.writers):
            w.close()
        await asyncio.wait_for(self.server.wait_closed(), 2)

    def _live(self, k):
        v = self.data.get(k)
        if v and v[1] and v[1] <= time.time():
            del self.data[k]
            return None
        return v

    @staticmethod
    async def _read(r):
        line = await r.readline()
        if not line:
            return None
        n = int(line[1:-2])
        out = []
        for _ in range(n):
            ln = int((await r.readline())[1:-2])
            out.append((await r.readexactly(ln + 2))[:-2].decode())
        return out

    @staticmethod
    def _bulk(v):
        return b"$-1\r\n" if v is None else b"$%d\r\n%s\r\n" % (len(v.encode()), v.encode())

    async def _client(self, r, w):
        authed = not self.password
        self.writers.add(w)
        try:
            while True:
                cmd = await self._read(r)
                if cmd is None:
                    break
                self.commands.append(cmd)
                name, a = cmd[0].upper(), cmd[1:]
                if name == "AUTH":
                    if a[-1] == self.password:
                        authed = True
                        w.write(b"+OK\r\n")
                    else:
                        w.write(b"-WRONGPASS invalid password\r\n")
                elif not authed:
                    w.write(b"-NOAUTH Authentication required.\r\n")
                elif name == "PING":
                    w.write(b"+PONG\r\n")
                elif name == "SELECT":
                    w.write(b"+OK\r\n")
                elif name == "GET":
                    v = self._live(a[0])
                    w.write(self._bulk(v[0] if v else None))
                elif name == "SET":
                    k, val, opts = a[0], a[1], [x.upper() for x in a[2:]]
                    exp = 0.0
                    if "PX" in opts:
                        exp = time.time() + int(a[2 + opts.index("PX") + 1]) / 1000
                    if "NX" in opts and self._live(k):
                        w.write(b"$-1\r\n")
                    else:
                        self.data[k] = (val, exp)
                        w.write(b"+OK\r\n")
                elif name == "DEL":
                    w.write(b":%d\r\n" % (1 if self.data.pop(a[0], None) else 0))
                elif name == "INCR":
                    v = self._live(a[0])
                    n = int(v[0]) + 1 if v else 1
                    self.data[a[0]] = (str(n), v[1] if v else 0.0)
                    w.write(b":%d\r\n" % n)
                elif name == "PEXPIRE":
                    v = self._live(a[0])
                    if v:
                        self.data[a[0]] = (v[0], time.time() + int(a[1]) / 1000)
                    w.write(b":1\r\n")
                elif name == "PTTL":
                    v = self._live(a[0])
                    w.write(b":%d\r\n" % (-2 if not v else (-1 if not v[1] else int((v[1] - time.time()) * 1000))))
                elif name == "EVAL":
                    script, key, token = a[0], a[2], a[3]
                    v = self._live(key)
                    ok = bool(v and v[0] == token)
                    if script == _RENEW_LUA and ok:
                        self.data[key] = (token, time.time() + int(a[4]))
                    elif script == _RELEASE_LUA and ok:
                        del self.data[key]
                    w.write(b":%d\r\n" % (1 if ok else 0))
                elif name == "PUBLISH":
                    n = 0
                    for sw in list(self.subs.get(a[0], ())):
                        sw.write(b"*3\r\n$7\r\nmessage\r\n" + self._bulk(a[0]) + self._bulk(a[1]))
                        n += 1
                    w.write(b":%d\r\n" % n)
                elif name == "SUBSCRIBE":
                    for i, ch in enumerate(a, 1):
                        self.subs.setdefault(ch, set()).add(w)
                        w.write(b"*3\r\n$9\r\nsubscribe\r\n" + self._bulk(ch) + b":%d\r\n" % i)
                else:
                    w.write(b"-ERR unknown command\r\n")
                await w.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            for s in self.subs.values():
                s.discard(w)
            w.close()


async def settle(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        await asyncio.sleep(0.02)
    return cond()


# ------------------------------------------------------------------------------------------- the client
def test_wire_client_strings_counters_ttl_and_json():
    async def go():
        fr = await FakeRedis().start()
        s = Shared(fr.url)
        await s.start()
        assert s.mode == "redis"
        await s.set("a", "1")
        assert await s.get("a") == "1"
        assert await s.incr("n", ex=5) == 1 and await s.incr("n", ex=5) == 2
        assert 0 < await s.ttl("n") <= 5
        assert await s.set("lock", "x", ex=5, nx=True) is True and await s.set("lock", "y", ex=5, nx=True) is False
        await s.set_json("j", {"k": [1, 2]})
        assert await s.get_json("j") == {"k": [1, 2]}
        assert await s.set_blob("b", {"big": "x" * 5000}) < 500   # stored compressed
        assert (await s.get_blob("b"))["big"] == "x" * 5000
        assert "savahbot:a" in fr.data                            # every key carries the prefix
        await s.stop(); await fr.stop()
    run(go())


def test_password_in_url_is_sent_and_a_wrong_one_falls_back_to_memory():
    async def go():
        fr = await FakeRedis(password="s3cret").start()
        good = Shared(fr.url)
        await good.start()
        await good.set("a", "1")
        assert good.mode == "redis" and await good.get("a") == "1"
        bad = Shared(fr.url.replace("s3cret", "nope"))
        await bad.start()
        assert bad.mode == "unreachable" and "WRONGPASS" in bad.status()["error"]
        await bad.set("a", "mem")                 # still works, in memory
        assert await bad.get("a") == "mem" and fr.data["savahbot:a"][0] == "1"
        await good.stop(); await bad.stop(); await fr.stop()
    run(go())


def test_redis_down_falls_back_to_memory_then_recovers():
    async def go():
        fr = await FakeRedis().start()
        port = fr.port
        s = Shared(fr.url, retry_seconds=0.2)
        await s.start()
        await s.set("k", "redis-value")
        await fr.stop()
        await s.set("k", "memory-value")          # no exception, no crash
        assert s.mode == "unreachable" and await s.get("k") == "memory-value"
        fr2 = FakeRedis()
        fr2.server = await asyncio.start_server(fr2._client, "127.0.0.1", port)
        fr2.port = port
        await asyncio.sleep(0.3)
        await s.set("k2", "back")
        assert s.mode == "redis" and fr2.data["savahbot:k2"][0] == "back"
        await s.stop(); await fr2.stop()
    run(go())


def test_empty_or_placeholder_url_means_off():
    for url in ("", "  ", "edit-me", "EDIT-ME"):
        s = Shared(url)
        assert not s.configured and s.mode == "off"
    assert not Shared("http://wrong").configured and "redis://" in Shared("http://wrong").last_error


# ------------------------------------------------------------------------------------------- 2. login lockout
def test_login_lockout_is_shared_and_survives_a_restart():
    async def go():
        fr = await FakeRedis().start()
        a = SharedThrottle(Shared(fr.url), 3, 60)
        for _ in range(3):
            await a.fail("1.2.3.4")
        assert await a.retry_after("1.2.3.4") > 0
        b = SharedThrottle(Shared(fr.url), 3, 60)          # "restart" / another instance
        assert await b.retry_after("1.2.3.4") > 0
        assert await b.retry_after("5.6.7.8") == 0
        await b.success("1.2.3.4")
        assert await a.retry_after("1.2.3.4") == 0
        await fr.stop()
    run(go())


def test_login_throttle_without_redis_behaves_as_before():
    async def go():
        t = SharedThrottle(Shared(), 3, 60)
        for _ in range(3):
            await t.fail("x")
        assert await t.retry_after("x") > 0
        await t.success("x")
        assert await t.retry_after("x") == 0
    run(go())


# ------------------------------------------------------------------------------------------- 4. leader
def test_only_one_leader_and_a_handover_when_it_stops():
    async def go():
        fr = await FakeRedis().start()
        log = []

        def mk(name):
            async def gain(): log.append(f"{name}+")
            async def lose(): log.append(f"{name}-")
            return Leader(Shared(fr.url), "leader", 30, gain, lose)
        a, b = mk("A"), mk("B")
        await a.step(); await b.step()
        assert a.is_leader and not b.is_leader and log == ["A+"]
        await a.step(); await b.step()
        assert log == ["A+"]                                # renewing changes nothing
        await a.stop()                                      # releases the lock at once
        await b.step()
        assert b.is_leader and log == ["A+", "B+"]
        await fr.stop()
    run(go())


def test_leader_that_loses_its_lock_steps_down():
    async def go():
        fr = await FakeRedis().start()
        log = []
        async def lose(): log.append("lost")
        a = Leader(Shared(fr.url), "leader", 30, on_lose=lose)
        await a.step()
        fr.data["savahbot:lock:leader"] = ("someone-else", time.time() + 30)
        await a.step()
        assert not a.is_leader and log == ["lost"]
        await fr.stop()
    run(go())


def test_without_redis_the_only_instance_leads_immediately():
    async def go():
        gained = []
        async def gain(): gained.append(1)
        lead = Leader(Shared(), on_gain=gain)
        await lead.start()
        assert lead.is_leader and gained == [1]
        await lead.stop()
    run(go())


# ------------------------------------------------------------------------------------------- 3. live events
def test_events_cross_instances_without_duplicating_locally():
    async def go():
        fr = await FakeRedis().start()
        sa, sb = Shared(fr.url), Shared(fr.url)
        a, b = EventBus(), EventBus()
        a.attach_shared(sa); b.attach_shared(sb)
        qa, qb = a.subscribe(), b.subscribe()
        await asyncio.sleep(0.3)                           # let both subscriptions register
        a.publish("chat", {"text": "hello"})
        assert await settle(lambda: qb.qsize() == 1)
        assert (await qb.get())["data"] == {"text": "hello"}
        await asyncio.sleep(0.2)
        assert qa.qsize() == 1                             # the sender's own dashboard got it once, not twice
        await sa.stop(); await sb.stop(); await fr.stop()
    run(go())


# ------------------------------------------------------------------------------------------- 5. cache
def test_cache_shares_one_result_and_is_skipped_without_redis():
    async def go():
        fr = await FakeRedis().start()
        calls = []

        async def heavy():
            calls.append(1)
            return {"n": len(calls)}
        s = Shared(fr.url)
        assert await s.cached("x", 30, heavy) == {"n": 1}
        assert await Shared(fr.url).cached("x", 30, heavy) == {"n": 1} and len(calls) == 1
        assert await s.cached("x", 0, heavy) == {"n": 2}   # 0 seconds = no caching
        off = Shared()
        assert await off.cached("y", 30, heavy) == {"n": 3} and await off.cached("y", 30, heavy) == {"n": 4}
        await fr.stop()
    run(go())


# ------------------------------------------------------------------------------------------- 1 + 6. memory that survives
def _boot_env(fr, **extra):
    return {"REDIS_URL": fr.url, "OWNER_PASSWORD": "pw", "DEMO_AUTOSTART": "false", "BOT_MODE": "demo", **extra}


def test_moderation_memory_and_cooldowns_survive_a_restart():
    async def go():
        fr = await FakeRedis().start()
        c1 = Container(Settings(env=_boot_env(fr), env_file=None), Database(":memory:"))
        await c1.start(wait_for_telegram=True)
        assert c1.leader.is_leader and c1.shared.mode == "redis"
        now = time.time()
        for i in range(4):
            c1.engine.rate.hit("youtube:spammer", now - i, 60)
        c1.engine.dups.observe("youtube:spammer", "buy followers now", now, 600)
        c1.engine.behavior.observe("youtube:spammer", now - 30, new_window=600, min_messages=5, max_cv=0.2, max_mean_gap=60)
        c1.engine._strikes["youtube:spammer"] = __import__("collections").deque([now - 5, now - 4], maxlen=50)
        c1.commands._last_user[(7, "youtube:spammer")] = now - 2
        c1.hub._recent_punish["youtube:spammer"] = now - 10
        await c1.stop()                                    # the shutdown does a last save
        assert "savahbot:state" in fr.data

        c2 = Container(Settings(env=_boot_env(fr), env_file=None), Database(":memory:"))
        await c2.start(wait_for_telegram=True)
        assert c2.engine.rate.hit("youtube:spammer", time.time(), 60) == 5          # four remembered + this one
        assert c2.engine.dups.observe("youtube:spammer", "buy followers now", time.time(), 600) == 2
        info = c2.engine.behavior.observe("youtube:spammer", time.time(), new_window=10, min_messages=5, max_cv=0.2, max_mean_gap=60)
        assert not info.is_new and info.count == 2
        assert len(c2.engine._strikes["youtube:spammer"]) == 2
        assert (7, "youtube:spammer") in c2.commands._last_user
        assert "youtube:spammer" in c2.hub._recent_punish
        await c2.stop(); await fr.stop()
    run(go())


def test_a_damaged_snapshot_never_blocks_startup():
    async def go():
        fr = await FakeRedis().start()
        fr.data["savahbot:state"] = ("not-a-real-snapshot", 0.0)
        c = Container(Settings(env=_boot_env(fr), env_file=None), Database(":memory:"))
        await c.start(wait_for_telegram=True)
        assert c.leader.is_leader
        await c.stop(); await fr.stop()
    run(go())


def test_the_same_live_message_is_only_handled_once():
    async def go():
        fr = await FakeRedis().start()
        c = Container(Settings(env=_boot_env(fr), env_file=None), Database(":memory:"))
        await c.start(wait_for_telegram=True)
        msg = lambda: ChatMessage("youtube", "u1", "Viewer", "hello there", "everyone", ts=time.time(), msg_id="yt-abc")
        await c.hub.ingest(msg())
        await c.hub.ingest(msg())                          # e.g. re-delivered after a restart or a hand-over
        assert c.hub.lines == 1 and len(c.hub.buffer) == 1
        await c.stop(); await fr.stop()
    run(go())


def test_a_standby_instance_stays_quiet_and_status_reports_redis():
    async def go():
        fr = await FakeRedis().start()
        c1 = Container(Settings(env=_boot_env(fr), env_file=None), Database(":memory:"))
        c2 = Container(Settings(env=_boot_env(fr), env_file=None), Database(":memory:"))
        await c1.start(wait_for_telegram=True)
        await c2.start(wait_for_telegram=True)
        assert c1.leader.is_leader and not c2.leader.is_leader
        assert c2.hub.source is None and c1.hub.source is not None     # only the leader runs a chat source
        await c2.hub.apply_mode()                                       # e.g. a mode switch sent to the standby
        assert c2.hub.source is None
        await c1.stop()                                                 # leader leaves, standby takes over
        await c2.leader.step()
        assert c2.leader.is_leader and c2.hub.source is not None
        await c2.stop(); await fr.stop()
    run(go())


def test_without_redis_the_container_behaves_as_in_1_1_7():
    async def go():
        c = Container(Settings(env={"OWNER_PASSWORD": "pw", "DEMO_AUTOSTART": "false"}, env_file=None), Database(":memory:"))
        await c.start(wait_for_telegram=True)
        assert c.shared.mode == "off" and c.leader.is_leader and c.hub.source is not None
        assert c.keeper.enabled is False and await c.keeper.save() == 0
        await c.stop()
    run(go())
