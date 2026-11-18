"""Dashboard API for the Knowledge section (Settings > Knowledge). Thin on purpose: the logic lives in app.intel."""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from ..intel import benchmark
from ..intel.core import DETECTORS
from ..moderation import ModInput
from . import schemas as S
from ..store import ValidationFailed
from .routes import ApiError, R, need, parse


def _q_int(request: Request, name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(request.query_params.get(name, default))))
    except ValueError:
        return default


# ---------------------------------------------------------------------------------- overview and packs
@R.add("/knowledge/overview", ["GET"])
async def knowledge_overview(request: Request, c: Any) -> dict:
    return await c.knowledge.overview()


@R.add("/knowledge/categories", ["GET"])
async def knowledge_categories(request: Request, c: Any) -> dict:
    return {"categories": c.knowledge.categories()}


@R.add("/knowledge/packs/{pack_id}", ["GET"])
async def knowledge_pack(request: Request, c: Any) -> dict:
    pid = request.path_params["pack_id"]
    pack = c.intel.packs.get(pid)
    need(pack is not None, "pack")
    if pack.editable:
        return c.knowledge.entry_list(pid, request.query_params.get("q", ""), _q_int(request, "offset", 0, 0, 1_000_000),
                                      _q_int(request, "limit", 60, 1, 200), request.query_params.get("only", ""))
    payload: dict[str, Any] = {}
    if pack.kind == "facets":
        payload = {"facets": {k: [w[3:] if w.startswith("re:") else w for w in v] for k, v in pack.payload["facets"].items()},
                   "min_groups": pack.payload.get("min_groups", 2), "anchors": pack.payload.get("anchors", [])}
    elif pack.kind == "corpus":
        payload = {"label": pack.payload["label"], "examples": pack.payload["examples"][:200]}
    elif pack.kind == "maps":
        payload = {"letters": pack.payload.get("letters", {}), "sequences": pack.payload.get("sequences", [])}
    return {"pack": c.knowledge.pack_info(pack), "total": 0, "offset": 0, "items": [], "payload": payload}


@R.add("/knowledge/packs/{pack_id}", ["PATCH"])
async def knowledge_pack_update(request: Request, c: Any) -> dict:
    b = await parse(request, S.PackPatch)
    return {"pack": await c.knowledge.set_pack(request.path_params["pack_id"], b.mode, b.scale)}


@R.add("/knowledge/packs/{pack_id}/entries", ["POST"])
async def knowledge_entries_add(request: Request, c: Any) -> dict:
    b = await parse(request, S.EntriesAdd)
    return await c.knowledge.add_entries(request.path_params["pack_id"], b.phrases, b.weight)


@R.add("/knowledge/packs/{pack_id}/entries", ["PATCH"])
async def knowledge_entry_update(request: Request, c: Any) -> dict:
    b = await parse(request, S.EntryPatch)
    return await c.knowledge.set_entry(request.path_params["pack_id"], b.phrase, b.enabled, b.weight)


@R.add("/knowledge/packs/{pack_id}/entries/remove", ["POST"])
async def knowledge_entry_remove(request: Request, c: Any) -> dict:
    b = await parse(request, S.EntryRef)
    return await c.knowledge.remove_entry(request.path_params["pack_id"], b.phrase)


