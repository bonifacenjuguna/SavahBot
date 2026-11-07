"""The Knowledge API: the real handlers, run through the real route registry (auth, validation, error mapping)."""
import asyncio
import json
import time

from app.api.routes import R
from app.config import Settings
from app.container import Container
from app.intel import feeds as feeds_mod

PASSWORD = "correct horse battery"


class Req:
    """Just enough of a Starlette request for the registry's endpoints."""

    def __init__(self, c, method, body=None, query=None, params=None, token=None, path="/"):
        self.method, self._body, self.query_params, self.path_params = method, body, query or {}, params or {}
        self.headers = {"authorization": f"Bearer {token}"} if token else {}
        self.url = type("U", (), {"path": path})()
        self.client = None
        self.app = type("A", (), {"state": type("S", (), {"c": c})()})()

    async def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class Client:
    def __init__(self, c):
        self.c, self.token = c, c.auth.issue_token()[0]

    async def call(self, method, template, body=None, query=None, auth=True, **params):
        route = next(r for r in R.routes if r.path == "/api" + template and method in r.methods)
        resp = await route.endpoint(Req(self.c, method, body, query, params, self.token if auth else None, path=template))
        raw = resp.body if isinstance(resp.body, (str, bytes)) else b""
        text = raw.decode() if isinstance(raw, bytes) else raw
        ctype = getattr(resp, "media_type", "") or ""
        return resp.status_code, (json.loads(text) if "json" in ctype else text)


def boot(fn):
    def wrapper(tmp_path):
        async def go():
            c = Container(Settings(env={"DATABASE_URL": f"sqlite:///{tmp_path}/t.db", "OWNER_PASSWORD": PASSWORD, "BOT_MODE": "demo",
                                        "DEMO_AUTOSTART": "false", "INTEL_FEED_STARTUP_DELAY_SECONDS": "99999"}, env_file=""))
            await c.start()
            try:
                await fn(Client(c))
            finally:
                await c.stop()
        asyncio.run(go())
    return wrapper


@boot
async def test_everything_needs_the_owner_token(api):
    for method, path in (("GET", "/knowledge/overview"), ("GET", "/knowledge/detectors"), ("POST", "/knowledge/benchmark"),
                         ("GET", "/knowledge/feeds"), ("GET", "/knowledge/learning")):
        st, _ = await api.call(method, path, auth=False)
        assert st == 401, path


@boot
async def test_overview_categories_and_detectors(api):
    st, ov = await api.call("GET", "/knowledge/overview")
    assert st == 200 and ov["status"]["packs_active"] >= 30 and ov["detectors"] and ov["feeds"]["total"] >= 5
    st, cats = await api.call("GET", "/knowledge/categories")
    assert {c["id"] for c in cats["categories"]} >= {"scams", "spam", "abuse", "links", "languages", "safe", "normalize", "corpus"}
    st, dets = await api.call("GET", "/knowledge/detectors")
    ids = {d["id"] for d in dets["detectors"]}
    assert {"scam", "harassment", "typo", "link_risk", "intent", "raid_wave"} <= ids


@boot
async def test_pack_views_for_every_kind(api):
    st, p = await api.call("GET", "/knowledge/packs/{pack_id}", pack_id="scams.giveaway", query={"q": "robux", "limit": "5"})
    assert st == 200 and p["items"] and len(p["items"]) <= 5 and p["pack"]["editable"]
    assert (await api.call("GET", "/knowledge/packs/{pack_id}", pack_id="scams.intent_facets"))[1]["payload"]["facets"]["money"]
    assert (await api.call("GET", "/knowledge/packs/{pack_id}", pack_id="corpus.spam_examples"))[1]["payload"]["label"] == "spam"
    assert (await api.call("GET", "/knowledge/packs/{pack_id}", pack_id="normalize.confusables"))[1]["payload"]["letters"]
    assert (await api.call("GET", "/knowledge/packs/{pack_id}", pack_id="nope.nothing"))[0] == 404


