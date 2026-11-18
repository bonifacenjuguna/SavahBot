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


@e2e
async def test_lessons_api_teach_list_flip_forget_snapshot_and_auth(api):
    assert (await api.call("GET", "/api/knowledge/lessons", auth=False))[0] == 401
    assert (await api.call("POST", "/api/knowledge/lessons", {"label": "maybe", "text": "x"}))[0] == 422
    st, res = await api.call("POST", "/api/knowledge/lessons", {"label": "spam", "text": "free robux click my profile now"})
    assert st == 200 and res["status"] == "added" and res["counts"]["spam"] == 1
    st, lst = await api.call("GET", "/api/knowledge/lessons?label=spam&q=robux")
    assert st == 200 and lst["total"] == 1
    lid = lst["items"][0]["id"]
    st, flip = await api.call("POST", f"/api/knowledge/lessons/{lid}/flip")
    assert st == 200 and flip["label"] == "ham"
    st, snap = await api.call("POST", "/api/knowledge/snapshots", {"name": "Before cleanup"})
    assert st == 200 and snap["count"] == 1
    assert (await api.call("DELETE", f"/api/knowledge/lessons/{lid}"))[0] == 200
    assert (await api.call("DELETE", f"/api/knowledge/lessons/{lid}"))[0] == 404
    assert (await api.call("POST", f"/api/knowledge/snapshots/{snap['id']}/restore"))[1]["restored"] == 1
    st, q = await api.call("GET", "/api/knowledge/learning/quality")
    assert st == 200 and q["counts"]["total"] == 1 and "timeline" in q
    assert (await api.call("GET", "/api/knowledge/learning/queue"))[0] == 200
    st, exp = await api.call("GET", "/api/knowledge/lessons/export")
    assert st == 200
    st, bulk = await api.call("POST", "/api/knowledge/suggestions/bulk", {"ids": [999], "action": "dismiss"})
    assert st == 200 and bulk["failed"] == 1
    assert (await api.call("POST", "/api/knowledge/learning/reset"))[1]["cleared"] == 1


@e2e
async def test_knowledge_health_hits_and_bundle_round_trip(api):
    st, h = await api.call("GET", "/api/knowledge/health")
    assert st == 200 and h["checked"] > 10 and "by_kind" in h
    st, hits = await api.call("GET", "/api/knowledge/hits")
    assert st == 200 and hits["total"] >= 0
    await api.call("POST", "/api/knowledge/packs/spam.custom/entries", {"phrases": ["zorbnik tokens"], "weight": 60})
    await api.call("POST", "/api/knowledge/lessons", {"label": "spam", "text": "free robux click my profile now"})
    st, bundle = await api.call("GET", "/api/knowledge/bundle")
    assert st == 200 and bundle["format"] == "savahbot-knowledge" and len(bundle["entries"]) == 1 and len(bundle["lessons"]) == 1
    # a tampered file is refused
    bad = {**bundle, "entries": []}
    assert (await api.call("POST", "/api/knowledge/bundle/import", bad))[0] == 400
    # dry run changes nothing; real import is idempotent
    st, dry = await api.call("POST", "/api/knowledge/bundle/import?dry=1", bundle)
    assert st == 200 and dry["dry_run"] and dry["entries"] == 1
    st, res = await api.call("POST", "/api/knowledge/bundle/import", bundle)
    assert st == 200 and res["entries_added"] == 0 and res["entries_skipped"] == 1
    assert (await api.call("POST", "/api/knowledge/bundle/import", {"format": "other"}))[0] == 400