@R.add("/knowledge/packs/{pack_id}/export", ["GET"])
async def knowledge_export(request: Request, c: Any) -> Response:
    pid = request.path_params["pack_id"]
    need(pid in c.intel.packs, "pack")
    return Response(c.knowledge.export_text(pid), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{pid}.txt"'})


# ---------------------------------------------------------------------------------- detectors and the test lab
@R.add("/knowledge/detectors", ["GET"])
async def knowledge_detectors(request: Request, c: Any) -> dict:
    return {"detectors": await c.knowledge.detectors()}


@R.add("/knowledge/detectors/{det}", ["PATCH"])
async def knowledge_detector_update(request: Request, c: Any) -> dict:
    b = await parse(request, S.DetectorPatch)
    return {"detector": await c.knowledge.set_detector(request.path_params["det"], b.mode, b.scale)}


@R.add("/knowledge/test", ["POST"])
async def knowledge_test(request: Request, c: Any) -> dict:
    b = await parse(request, S.KnowledgeTest)
    verdict = c.engine.evaluate(ModInput("test", "knowledge-test", b.author, b.text, "everyone", 0.0), stateless=True)
    return {"verdict": verdict.to_dict(), "trace": c.knowledge.test(b.text, b.author), "reacts": c.intel.probe(b.text, b.author),
            "detectors": {k: v["title"] for k, v in DETECTORS.items()}}


@R.add("/knowledge/benchmark", ["POST"])
async def knowledge_benchmark(request: Request, c: Any) -> dict:
    return benchmark.run(c.engine, c.cfg)


# ---------------------------------------------------------------------------------- learning
@R.add("/knowledge/learning", ["GET"])
async def knowledge_learning(request: Request, c: Any) -> dict:
    return {"stats": await c.learning.stats(), "suggestions": await c.learning.suggestions("new"), "log": await c.learning.log(40)}


@R.add("/knowledge/learning/refresh", ["POST"])
async def knowledge_learning_refresh(request: Request, c: Any) -> dict:
    res = await c.learning.refresh()
    return res | {"suggestions": await c.learning.suggestions("new")}


@R.add("/knowledge/suggestions/{sid:int}/accept", ["POST"])
async def knowledge_suggestion_accept(request: Request, c: Any) -> dict:
    return await c.learning.accept(request.path_params["sid"])


@R.add("/knowledge/suggestions/{sid:int}/dismiss", ["POST"])
async def knowledge_suggestion_dismiss(request: Request, c: Any) -> dict:
    return await c.learning.dismiss(request.path_params["sid"])


@R.add("/knowledge/log/{lid:int}/undo", ["POST"])
async def knowledge_log_undo(request: Request, c: Any) -> dict:
    return await c.learning.undo(request.path_params["lid"])


# ---------------------------------------------------------------------------------- live data
@R.add("/knowledge/feeds", ["GET"])
async def knowledge_feeds(request: Request, c: Any) -> dict:
    return {"feeds": c.feeds.list(), "summary": c.feeds.summary()}


@R.add("/knowledge/feeds", ["POST"])
async def knowledge_feed_add(request: Request, c: Any) -> dict:
    b = await parse(request, S.FeedAdd)
    res = await c.feeds.add_custom(b.title, b.url, b.format)
    return res | {"feeds": c.feeds.list()}


@R.add("/knowledge/feeds/{fid}", ["PATCH"])
async def knowledge_feed_update(request: Request, c: Any) -> dict:
    b = await parse(request, S.FeedPatch)
    await c.feeds.set_enabled(request.path_params["fid"], b.enabled)
    return {"feeds": c.feeds.list()}


@R.add("/knowledge/feeds/{fid}/refresh", ["POST"])
async def knowledge_feed_refresh(request: Request, c: Any) -> dict:
    b = await parse(request, S.FeedRefresh)
    res = await c.feeds.refresh(request.path_params["fid"], force=b.force)
    return res | {"feeds": c.feeds.list()}


@R.add("/knowledge/feeds/{fid}/rollback", ["POST"])
async def knowledge_feed_rollback(request: Request, c: Any) -> dict:
    res = await c.feeds.rollback(request.path_params["fid"])
    return res | {"feeds": c.feeds.list()}


@R.add("/knowledge/feeds/{fid}/delete", ["POST"])
async def knowledge_feed_delete(request: Request, c: Any) -> dict:
    await c.feeds.remove_custom(request.path_params["fid"])
    return {"feeds": c.feeds.list()}


# ---------------------------------------------------------------------------------- lessons (what the bot was taught)
@R.add("/knowledge/lessons", ["GET"])
async def knowledge_lessons(request: Request, c: Any) -> dict:
    q = request.query_params
    return await c.learning.ledger.search(q.get("label", ""), q.get("source", ""), q.get("q", ""), _q_int(request, "offset", 0, 0, 1_000_000),
                                          _q_int(request, "limit", 40, 1, 200))


@R.add("/knowledge/lessons", ["POST"])
async def knowledge_teach(request: Request, c: Any) -> dict:
    b = await parse(request, S.Teach)
    text, author, demo = b.text, b.author, False
    if b.action_id is not None:
        a = await c.store.get_action(b.action_id)
        need(a is not None, "moderation record")
        text, author, demo = a.get("body") or text, a.get("author_name") or author, bool(a.get("demo"))
    res = await c.learning.teach(text, b.label, "teach", author=author, action_id=b.action_id, demo=demo)
    return {**res, "counts": await c.learning.ledger.counts()}


@R.add("/knowledge/lessons/{lid:int}", ["DELETE"])
async def knowledge_forget(request: Request, c: Any) -> dict:
    need(await c.learning.forget(request.path_params["lid"]), "lesson")
    return {"ok": True}


@R.add("/knowledge/lessons/{lid:int}/flip", ["POST"])
async def knowledge_flip(request: Request, c: Any) -> dict:
    row = await c.learning.relabel(request.path_params["lid"])
    need(row is not None, "lesson")
    return {"ok": True, "label": row["label"]}


@R.add("/knowledge/lessons/export", ["GET"])
async def knowledge_lessons_export(request: Request, c: Any) -> Response:
    import json
    body = json.dumps(await c.learning.ledger.export(), indent=1)
    return Response(body, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="savahbot-lessons.json"'})


@R.add("/knowledge/lessons/import", ["POST"])
async def knowledge_lessons_import(request: Request, c: Any) -> dict:
    try:
        data = await request.json()
    except ValueError:
        raise ApiError("Send the lessons file as JSON.", 400) from None
    return await c.learning.import_lessons(data)


@R.add("/knowledge/learning/quality", ["GET"])
async def knowledge_quality(request: Request, c: Any) -> dict:
    return await c.learning.quality()


@R.add("/knowledge/learning/queue", ["GET"])
async def knowledge_queue(request: Request, c: Any) -> dict:
    return await c.learning.queue(_q_int(request, "limit", 12, 1, 40))


@R.add("/knowledge/learning/reset", ["POST"])
async def knowledge_learning_reset(request: Request, c: Any) -> dict:
    return {"ok": True, "cleared": await c.learning.reset()}


@R.add("/knowledge/snapshots", ["GET"])
async def knowledge_snapshots(request: Request, c: Any) -> dict:
    return {"items": await c.learning.ledger.snapshots()}


@R.add("/knowledge/snapshots", ["POST"])
async def knowledge_snapshot_create(request: Request, c: Any) -> dict:
    b = await parse(request, S.SnapshotName)
    return await c.learning.ledger.snapshot(b.name)


@R.add("/knowledge/snapshots/{sid:int}/restore", ["POST"])
async def knowledge_snapshot_restore(request: Request, c: Any) -> dict:
    return {"ok": True, "restored": await c.learning.restore(request.path_params["sid"])}


@R.add("/knowledge/snapshots/{sid:int}", ["DELETE"])
async def knowledge_snapshot_delete(request: Request, c: Any) -> dict:
    need(await c.learning.ledger.delete_snapshot(request.path_params["sid"]), "snapshot")
    return {"ok": True}


@R.add("/knowledge/suggestions/bulk", ["POST"])
async def knowledge_suggestions_bulk(request: Request, c: Any) -> dict:
    b = await parse(request, S.BulkSuggestions)
    done = failed = 0
    for sid in dict.fromkeys(b.ids):
        try:
            await (c.learning.accept(sid) if b.action == "accept" else c.learning.dismiss(sid))
            done += 1
        except (KeyError, ValidationFailed):
            failed += 1
    return {"done": done, "failed": failed}


# ---------------------------------------------------------------------------------- tools: health, hits, bundle
@R.add("/knowledge/health", ["GET"])
async def knowledge_health(request: Request, c: Any) -> dict:
    from ..intel import tools
    return tools.pack_health(c.knowledge)


@R.add("/knowledge/hits", ["GET"])
async def knowledge_hits(request: Request, c: Any) -> dict:
    from ..intel import tools
    return await tools.hit_stats(c.knowledge)


@R.add("/knowledge/bundle", ["GET"])
async def knowledge_bundle_export(request: Request, c: Any) -> Response:
    import json
    from ..intel import tools
    body = json.dumps(await tools.export_bundle(c.knowledge, request.query_params.get("lessons", "1") != "0"), indent=1)
    return Response(body, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="savahbot-knowledge.json"'})


@R.add("/knowledge/bundle/import", ["POST"])
async def knowledge_bundle_import(request: Request, c: Any) -> dict:
    from ..intel import tools
    try:
        data = await request.json()
    except ValueError:
        raise ApiError("Send the bundle as JSON.", 400) from None
    await c.learning.ledger.snapshot("Before bundle import") if request.query_params.get("dry") != "1" else None
    return await tools.import_bundle(c.knowledge, data, dry_run=request.query_params.get("dry") == "1")
