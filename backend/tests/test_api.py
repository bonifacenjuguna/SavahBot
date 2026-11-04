"""End-to-end: boots the real ASGI app under uvicorn and drives every route over real HTTP."""
import asyncio
import json
import socket

import functools
from contextlib import asynccontextmanager

import uvicorn

from app.config import Settings
from app.container import Container
from app.http import request_json, request_raw
from app.main import create_app

PASSWORD = "correct horse battery"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Api:
    def __init__(self, base, token=None):
        self.base, self.token = base, token

    async def call(self, method, path, body=None, auth=True, **kw):
        headers = {"Authorization": f"Bearer {self.token}"} if auth and self.token else {}
        return await request_json(method, self.base + path, json_body=body, headers=headers, **kw)


@asynccontextmanager
async def booted(tmp_path):
    port = free_port()
    settings = Settings(env={"DATABASE_URL": f"sqlite:///{tmp_path}/t.db", "OWNER_PASSWORD": PASSWORD, "BOT_MODE": "demo",
                             "DEMO_AUTOSTART": "false", "FRONTEND_URL": "https://dash.example.app"}, env_file="")
    container = Container(settings)
    app = create_app(container)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    task = asyncio.ensure_future(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started
    a = Api(f"http://127.0.0.1:{port}")
    a.c = container
    st, body = await a.call("POST", "/api/auth/login", {"password": PASSWORD}, auth=False)
    assert st == 200, body
    a.token = body["token"]
    yield a
    server.should_exit = True
    await asyncio.wait_for(task, 10)


def e2e(fn):
    """Run an async test against a freshly booted server (no pytest-asyncio needed)."""
    @functools.wraps(fn)
    def wrapper(tmp_path):
        async def go():
            async with booted(tmp_path) as api:
                await asyncio.wait_for(fn(api), 60)
        asyncio.run(go())
    wrapper.__signature__ = __import__("inspect").signature(lambda tmp_path: None)
    return wrapper


@e2e
async def test_health_and_auth(api):
    st, body = await api.call("GET", "/api/health", auth=False)
    assert st == 200 and body["ok"] and body["mode"] == "demo"
    assert (await api.call("GET", "/api/status", auth=False))[0] == 401
    api2 = Api(api.base, "garbage")
    assert (await api2.call("GET", "/api/status"))[0] == 401
    st, body = await api.call("POST", "/api/auth/login", {"password": "nope"}, auth=False)
    assert st == 401 and "not right" in body["error"]
    st, _ = await api.call("POST", "/api/auth/login", {"nothing": 1}, auth=False)
    assert st == 422
    assert (await api.call("GET", "/api/auth/me"))[0] == 200


@e2e
async def test_cors_allows_only_the_dashboard(api):
    st, _, h = await request_raw("OPTIONS", api.base + "/api/status", headers={
        "Origin": "https://dash.example.app", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
    assert st == 200 and h.get("access-control-allow-origin") == "https://dash.example.app"
    st, _, h = await request_raw("OPTIONS", api.base + "/api/status", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in {k.lower() for k in h}


@e2e
async def test_status_setup_settings(api):
    st, s = await api.call("GET", "/api/status")
    assert st == 200 and s["hub"]["mode"] == "demo" and "telegram" in s and "youtube" in s and s["database"] == "sqlite"
    st, s = await api.call("GET", "/api/setup")
    assert st == 200 and s["requirements"]
    st, s = await api.call("GET", "/api/settings")
    names = {i["name"] for i in s["items"]}
    assert len(names) > 150 and "bot_mode" in names
    secret = next(i for i in s["items"] if i["name"] == "telegram_bot_token")
    assert secret["value"] is None
    st, s = await api.call("PATCH", "/api/settings", {"values": {"mod_mode": "auto"}})
    assert st == 200 and s["items"][0]["value"] == "auto"
    st, s = await api.call("PATCH", "/api/settings", {"values": {"mod_mode": "banana"}})
    assert st == 400
    st, s = await api.call("PATCH", "/api/settings", {"values": {"no_such_setting": 1}})
    assert st == 404
    assert (await api.call("DELETE", "/api/settings/mod_mode"))[0] == 200
    assert api.c.cfg.get("mod_mode") == "suggest"


@e2e
async def test_commands_crud_and_preview(api):
    st, body = await api.call("GET", "/api/commands")
    assert st == 200 and body["items"] and "addcom" in body["builtin"]
    st, body = await api.call("POST", "/api/commands", {"name": "!shoutout", "response": "Hi $(user)!"})
    assert st == 200
    cid = body["item"]["id"]
    assert (await api.call("POST", "/api/commands", {"name": "shoutout", "response": "x"}))[0] == 400
    assert (await api.call("POST", "/api/commands", {"name": "addcom", "response": "x"}))[0] == 400
    st, body = await api.call("PATCH", f"/api/commands/{cid}", {"response": "Yo $(user)", "enabled": False})
    assert st == 200 and body["item"]["response"] == "Yo $(user)" and not body["item"]["enabled"]
    st, body = await api.call("POST", "/api/commands/preview", {"template": "Hi $(user) $(math 2+3)", "user": "Ana"})
    assert st == 200 and "Ana" in body["output"] and "5" in body["output"]
    assert (await api.call("PATCH", "/api/commands/99999", {"response": "x"}))[0] == 404
    assert (await api.call("DELETE", f"/api/commands/{cid}"))[0] == 200
    assert (await api.call("DELETE", f"/api/commands/{cid}"))[0] == 404


@e2e
async def test_timers_quotes_regulars_blacklist(api):
    st, b = await api.call("POST", "/api/timers", {"name": "social", "message": "Follow!", "interval_seconds": 600})
    assert st == 200
    tid = next(t["id"] for t in b["items"] if t["name"] == "social")
    assert (await api.call("POST", "/api/timers", {"name": "x", "message": "y", "interval_seconds": 5}))[0] == 422
    st, b = await api.call("PATCH", f"/api/timers/{tid}", {"enabled": True})
    assert st == 200 and next(t for t in b["items"] if t["id"] == tid)["enabled"]
    assert (await api.call("DELETE", f"/api/timers/{tid}"))[0] == 200

    st, b = await api.call("POST", "/api/quotes", {"body": "Ship it", "author": "me"})
    assert st == 200 and any(q["body"] == "Ship it" for q in b["items"])
    qid = next(q["id"] for q in b["items"] if q["body"] == "Ship it")
    assert (await api.call("DELETE", f"/api/quotes/{qid}"))[0] == 200

    st, b = await api.call("POST", "/api/regulars", {"ident": "UC123", "label": "Ana"})
    assert st == 200 and b["items"]
    rid = b["items"][0]["id"]
    assert (await api.call("DELETE", f"/api/regulars/{rid}"))[0] == 200

    st, b = await api.call("POST", "/api/blacklist", {"phrase": "zorbnik", "weight": 70})
    assert st == 200
    bid = next(i["id"] for i in b["items"] if i["phrase"] == "zorbnik")
    st, b = await api.call("POST", "/api/moderation/test", {"text": "buy zorbnik now"})
    assert st == 200 and b["verdict"]["score"] >= 70
    assert (await api.call("PATCH", f"/api/blacklist/{bid}", {"enabled": False}))[0] == 200
    st, b = await api.call("POST", "/api/moderation/test", {"text": "buy zorbnik now"})
    assert b["verdict"]["score"] < 70
    assert (await api.call("DELETE", f"/api/blacklist/{bid}"))[0] == 200


@e2e
async def test_notes_and_reminders(api):
    st, b = await api.call("POST", "/api/notes", {"body": "Plan the raid", "tags": ["ideas"], "pinned": True})
    assert st == 200 and b["items"][0]["body"] == "Plan the raid"
    nid = b["items"][0]["id"]
    st, b = await api.call("PATCH", f"/api/notes/{nid}", {"body": "Plan the raid v2"})
    assert st == 200 and b["items"][0]["body"] == "Plan the raid v2"
    assert (await api.call("DELETE", f"/api/notes/{nid}"))[0] == 200

    st, b = await api.call("POST", "/api/reminders", {"when": "in 2h", "text": "Stretch"})
    if st != 200:  # accept whichever relative form the parser documents
        st, b = await api.call("POST", "/api/reminders", {"when": "2h", "text": "Stretch"})
    assert st == 200 and b["items"], b
    rid = b["items"][0]["id"]
    assert (await api.call("POST", "/api/reminders", {"when": "garbage words", "text": "x"}))[0] == 400
    assert (await api.call("DELETE", f"/api/reminders/{rid}"))[0] == 200


@e2e
async def test_demo_scenario_moderation_flow_and_analytics(api):
    st, b = await api.call("GET", "/api/demo")
    assert st == 200 and b["active"] and any(s["name"] == "spam_raid" for s in b["scenarios"])
    st, b = await api.call("POST", "/api/demo/scenario", {"name": "link_spammer"})
    assert st == 200
    pending = []
    for _ in range(100):
        st, b = await api.call("GET", "/api/moderation/pending")
        pending = b["items"]
        if pending:
            break
        await asyncio.sleep(0.1)
    assert pending, "the link spammer scenario should queue an approval"
    pid = pending[0]["id"]
    st, b = await api.call("POST", f"/api/moderation/{pid}/approve")
    assert st == 200 and b["item"]["status"] in ("executed", "approved", "done", "simulated")
    st, b = await api.call("POST", f"/api/moderation/{pid}/approve")
    assert st == 409
    st, b = await api.call("GET", "/api/moderation/history")
    assert st == 200 and b["items"]
    st, b = await api.call("GET", "/api/chat/recent?limit=20")
    assert st == 200 and b["items"]
    st, b = await api.call("GET", "/api/analytics?hours=24")
    assert st == 200
    assert (await api.call("POST", "/api/moderation/approve-all"))[0] == 200
    assert (await api.call("POST", "/api/demo/scenario", {"name": "nope"}))[0] == 409
    assert (await api.call("DELETE", "/api/chat/demo"))[0] == 200
    st, b = await api.call("POST", "/api/chat/send", {"text": "hello"})
    assert st in (200, 409)


@e2e
async def test_mode_switch_and_guards(api):
    st, b = await api.call("POST", "/api/mode", {"mode": "live"})
    assert st == 200
    await asyncio.sleep(0.2)
    assert api.c.cfg.get("bot_mode") == "live"
    assert (await api.call("POST", "/api/demo/scenario", {"name": "friendly_chat"}))[0] == 409
    assert (await api.call("POST", "/api/mode", {"mode": "sideways"}))[0] == 400
    st, b = await api.call("POST", "/api/mode", {"mode": "demo"})
    assert st == 200


@e2e
async def test_youtube_account_and_target_are_reported_separately_and_verify_never_claims_success(api):
    st, b = await api.call("GET", "/api/setup")
    assert st == 200 and b["youtube_account"] == {} and b["youtube_target"]["configured"] is False
    assert any(i["env"] == "YOUTUBE_TARGET_CHANNEL_ID" and i["set"] is False for i in b["requirements"]["youtube"])
    st, b = await api.call("GET", "/api/youtube/status")
    assert st == 200 and b["target"]["configured"] is False and b["account"]["channel_id"] == "" and b["permissions"]["delete"] is None
    st, b = await api.call("POST", "/api/youtube/verify")
    assert st == 200 and b["ok"] is False and b["checks"][0]["ok"] is False and "Not connected" in b["checks"][0]["detail"]


@e2e
async def test_integrations_without_credentials(api):
    st, b = await api.call("GET", "/api/youtube/status")
    assert st == 200 and b["connected"] is False
    st, b = await api.call("POST", "/api/youtube/oauth/start")
    assert st == 409 and "GOOGLE_CLIENT_ID" in b["error"]
    st, raw, h = await request_raw("GET", api.base + "/api/youtube/oauth/callback?state=bad&code=x", follow_redirects=False)
    assert st == 303 and "youtube=error" in h.get("location", h.get("Location", ""))
    assert (await api.call("POST", "/api/youtube/disconnect"))[0] == 200
    st, b = await api.call("GET", "/api/telegram/status")
    assert st == 200 and b["configured"] is False
    assert (await api.call("POST", "/api/telegram/test"))[0] == 409
    st, _ = await api.call("POST", "/api/telegram/webhook", {"update_id": 1}, auth=False)
    assert st == 403


@e2e
async def test_sse_stream_delivers_events(api):
    import urllib.request

    def read_events():
        req = urllib.request.Request(api.base + "/api/events", headers={"Authorization": f"Bearer {api.token}"})
        got = []
        with urllib.request.urlopen(req, timeout=10) as r:
            for raw in r:
                line = raw.decode().strip()
                if line.startswith("data:"):
                    got.append(json.loads(line[5:]))
                    if len(got) >= 2:
                        break
        return got

    task = asyncio.ensure_future(asyncio.to_thread(read_events))
    for _ in range(50):
        if api.c.bus.subscriber_count:
            break
        await asyncio.sleep(0.05)
    assert api.c.bus.subscriber_count == 1
    api.c.bus.publish("ping_test", {"n": 1})
    got = await asyncio.wait_for(task, 10)
    assert got[0]["type"] == "hello" and got[1]["type"] == "ping_test"
    for _ in range(50):
        if not api.c.bus.subscriber_count:
            break
        await asyncio.sleep(0.1)
    assert api.c.bus.subscriber_count == 0


@e2e
async def test_youtube_diagnostics_flags_swapped_and_bad_values(api):
    st, b = await api.call("GET", "/api/youtube/diagnostics")
    assert st == 200 and not b["checks"][0]["ok"] and b["sign_in_url"] == ""
    api.c.cfg.settings._values["google_client_id"] = "GOCSPX-abc"
    api.c.cfg.settings._values["google_client_secret"] = "12345.apps.googleusercontent.com"
    st, b = await api.call("GET", "/api/youtube/diagnostics")
    bad = [c["text"] for c in b["checks"] if not c["ok"]]
    assert any("should end in" in t for t in bad) and any("secret normally starts" in t for t in bad)
    assert "GOCSPX-abc" == b["client_id"] and "12345" not in str(b)
    api.c.cfg.settings._values["google_client_id"] = "123-abc.apps.googleusercontent.com"
    api.c.cfg.settings._values["google_client_secret"] = "GOCSPX-xyz"
    api.c.settings._values["public_base_url"] = "https://bot.example.app"
    st, b = await api.call("GET", "/api/youtube/diagnostics")
    assert st == 200 and all(c["ok"] for c in b["checks"]), b["checks"]
    assert "client_id=123-abc.apps.googleusercontent.com" in b["sign_in_url"] and "GOCSPX" not in b["sign_in_url"]
    assert b["redirect_uri"] == "https://bot.example.app/api/youtube/oauth/callback"
