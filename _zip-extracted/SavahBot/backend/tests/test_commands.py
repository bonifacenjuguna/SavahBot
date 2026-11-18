import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.commands import CommandEngine, Ctx, Renderer
from app.commands.safe_math import MathError, calculate
from app.commands.variables import UrlBlocked, check_url
from app.config import StaticConfig
from app.db import Database
from app.models import ChatMessage
from app.moderation import PermitStore
from app.store import Store


def run(coro):
    return asyncio.run(coro)


async def make(cfg=None, uptime=None):
    db = Database(":memory:")
    await db.connect()
    store = Store(db)
    cfg = cfg or StaticConfig()
    permits = PermitStore()
    renderer = Renderer(cfg, store, uptime_fn=lambda: uptime)
    engine = CommandEngine(cfg, store, renderer, permits, uptime_fn=lambda: uptime, channel_fn=lambda: "SavahDemo")
    return cfg, store, engine, permits


def m(text, name="alice", level="everyone", ts=None):
    kw = {"ts": ts} if ts is not None else {}
    return ChatMessage("demo", name.lower(), name, text, level, **kw)


# ---------------------------------------------------------------- safe math
def test_math_basics_and_formatting():
    assert calculate("2 + 3 * 4") == "14"
    assert calculate("(1+2)*3") == "9"
    assert calculate("10 / 4") == "2.5"
    assert calculate("7 // 2") == "3" and calculate("7 % 4") == "3" and calculate("2 ** 10") == "1024"
    assert calculate("-5 + +2") == "-3"
    assert calculate("1/3") == "0.333333"


@pytest.mark.parametrize("bad", ["", "__import__('os').system('id')", "open('x')", "1 +", "2 ** 9999", "9e99 * 9e99",
                                 "1/0", "'a' * 5", "x + 1", "(lambda: 1)()", "[1,2]", "True + 1", "1 if 1 else 2", "9" * 200])
def test_math_rejects_everything_unsafe(bad):
    with pytest.raises(MathError):
        calculate(bad)


# ---------------------------------------------------------------- renderer
def test_variables_basic_and_nested():
    async def go():
        cfg, store, engine, _ = await make(uptime=3725)
        r = engine.renderer
        ctx = Ctx(author_name="Alice", author_id="a1", level="mod", args=["@Bob", "extra"], raw_args="@Bob extra",
                  channel="SavahDemo", command="hello")
        assert await r.render("Hi $(user) -> $(touser), id $(userid), $(userlevel) in $(channel)", ctx) == \
            "Hi Alice -> Bob, id a1, mod in SavahDemo"
        assert await r.render("[$(1)] [$(2)] [$(3)] all=$(args)", ctx) == "[@Bob] [extra] [] all=@Bob extra"
        assert await r.render("$(math 1+$(random 4-4))", ctx) == "5"  # inner variable expands first
        assert await r.render("$(math (1+2)*$(user))", ctx) == "[math: unsupported expression]"
        assert await r.render("Live: $(uptime) / $(botname)", ctx) == "Live: 1h 2m 5s / SavahBot"
        assert await r.render("$(unknownvar x) stays", ctx) == "$(unknownvar x) stays"
        assert await r.render("unclosed $(user", ctx) == "unclosed $(user"
    run(go())


def test_counters_time_countdown_random_choose():
    async def go():
        cfg, store, engine, _ = await make()
        r = engine.renderer
        ctx = Ctx(command="deaths", now=1_000_000.0)
        assert [await r.render("$(count)", ctx) for _ in range(3)] == ["1", "2", "3"]
        assert await r.render("$(count other)", ctx) == "1"
        assert await r.render("$(countdown 1970-01-12 15:00)", Ctx(now=0)) == "11d 12h"  # owner tz is UTC+3 -> 12:00 UTC
        assert await r.render("$(countdown 2000-01-01)", Ctx(now=2_000_000_000.0)) == "now"  # target already passed
        assert await r.render("$(countup 1970-01-01T03:00:00)", Ctx(now=3600)) == "1h"
        assert len(await r.render("$(time Africa/Nairobi)", ctx)) == 5
        assert await r.render("$(time Mars/Base)", ctx) == "[time: invalid input]"
        assert 1 <= int(await r.render("$(random 5-7)", ctx)) <= 7
        assert await r.render("$(random 9-3)", ctx) in {str(i) for i in range(3, 10)}
        assert await r.render("$(choose only)", ctx) == "only"
        assert await r.render("$(choose a|b|c)", ctx) in {"a", "b", "c"}
    run(go())


