"""Optional Redis support (1.1.8). Standard library only: a small Redis client is built in, so nothing new is installed.

With REDIS_URL empty, everything here runs in memory and SavahBot behaves exactly as it did before.
With REDIS_URL set, the bot uses Redis for six things:

  1. moderation memory that survives a restart (snapshots of the trackers),
  2. login-attempt counting that survives a restart,
  3. live dashboard events shared across several backend instances (pub/sub),
  4. one leader for the chat poller, the scheduler and Telegram polling (a lock),
  5. a short-lived cache for heavy dashboard queries,
  6. cooldowns and duplicate-message protection that survive a restart.

Redis is never required: if it is unreachable the bot carries on in memory and reconnects on its own.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import ssl
import time
import zlib
from typing import Any, Awaitable, Callable
from urllib.parse import unquote, urlparse

logger = logging.getLogger("savahbot.shared")

_RENEW_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
_RELEASE_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
_NETWORK_ERRORS = (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, ssl.SSLError)


class RedisError(Exception):
    """Redis answered with an error (wrong password, bad command...)."""


# ============================================================================================ the wire client
class _Conn:
    """One Redis connection speaking RESP2. Commands are serialised; pub/sub uses its own connection."""

    def __init__(self, url: str, timeout: float) -> None:
        u = urlparse(url)
        if u.scheme not in ("redis", "rediss"):
            raise ValueError("REDIS_URL must start with redis:// or rediss://")
        self.host = u.hostname or "localhost"
        self.port = u.port or 6379
        self.user = unquote(u.username) if u.username else ""
        self.password = unquote(u.password) if u.password else ""
        self.db = int(u.path.strip("/") or 0) if u.path.strip("/").isdigit() else 0
        self.tls = u.scheme == "rediss"
        self.timeout = timeout
        self._r: asyncio.StreamReader | None = None
        self._w: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._w is not None and not self._w.is_closing()

    async def open(self) -> None:
        ctx = ssl.create_default_context() if self.tls else None
        self._r, self._w = await asyncio.wait_for(asyncio.open_connection(self.host, self.port, ssl=ctx), self.timeout)
        if self.password:
            await self._raw("AUTH", *([self.user, self.password] if self.user else [self.password]))
        if self.db:
            await self._raw("SELECT", self.db)

    async def close(self) -> None:
        w, self._w, self._r = self._w, None, None
        if w is not None:
            try:
                w.close()
                await asyncio.wait_for(w.wait_closed(), 1)
            except Exception:
                pass

    @staticmethod
    def _encode(args: tuple) -> bytes:
        out = [b"*%d\r\n" % len(args)]
        for a in args:
            b = a if isinstance(a, bytes) else str(a).encode()
            out.append(b"$%d\r\n%s\r\n" % (len(b), b))
        return b"".join(out)

    async def _raw(self, *args: Any) -> Any:
        assert self._w is not None and self._r is not None
        self._w.write(self._encode(args))
        await asyncio.wait_for(self._w.drain(), self.timeout)
        return await asyncio.wait_for(self.read_reply(), self.timeout)

    async def read_reply(self) -> Any:
        assert self._r is not None
        line = await self._r.readline()
        if not line:
            raise ConnectionError("Redis closed the connection")
        kind, rest = line[:1], line[1:-2]
        if kind == b"+":
            return rest.decode()
        if kind == b"-":
            raise RedisError(rest.decode())
        if kind == b":":
            return int(rest)
        if kind == b"$":
            n = int(rest)
            if n < 0:
                return None
            data = await self._r.readexactly(n + 2)
            return data[:-2].decode("utf-8", "replace")
        if kind == b"*":
            n = int(rest)
            return None if n < 0 else [await self.read_reply() for _ in range(n)]
        raise RedisError(f"unexpected reply {line!r}")

    async def command(self, *args: Any) -> Any:
        async with self._lock:
            if not self.connected:
                await self.open()
            try:
                return await self._raw(*args)
            except RedisError:
                raise
            except BaseException:
                await self.close()  # a half-read reply would poison the next command
                raise

    async def send_only(self, *args: Any) -> None:
        assert self._w is not None
        self._w.write(self._encode(args))
        await asyncio.wait_for(self._w.drain(), self.timeout)


# ============================================================================================ memory stand-in
class MemoryBackend:
    """The same operations, kept in this process. Used when Redis is off or temporarily unreachable."""

    def __init__(self) -> None:
        self._d: dict[str, tuple[str, float]] = {}   # key -> (value, expires_at or 0)

    def _live(self, key: str, now: float) -> tuple[str, float] | None:
        item = self._d.get(key)
        if item and item[1] and item[1] <= now:
            del self._d[key]
            return None
        return item

    async def get(self, key: str) -> str | None:
        item = self._live(key, time.time())
        return item[0] if item else None

    async def set(self, key: str, value: str, ex: float | None = None, nx: bool = False) -> bool:
        now = time.time()
        if nx and self._live(key, now):
            return False
        self._d[key] = (value, now + ex if ex else 0.0)
        if len(self._d) > 20000:
            for k in [k for k in self._d if self._live(k, now) is None][:5000]:
                self._d.pop(k, None)
        return True

    async def delete(self, key: str) -> None:
        self._d.pop(key, None)

    async def incr(self, key: str, ex: float | None = None) -> int:
        now = time.time()
        item = self._live(key, now)
        n = int(item[0]) + 1 if item else 1
        self._d[key] = (str(n), item[1] if item else (now + ex if ex else 0.0))
        return n

    async def ttl(self, key: str) -> float:
        item = self._live(key, time.time())
        return max(0.0, item[1] - time.time()) if item and item[1] else -1.0

    async def renew(self, key: str, token: str, ex: float) -> bool:
        item = self._live(key, time.time())
        if item and item[0] == token:
            self._d[key] = (token, time.time() + ex)
            return True
        return False

    async def release(self, key: str, token: str) -> bool:
        item = self._live(key, time.time())
        if item and item[0] == token:
            del self._d[key]
            return True
        return False

    async def ping(self) -> bool:
        return True


class RedisBackend:
    def __init__(self, url: str, timeout: float) -> None:
        self.conn = _Conn(url, timeout)

    async def get(self, key: str) -> str | None:
        return await self.conn.command("GET", key)

    async def set(self, key: str, value: str, ex: float | None = None, nx: bool = False) -> bool:
        args: list[Any] = ["SET", key, value]
        if ex:
            args += ["PX", int(ex * 1000)]
        if nx:
            args.append("NX")
        return (await self.conn.command(*args)) == "OK"

    async def delete(self, key: str) -> None:
        await self.conn.command("DEL", key)

    async def incr(self, key: str, ex: float | None = None) -> int:
        n = int(await self.conn.command("INCR", key))
        if n == 1 and ex:
            await self.conn.command("PEXPIRE", key, int(ex * 1000))
        return n

    async def ttl(self, key: str) -> float:
        ms = int(await self.conn.command("PTTL", key))
        return ms / 1000 if ms >= 0 else -1.0

    async def renew(self, key: str, token: str, ex: float) -> bool:
        return int(await self.conn.command("EVAL", _RENEW_LUA, 1, key, token, int(ex))) == 1

    async def release(self, key: str, token: str) -> bool:
        return int(await self.conn.command("EVAL", _RELEASE_LUA, 1, key, token)) == 1

    async def ping(self) -> bool:
        return (await self.conn.command("PING")) == "PONG"


# ============================================================================================ the facade
class Shared:
    """What the rest of the bot talks to. Falls back to memory instead of ever raising a Redis error."""

    def __init__(self, url: str = "", prefix: str = "savahbot", timeout: float = 3.0, retry_seconds: float = 15.0) -> None:
        self.url = (url or "").strip()
        if self.url.lower().startswith("edit-me"):
            self.url = ""
        self.prefix = (prefix or "savahbot").strip(":")
        self.instance_id = secrets.token_hex(4)
        self.retry_seconds = retry_seconds
        self.memory = MemoryBackend()
        self.redis: RedisBackend | None = None
        self.last_error = ""
        self._down_until = 0.0
        self._ever_ok = False
        self._subs: dict[str, list[Callable[[str], Awaitable[None] | None]]] = {}
        self._sub_task: asyncio.Task | None = None
        self._stopping = False
        self._timeout = timeout
        if self.url:
            try:
                self.redis = RedisBackend(self.url, timeout)
            except ValueError as exc:
                self.last_error = str(exc)
                logger.error("REDIS_URL is not usable (%s). Running without Redis.", exc)

    # ------------------------------------------------------------------ state
    @property
    def configured(self) -> bool:
        return self.redis is not None

    @property
    def active(self) -> bool:
        """True while commands really go to Redis (configured and not in a back-off)."""
        return self.redis is not None and time.time() >= self._down_until

    @property
    def mode(self) -> str:
        if not self.configured:
            return "off"
        return "redis" if self.active and self._ever_ok else ("connecting" if self.active else "unreachable")

    def status(self) -> dict[str, Any]:
        return {"mode": self.mode, "configured": self.configured, "instance": self.instance_id, "error": self.last_error if self.mode == "unreachable" else ""}

    def key(self, name: str) -> str:
        return f"{self.prefix}:{name}"

    def _fail(self, exc: BaseException) -> None:
        was_up = self._down_until == 0 or time.time() >= self._down_until
        self._down_until = time.time() + self.retry_seconds
        self.last_error = str(exc) or exc.__class__.__name__
        if was_up:
            logger.warning("Redis is not answering (%s). Carrying on in memory and retrying every %ds.", self.last_error, int(self.retry_seconds))

    async def _do(self, op: str, *args: Any, **kw: Any) -> Any:
        if self.active:
            try:
                out = await getattr(self.redis, op)(*args, **kw)
                if not self._ever_ok or self._down_until:
                    logger.info("Redis is connected (%s).", self.url.split("@")[-1].split("/")[0])
                self._ever_ok, self._down_until, self.last_error = True, 0.0, ""
                return out
            except RedisError as exc:      # a real answer, but an error: bad password, wrong command
                self._fail(exc)
            except _NETWORK_ERRORS as exc:
                self._fail(exc)
        return await getattr(self.memory, op)(*args, **kw)

    # ------------------------------------------------------------------ operations (keys get the prefix)
    async def get(self, name: str) -> str | None:
        return await self._do("get", self.key(name))

    async def set(self, name: str, value: str, ex: float | None = None, nx: bool = False) -> bool:
        return bool(await self._do("set", self.key(name), value, ex=ex, nx=nx))

    async def delete(self, name: str) -> None:
        await self._do("delete", self.key(name))

    async def incr(self, name: str, ex: float | None = None) -> int:
        return int(await self._do("incr", self.key(name), ex=ex))

    async def ttl(self, name: str) -> float:
        return float(await self._do("ttl", self.key(name)))

    async def get_json(self, name: str) -> Any:
        raw = await self.get(name)
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return None

    async def set_json(self, name: str, value: Any, ex: float | None = None) -> None:
        await self.set(name, json.dumps(value, separators=(",", ":")), ex=ex)

    async def get_blob(self, name: str) -> Any:
        """Large JSON, stored compressed."""
        raw = await self.get(name)
        if not raw:
            return None
        try:
            return json.loads(zlib.decompress(base64.b64decode(raw)))
        except Exception:
            return None

    async def set_blob(self, name: str, value: Any, ex: float | None = None) -> int:
        raw = base64.b64encode(zlib.compress(json.dumps(value, separators=(",", ":")).encode(), 6)).decode()
        await self.set(name, raw, ex=ex)
        return len(raw)

    async def cached(self, name: str, ttl: float, factory: Callable[[], Awaitable[Any]]) -> Any:
        """Short-lived shared cache. Only used when Redis is on, so single-instance behaviour is unchanged."""
        if not self.configured or ttl <= 0:
            return await factory()
        hit = await self.get_json(f"cache:{name}")
        if hit is not None:
            return hit["v"]
        value = await factory()
        try:
            await self.set_json(f"cache:{name}", {"v": value}, ex=ttl)
        except (TypeError, ValueError):
            pass
        return value

    # ------------------------------------------------------------------ locks
    async def lock_acquire(self, name: str, token: str, ttl: float) -> bool:
        return await self._do("set", self.key(f"lock:{name}"), token, ex=ttl, nx=True)

    async def lock_renew(self, name: str, token: str, ttl: float) -> bool:
        return bool(await self._do("renew", self.key(f"lock:{name}"), token, ttl))

    async def lock_release(self, name: str, token: str) -> None:
        await self._do("release", self.key(f"lock:{name}"), token)

    # ------------------------------------------------------------------ pub/sub
    async def publish(self, channel: str, message: str) -> None:
        """Goes to every instance (including this one). Dropped quietly when Redis is not there."""
        if not self.active:
            return
        try:
            await self.redis.conn.command("PUBLISH", self.key(channel), message)  # type: ignore[union-attr]
            self._ever_ok = True
        except (RedisError, *_NETWORK_ERRORS) as exc:
            self._fail(exc)

    def subscribe(self, channel: str, callback: Callable[[str], Awaitable[None] | None]) -> None:
        self._subs.setdefault(channel, []).append(callback)
        if self.configured and (self._sub_task is None or self._sub_task.done()) and not self._stopping:
            self._sub_task = asyncio.ensure_future(self._listen())

    async def _listen(self) -> None:
        """Keeps one subscription connection open; reconnects forever. A dropped link only pauses cross-instance events."""
        assert self.redis is not None
        while not self._stopping:
            conn = _Conn(self.url, self._timeout)
            try:
                await conn.open()
                chans = {self.key(c): c for c in self._subs}
                await conn.send_only("SUBSCRIBE", *chans)
                while True:
                    msg = await conn.read_reply()
                    if isinstance(msg, list) and len(msg) >= 3 and msg[0] == "message":
                        for cb in self._subs.get(chans.get(msg[1], ""), []):
                            try:
                                res = cb(msg[2])
                                if asyncio.iscoroutine(res):
                                    await res
                            except Exception:
                                logger.exception("A Redis subscriber failed")
            except asyncio.CancelledError:
                await conn.close()
                raise
            except (RedisError, *_NETWORK_ERRORS) as exc:
                logger.debug("Redis subscription dropped: %s", exc)
            finally:
                await conn.close()
            await asyncio.sleep(3)

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if not self.configured:
            logger.info("Redis: off (REDIS_URL is empty). Everything runs in memory.")
            return
        try:
            await self.redis.conn.command("PING")  # type: ignore[union-attr]
            self._ever_ok = True
            logger.info("Redis: connected.")
        except (RedisError, *_NETWORK_ERRORS) as exc:
            self._fail(exc)

    async def stop(self) -> None:
        self._stopping = True
        if self._sub_task:
            self._sub_task.cancel()
            await asyncio.gather(self._sub_task, return_exceptions=True)
        if self.redis:
            await self.redis.conn.close()


# ============================================================================================ leader election
class Leader:
    """Exactly one running instance is the leader: it polls chat, runs the scheduler and polls Telegram.

    Without Redis there is one instance, so it is always the leader. With Redis the leader holds a lock that it renews;
    if it dies, another instance takes over within `ttl` seconds.
    """

    def __init__(self, shared: Shared, name: str = "leader", ttl: float = 30.0,
                 on_gain: Callable[[], Awaitable[None]] | None = None, on_lose: Callable[[], Awaitable[None]] | None = None) -> None:
        self.shared = shared
        self.name = name
        self.ttl = max(6.0, ttl)
        self.on_gain = on_gain
        self.on_lose = on_lose
        self.token = secrets.token_hex(8)
        self.is_leader = False
        self._task: asyncio.Task | None = None

    async def step(self) -> None:
        """One election round. Public so tests can drive it."""
        if not self.shared.configured:
            if not self.is_leader:
                await self._gain()
            return
        if self.is_leader:
            if await self.shared.lock_renew(self.name, self.token, self.ttl):
                return
            if await self.shared.lock_acquire(self.name, self.token, self.ttl):   # lock expired during a blip: take it back quietly
                return
            await self._lose()
        elif await self.shared.lock_acquire(self.name, self.token, self.ttl):
            await self._gain()

    async def _gain(self) -> None:
        self.is_leader = True
        logger.info("This instance (%s) is now the leader.", self.shared.instance_id)
        if self.on_gain:
            await self.on_gain()

    async def _lose(self) -> None:
        self.is_leader = False
        logger.warning("This instance (%s) is no longer the leader; another one took over.", self.shared.instance_id)
        if self.on_lose:
            await self.on_lose()

    async def start(self) -> None:
        await self.step()
        if self.shared.configured and self._task is None:
            self._task = asyncio.ensure_future(self._loop())

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.ttl / 3)
            try:
                await self.step()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Leader election round failed")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self.is_leader and self.shared.configured:
            await self.shared.lock_release(self.name, self.token)   # hand over at once instead of waiting for the lock to expire
        self.is_leader = False