@boot
async def test_edit_a_pack_and_see_it_work(api):
    t = {"text": "buy zorbnik tokens at the bazaar"}
    assert (await api.call("POST", "/knowledge/test", t))[1]["verdict"]["score"] == 0
    st, res = await api.call("POST", "/knowledge/packs/{pack_id}/entries", {"phrases": ["zorbnik tokens"], "weight": 60}, pack_id="spam.custom")
    assert st == 200 and res["added"] == 1
    st, out = await api.call("POST", "/knowledge/test", t)
    assert out["verdict"]["score"] >= 55 and out["trace"]["matches"][0]["pack"] == "spam.custom"
    assert "spam" in out["reacts"] and out["verdict"]["signals"][0]["why"]
    assert (await api.call("PATCH", "/knowledge/packs/{pack_id}/entries", {"phrase": "zorbnik tokens", "enabled": False}, pack_id="spam.custom"))[0] == 200
    assert (await api.call("POST", "/knowledge/test", t))[1]["verdict"]["score"] == 0
    assert (await api.call("POST", "/knowledge/packs/{pack_id}/entries/remove", {"phrase": "zorbnik tokens"}, pack_id="spam.custom"))[0] == 200
    st, text = await api.call("GET", "/knowledge/packs/{pack_id}/export", pack_id="scams.giveaway")
    assert st == 200 and "free robux" in text
    st, e = await api.call("POST", "/knowledge/packs/{pack_id}/entries", {"phrases": ["re:(broken"]}, pack_id="spam.custom")
    assert st == 400 and "pattern" in e["error"]


@boot
async def test_pack_and_detector_switches_and_bad_input(api):
    st, p = await api.call("PATCH", "/knowledge/packs/{pack_id}", {"mode": "off"}, pack_id="scams.crypto")
    assert st == 200 and p["pack"]["mode"] == "off"
    assert (await api.call("PATCH", "/knowledge/packs/{pack_id}", {"mode": "bogus"}, pack_id="scams.crypto"))[0] == 400
    assert (await api.call("PATCH", "/knowledge/packs/{pack_id}", {"scale": 9}, pack_id="scams.crypto"))[0] == 422
    assert (await api.call("PATCH", "/knowledge/packs/{pack_id}", {"surprise": 1}, pack_id="scams.crypto"))[0] == 422
    assert (await api.call("PATCH", "/knowledge/packs/{pack_id}", {}, pack_id="nope.none"))[0] in (404, 400)
    st, d = await api.call("PATCH", "/knowledge/detectors/{det}", {"mode": "shadow", "scale": 0.5}, det="scam")
    assert st == 200 and d["detector"]["mode"] == "shadow" and d["detector"]["scale"] == 0.5
    assert api.c.cfg.get("intel_scam_mode") == "shadow"
    assert (await api.call("PATCH", "/knowledge/detectors/{det}", {"mode": "loud"}, det="scam"))[0] == 400
    assert (await api.call("PATCH", "/knowledge/detectors/{det}", {"mode": "live"}, det="nope"))[0] == 404


@boot
async def test_benchmark_endpoint(api):
    st, r = await api.call("POST", "/knowledge/benchmark")
    assert st == 200 and r["with_intel"]["recall_flag"] >= 0.95 and r["with_intel"]["false_alarm_delete"] == 0
    assert r["with_intel"]["recall_flag"] > r["without_intel"]["recall_flag"]