def test_render_limits_and_truncation():
    async def go():
        cfg, store, engine, _ = await make(StaticConfig({"command_max_expansions": 3, "command_max_response_length": 20}))
        r = engine.renderer
        out = await r.render("$(user)$(user)$(user)$(user)", Ctx(author_name="x"))
        assert out == "xxx$(user)"
        assert len(await r.render("a" * 100, Ctx())) == 20
        cfg.set("command_max_response_length", 200)
        cfg.set("command_max_expansions", 25)
        cfg.set("command_max_render_depth", 1)
        assert await r.render("$(math 1+$(math 1+$(math 1+1)))", Ctx()) != "4"  # depth cap stops deep nesting
    run(go())


def test_quote_variable():
    async def go():
        cfg, store, engine, _ = await make()
        ctx = Ctx()
        assert await engine.renderer.render("$(quote)", ctx) == "no quotes yet"
        await store.add_quote("be kind")
        assert await engine.renderer.render("$(quote 1)", ctx) == "be kind"
    run(go())


# ---------------------------------------------------------------- urlfetch / SSRF
class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data")
            self.end_headers()
            return
        body = f"hello {self.path}  from\n server".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture()
def local_server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_urlfetch_blocks_internal_addresses_by_default(local_server):
    async def go():
        cfg, store, engine, _ = await make()
        out = await engine.renderer.render(f"$(urlfetch {local_server}/x)", Ctx())
        assert out == "[urlfetch: private or internal addresses are blocked]"
        for url in ("http://169.254.169.254/latest", "http://10.0.0.5/", "http://[::1]/", "file:///etc/passwd", "ftp://x.test/"):
            with pytest.raises(UrlBlocked):
                await check_url(url, cfg)
    run(go())


def test_urlfetch_works_when_allowed_and_never_follows_redirects(local_server):
    async def go():
        cfg, store, engine, _ = await make(StaticConfig({"urlfetch_block_private": False}))
        assert await engine.renderer.render(f"$(urlfetch {local_server}/hi/$(user))", Ctx(author_name="Al")) == \
            "hello /hi/Al from server"
        assert await engine.renderer.render(f"$(urlfetch {local_server}/redir)", Ctx()) == "[urlfetch: server answered 302]"
        cfg.set("urlfetch_allowed_hosts", "example.com")
        assert "allow-list" in await engine.renderer.render(f"$(urlfetch {local_server}/x)", Ctx())
        cfg.set("urlfetch_allowed_hosts", "")
        cfg.set("urlfetch_enabled", False)
        assert "turned off" in await engine.renderer.render(f"$(urlfetch {local_server}/x)", Ctx())
    run(go())


# ---------------------------------------------------------------- dispatcher
def test_custom_command_levels_aliases_and_cooldowns():
    async def go():
        cfg, store, engine, _ = await make()
        await store.create_command("hello", "Hi $(user)!", cooldown=60, user_cooldown=0, aliases=["hi"])
        await store.create_command("modonly", "secret", userlevel="mod", cooldown=0, user_cooldown=0)
        await store.create_command("off", "disabled", enabled=False, cooldown=0)
        assert await engine.handle(m("!hello")) == ["Hi alice!"]
        assert await engine.handle(m("!hello", "bob")) == []          # global cooldown
        assert await engine.handle(m("!hi", "owner1", "owner")) == ["Hi owner1!"]  # owner bypasses cooldown, alias works
        assert await engine.handle(m("!modonly")) == []
        assert await engine.handle(m("!modonly", "mo", "mod")) == ["secret"]
        assert await engine.handle(m("!off", level="owner")) == []
        assert await engine.handle(m("!nothing")) == []
        assert await engine.handle(m("hello there")) == []
        assert (await store.find_command("hello"))["uses"] == 2
        bot = m("!hello", "bot1")
        bot.from_bot = True
        assert await engine.handle(bot) == []
        old = m("!hello", "x")
        old.backfill = True
        assert await engine.handle(old) == []
    run(go())


