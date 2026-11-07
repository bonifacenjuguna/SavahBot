"""Knowledge API over real HTTP (same harness as test_api.py)."""
from test_api import e2e


@e2e
async def test_knowledge_overview_and_edit_over_http(api):
    st, ov = await api.call("GET", "/api/knowledge/overview")
    assert st == 200 and ov["status"]["packs_active"] >= 30
    assert (await api.call("GET", "/api/knowledge/overview", auth=False))[0] == 401
    st, res = await api.call("POST", "/api/knowledge/packs/spam.custom/entries", {"phrases": ["zorbnik tokens"], "weight": 60})
    assert st == 200 and res["added"] == 1
    st, out = await api.call("POST", "/api/knowledge/test", {"text": "buy zorbnik tokens now"})
    assert st == 200 and out["verdict"]["score"] >= 55
    st, p = await api.call("PATCH", "/api/knowledge/packs/spam.custom", {"mode": "off"})
    assert st == 200 and p["pack"]["mode"] == "off"
    assert (await api.call("POST", "/api/knowledge/test", {"text": "buy zorbnik tokens now"}))[1]["verdict"]["score"] == 0


@e2e
async def test_knowledge_detectors_benchmark_and_errors_over_http(api):
    st, d = await api.call("PATCH", "/api/knowledge/detectors/abuse", {"mode": "live"})
    assert st == 200 and d["detector"]["mode"] == "live"
    assert (await api.call("PATCH", "/api/knowledge/detectors/abuse", {"mode": "loud"}))[0] == 400
    assert (await api.call("GET", "/api/knowledge/packs/nope.nothing"))[0] == 404
    st, r = await api.call("POST", "/api/knowledge/benchmark")
    assert st == 200 and r["with_intel"]["recall_flag"] >= 0.95


@e2e
async def test_knowledge_feeds_and_learning_are_reachable(api):
    st, f = await api.call("GET", "/api/knowledge/feeds")
    assert st == 200 and len(f["feeds"]) >= 5
    st, learn = await api.call("GET", "/api/knowledge/learning")
    assert st == 200 and learn["stats"]["decisions"] == 0
    assert (await api.call("POST", "/api/knowledge/learning/refresh"))[0] == 200