@boot
async def test_learning_flow_over_the_api(api):
    c = api.c
    for i in range(4):
        await c.db.execute("INSERT INTO mod_actions (ts, platform, author_id, author_name, body, score, reasons, action, status, demo) "
                           "VALUES (?, 'youtube', ?, ?, ?, 60, '[]', 'delete', 'executed', 0)", (time.time(), f"acc{i}", f"acc{i}", f"visit blorptastic shop today {i}"))
    st, res = await api.call("POST", "/knowledge/learning/refresh")
    assert st == 200 and res["new"] >= 1
    st, learn = await api.call("GET", "/knowledge/learning")
    assert learn["stats"]["decisions"] == 4 and learn["suggestions"]
    sid = next(s for s in learn["suggestions"] if "blorptastic" in s["body"])["id"]
    st, acc = await api.call("POST", "/knowledge/suggestions/{sid:int}/accept", sid=sid)
    assert st == 200
    assert (await api.call("POST", "/knowledge/suggestions/{sid:int}/accept", sid=sid))[0] == 400
    st, learn = await api.call("GET", "/knowledge/learning")
    assert learn["log"][0]["summary"].startswith("Added")
    assert (await api.call("POST", "/knowledge/log/{lid:int}/undo", lid=acc["log_id"]))[0] == 200
    assert (await api.call("POST", "/knowledge/suggestions/{sid:int}/dismiss", sid=999999))[0] == 404


class Net:
    status, body, headers = 200, b"", {}

    async def __call__(self, method, url, headers=None, **kw):
        return self.status, self.body, dict(self.headers)


@boot
async def test_feeds_over_the_api(api):
    net = Net()
    net.body = ("0.0.0.0 evil-one.tracker-site.org\n" * 1 + "\n".join(f"0.0.0.0 bad{i}.tracker-site.org" for i in range(60))).encode()
    feeds_mod.request_raw = net
    st, f = await api.call("GET", "/knowledge/feeds")
    assert st == 200 and len(f["feeds"]) >= 5 and f["summary"]["total"] >= 5
    st, r = await api.call("POST", "/knowledge/feeds/{fid}/refresh", {}, fid="urlhaus_hosts")
    assert st == 200 and r["ok"] and r["entries"] == 61
    feed = next(x for x in r["feeds"] if x["id"] == "urlhaus_hosts")
    assert feed["status"] == "ok" and feed["entries"] == 61
    st, out = await api.call("POST", "/knowledge/test", {"text": "see http://bad7.tracker-site.org/login"})
    assert "link_risk" in {s["name"] for s in out["verdict"]["signals"]}
    assert (await api.call("PATCH", "/knowledge/feeds/{fid}", {"enabled": False}, fid="urlhaus_hosts"))[0] == 200
    assert (await api.call("POST", "/knowledge/feeds/{fid}/rollback", fid="urlhaus_hosts"))[0] == 400
    assert (await api.call("POST", "/knowledge/feeds/{fid}/refresh", {}, fid="nope"))[0] == 404
    assert (await api.call("POST", "/knowledge/feeds", {"title": "x", "url": "http://127.0.0.1/a", "format": "domains"}))[0] == 400
    assert (await api.call("POST", "/knowledge/feeds/{fid}/delete", fid="urlhaus_hosts"))[0] == 404


@boot
async def test_existing_moderation_test_route_gains_the_new_fields(api):
    st, v = await api.call("POST", "/moderation/test", {"text": "double your bitcoin whatsapp me +254712345678"})
    assert st == 200
    body = v.get("verdict", v)
    assert {"score", "action", "signals", "confidence", "shadow"} <= set(body)


@boot
async def test_the_scheduler_drives_the_knowledge_work(api):
    """Counters are saved, and feed and learning work is started, from the scheduler's regular tick."""
    c = api.c
    assert c.knowledge.tick in c.scheduler.hooks
    from app.moderation import ModInput
    c.engine.evaluate(ModInput("youtube", "u1", "viewer", "double your bitcoin whatsapp me +254712345678", "everyone", time.time()))
    assert c.intel.pending["live:scam"] == 1
    c.knowledge._last_flush = 0.0
    await c.scheduler.tick(time.time() + 1)
    assert (await c.knowledge.counters())["intel:live:scam"] == 1 and not c.intel.pending


@boot
async def test_a_failing_hook_never_stops_the_scheduler(api):
    calls = []

    async def bad(now):
        calls.append("bad")
        raise RuntimeError("boom")

    async def good(now):
        calls.append("good")
    api.c.scheduler.hooks[:] = [bad, good]
    await api.c.scheduler.tick(time.time() + 1)
    assert calls == ["bad", "good"]
