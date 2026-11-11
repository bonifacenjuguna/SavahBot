"""Stream events, subscriber alerts and live stats, against a fake YouTube."""
import asyncio
import time
from types import SimpleNamespace

from app.activity import ActivityLog  # noqa: F401  (registers the schema)
from app.services.live_extras import LiveExtras, _fill, parse_event


def item(type_, **details):
    return {"id": "e1", "snippet": {"type": type_, **details}, "authorDetails": {"channelId": "UC1", "displayName": "Sam"}}


def test_parse_event_kinds_and_no_comment_kept():
    ev = parse_event(item("superChatEvent", superChatDetails={"amountDisplayString": "KES 200", "userComment": "secret words"}))
    assert ev["kind"] == "superchat" and ev["amount"] == "KES 200" and "secret" not in str(ev)
    assert parse_event(item("membershipGiftingEvent", membershipGiftingDetails={"giftMembershipsCount": 5}))["count"] == 5
    assert parse_event(item("newSponsorEvent"))["kind"] == "member"
    assert parse_event(item("textMessageEvent")) is None


def test_fill_blocks_variable_injection():
    assert _fill("Hi $(user)", user="$(math 1+1)") == "Hi $ (math 1+1)"


def make(tmp_path, answers):
    from app.config import Settings
    from app.db import Database
    from app.runtime_config import RuntimeConfig

    async def build():
        db = Database(f"sqlite:///{tmp_path}/x.db"); await db.connect()
        cfg = RuntimeConfig(Settings(), db)
        sent, emitted, spent = [], [], []

        class Quota:
            def can_afford(self, k): return True
            def cost(self, k): return 1
            async def spend(self, n): spent.append(n)

        class Hub:
            mode = "live"
            async def send_chat(self, t, render=False): sent.append(t); return True

        class Notifier:
            async def emit(self, cid, title, body="", **kw): emitted.append((cid, title))

        class YT:
            state, video_id = "live", "vid1"
            async def _api(self, method, path, params=None, body=None):
                return answers.pop(0)

        c = SimpleNamespace(cfg=cfg, db=db, quota=Quota(), hub=Hub(), notifier=Notifier(), youtube=YT())
        return LiveExtras(c), c, sent, emitted, spent
    return build


def test_events_dedupe_notify_and_thank(tmp_path):
    async def go():
        x, c, sent, emitted, _ = await make(tmp_path, [])()
        await c.cfg.set("yt_events_thank", True)
        ev = parse_event(item("superChatEvent", superChatDetails={"amountDisplayString": "$5"}))
        await x.handle(ev); await x.handle(ev); await x.handle({**ev, "event_id": "back"}, backfill=True)
        assert len(emitted) == 1 and emitted[0][0] == "stream.superchat" and sent == ["Thank you Sam for the $5!"]
        assert len(await x.recent_events()) == 1
    asyncio.run(go())


def test_live_stats_likes_hidden_and_milestone(tmp_path):
    async def go():
        ans = [(200, {"items": [{"statistics": {"likeCount": "95"}, "liveStreamingDetails": {"concurrentViewers": "12"}}]}),
               (200, {"items": [{"statistics": {"likeCount": "105"}, "liveStreamingDetails": {"concurrentViewers": "60"}}]}),
               (200, {"items": [{"statistics": {}, "liveStreamingDetails": {}}]})]
        x, c, _, emitted, spent = await make(tmp_path, ans)()
        yt = c.youtube
        await x._live_stats(yt, time.time() - 120)
        await x._live_stats(yt, time.time() - 60)
        assert [e[1] for e in emitted] == ["100 likes", "50 watching at once"]
        await x._live_stats(yt, time.time())
        s = await x.stats()
        assert s["likes"] is None and s["likes_hidden"] and "hides" in s["note"] and s["peak_viewers"] == 60 and len(s["series"]) == 3 and spent == [1, 1, 1]
    asyncio.run(go())


def test_subscribers_first_look_is_silent_then_alerts_and_missing_access_is_explained(tmp_path):
    async def go():
        sub = lambda *ids: (200, {"items": [{"subscriberSnippet": {"channelId": i, "title": f"N{i}"}} for i in ids]})
        cnt = lambda n: (200, {"items": [{"statistics": {"subscriberCount": str(n)}}]})
        ans = [sub("a"), cnt(99), sub("a", "b"), cnt(100), (403, {}), cnt(100)]
        x, c, sent, emitted, _ = await make(tmp_path, ans)()
        await c.cfg.set("yt_subs_thank", True)
        await x._subscribers(c.youtube, 1.0)
        assert emitted == []
        await x._subscribers(c.youtube, 2.0)
        assert [e[1] for e in emitted] == ["Nb subscribed", "100 subscribers"] and sent == ["Thanks for subscribing, Nb! 🎉"]
        await x._subscribers(c.youtube, 3.0)
        assert x.subs["state"] == "needs_access" and "Sign in" in x.subs["note"]
    asyncio.run(go())