def test_user_cooldown_is_per_user():
    async def go():
        cfg, store, engine, _ = await make()
        await store.create_command("ping", "pong", cooldown=0, user_cooldown=60)
        assert await engine.handle(m("!ping", "a")) == ["pong"]
        assert await engine.handle(m("!ping", "a")) == []
        assert await engine.handle(m("!ping", "b")) == ["pong"]
    run(go())


def test_builtin_commands_and_mod_permissions():
    async def go():
        cfg, store, engine, permits = await make(uptime=125)
        assert await engine.handle(m("!addcom !hi Hello", level="everyone")) == []         # not a mod: silent
        assert await engine.handle(m("!addcom !hi Hello there", "mo", "mod")) == ["Added !hi."]
        assert await engine.handle(m("!addcom !hi again", "mo", "mod")) == ["!hi already exists."]
        assert await engine.handle(m("!editcom hi Hello $(user)", "mo", "mod")) == ["Updated !hi."]
        assert await engine.handle(m("!hi", "zed")) == ["Hello zed"]
        assert await engine.handle(m("!addcom !quote x", "mo", "mod")) == ["!quote is built in and cannot be changed."]
        bad = await engine.handle(m("!addcom !bad! x", "mo", "mod"))
        assert len(bad) == 1 and bad[0].startswith("Name may use letters")
        assert (await engine.handle(m("!commands")))[0].startswith("Commands: !hi")
        assert await engine.handle(m("!delcom hi", "mo", "mod")) == ["Removed !hi."]
        assert await engine.handle(m("!delcom hi", "mo", "mod")) == ["!hi does not exist."]

        assert await engine.handle(m("!uptime")) == ["Live for 2m 5s."]
        assert "offline" in (await (await make())[2].handle(m("!uptime")))[0]

        assert "No quotes yet" in (await engine.handle(m("!quote")))[0]
        assert await engine.handle(m("!addquote wise words", "mo", "mod")) == ["Quote #1 added."]
        assert await engine.handle(m("!quote 1")) == ["“wise words” — mo"]
        assert await engine.handle(m("!addquote nope")) == []

        assert await engine.handle(m("!permit Bob 30", "mo", "mod")) == ["@Bob can post links for 30s."]
        assert permits.is_permitted("bob")
        assert await engine.handle(m("!permit", "mo", "mod")) == ["Usage: !permit <user> [seconds]"]
        assert await engine.handle(m("!permit Eve", "mo", "mod")) == ["@Eve can post links for 60s."]
    run(go())


def test_only_owner_may_create_urlfetch_commands():
    async def go():
        cfg, store, engine, _ = await make()
        msg = "Only the owner can use $(urlfetch) in a command."
        assert await engine.handle(m("!addcom !w $(urlfetch https://x.test/$(1))", "mo", "mod")) == [msg]
        assert await engine.handle(m("!addcom !w $(URLFETCH https://x.test/)", "mo", "mod")) == [msg]
        assert await engine.handle(m("!addcom !w $(urlfetch https://x.test/)", "boss", "owner")) == ["Added !w."]
        assert await engine.handle(m("!editcom w $(urlfetch https://evil.test/)", "mo", "mod")) == [msg]
    run(go())


def test_custom_prefix_and_preview():
    async def go():
        cfg, store, engine, _ = await make(StaticConfig({"command_prefix": "?"}))
        await store.create_command("hi", "hello $(touser)", cooldown=0, user_cooldown=0)
        assert await engine.handle(m("!hi")) == []
        assert await engine.handle(m("?hi bob")) == ["hello bob"]
        assert await engine.preview("Hey $(user) $(1)", m("x", "Zed"), "there") == "Hey Zed there"
    run(go())
