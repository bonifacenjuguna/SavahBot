import asyncio
from urllib.parse import parse_qs, urlparse

from fakes import FakeServer, wait_for

from app.config import Settings, StaticConfig
from app.container import Container
from app.db import Database
from app.services.youtube import QuotaTracker, parse_item
from app.store import Store

OWNER_CH = "UC" + "o" * 22      # the channel that owns the stream (Creator A)
MOD_CH = "UC" + "m" * 22        # the signed-in moderator's own channel (Creator B)
SPAM = "FREE ROBUX at robux-gift.xyz right now everybody"


def run(coro):
    return asyncio.run(coro)


def item(id_, author, text, name=None, **flags):
    return {"id": id_, "snippet": {"type": "textMessageEvent", "publishedAt": "2026-11-02T10:00:00Z", "authorChannelId": author,
                                   "textMessageDetails": {"messageText": text}},
            "authorDetails": {"channelId": author, "displayName": name or author, **flags}}


class FakeYouTube:
    def __init__(self):
        self.live = True
        self.pages = []            # scripted responses for liveChat/messages: (status, json)
        self.token_calls = 0
        self.reject_first_api_call = False
        self.action_status = {}    # e.g. {"bans": (403, {...})}
        self.account_channel = OWNER_CH   # which channel `channels?mine=true` reports: the signed-in account
        self.broadcast_channel = OWNER_CH
        self.videos = {}                  # id -> item for /videos
        self.search_ids = []              # ids returned by /search
        self.handles = {}                 # "@handle" -> channel id
        self.server = FakeServer(self._handle)

    def _handle(self, method, path, query, body, headers):
        if path == "/token":
            self.token_calls += 1
            if body.get("grant_type") == "authorization_code":
                return 200, {"access_token": "at-code", "refresh_token": "rt-new", "expires_in": 3600}
            if body.get("refresh_token") != "rt-1" and body.get("refresh_token") != "rt-new":
                return 400, {"error": "invalid_grant", "error_description": "Token has been revoked"}
            return 200, {"access_token": f"at-{self.token_calls}", "expires_in": 3600}
        if self.reject_first_api_call:
            self.reject_first_api_call = False
            return 401, {"error": {"errors": [{"reason": "authError"}]}}
        if path.endswith("/channels"):
            if query.get("forHandle"):
                cid = self.handles.get(query["forHandle"])
                return 200, {"items": [{"id": cid, "snippet": {"title": "Handle channel"}}] if cid else []}
            if not self.account_channel:
                return 200, {}
            return 200, {"items": [{"id": self.account_channel, "snippet": {"title": "Signed-in account", "customUrl": "@signedin"}}]}
        if path.endswith("/search"):
            return 200, {"items": [{"id": {"videoId": v}} for v in self.search_ids]}
        if path.endswith("/videos"):
            return 200, {"items": [self.videos[v] for v in query["id"].split(",") if v in self.videos]}
        if path.endswith("/liveBroadcasts"):
            if not self.live:
                return 200, {"items": []}
            return 200, {"items": [{"id": "bc1", "snippet": {"liveChatId": "chat1", "title": "Friday Night Stream", "channelId": self.broadcast_channel}}]}
        if path.endswith("/liveChat/messages") and method == "GET":
            return self.pages.pop(0) if self.pages else (200, {"items": [], "nextPageToken": "tok", "pollingIntervalMillis": 10})
        for key in ("bans", "messages"):
            if path.endswith("/liveChat/" + key) and method in ("POST", "DELETE") and key in self.action_status:
                return self.action_status[key]
        if path.endswith("/liveChat/messages") and method == "DELETE":
            return 204, None
        if path.endswith("/liveChat/bans"):
            return 200, {"kind": "youtube#liveChatBan", "id": "ban1"}
        if path.endswith("/liveChat/messages") and method == "POST":
            return 200, {"id": "sent1"}
        return 404, {"error": {"errors": [{"reason": "notFound"}]}}

    def calls(self, part, method=None):
        return self.server.calls(part, method)


def env(fake, **extra):
    base = fake.server.base
    return {"BOT_MODE": "live", "DEMO_AUTOSTART": "false", "PUBLIC_BASE_URL": "https://bot.example", "GOOGLE_CLIENT_ID": "cid.apps",
            "GOOGLE_CLIENT_SECRET": "csecret", "YOUTUBE_REFRESH_TOKEN": "rt-1", "YOUTUBE_API_BASE": base + "/youtube/v3",
            "GOOGLE_OAUTH_TOKEN_URL": base + "/token", "YT_MIN_POLL_SECONDS": "0.01", "YT_MAX_POLL_SECONDS": "0.05",
            "YOUTUBE_DETECT_INTERVAL_SECONDS": "1", "OWNER_PASSWORD": "pw", "YOUTUBE_TARGET_CHANNEL_ID": OWNER_CH, **extra}


async def boot(fake, **extra):
    c = Container(Settings(env=env(fake, **extra), env_file=None), Database(":memory:"))
    await c.start()
    return c


async def live_and_polled(c):
    """Wait until the stream is attached AND the first poll finished. The first poll is treated as chat
    history (stored, never moderated), so tests that script live messages must wait for it."""
    return await wait_for(lambda: c.youtube.state == "live" and c.youtube.polls >= 1)


# ---------------------------------------------------------------- pure logic
def test_parse_item_levels_types_and_junk():
    m = parse_item(item("i1", "UC1", "hello", "Alice", isChatOwner=True))
    assert (m.platform, m.level, m.author_name, m.msg_id, m.text) == ("youtube", "owner", "Alice", "i1", "hello")
    assert m.ts == 1793613600.0
    assert parse_item(item("i2", "UC2", "x", isChatModerator=True)).level == "mod"
    assert parse_item(item("i3", "UC3", "x", isChatSponsor=True)).level == "member"
    assert parse_item(item("i4", "UC4", "x")).level == "everyone"
    sc = {"id": "s1", "snippet": {"type": "superChatEvent", "publishedAt": "2026-11-02T10:00:00Z", "superChatDetails": {"userComment": "thanks!"}},
          "authorDetails": {"channelId": "UC5", "displayName": "Rich"}}
    assert parse_item(sc).text == "thanks!"
    assert parse_item({"id": "x", "snippet": {"type": "messageDeletedEvent"}, "authorDetails": {}}) is None
    assert parse_item(item("i5", "UC", "   ")) is None


def test_quota_pacing_spreads_the_read_budget_over_the_stream():
    async def go():
        db = Database(":memory:")
        await db.connect()
        cfg = StaticConfig()
        q = QuotaTracker(cfg, Store(db))
        await q.sync()
        # 10,000 units x 60% for reading = 6,000 / 5 per poll = 1,200 polls over 4 hours = one every 12 seconds
        assert abs(q.read_interval(0) - 12.0) < 0.01
        await q.spend(3000)
        assert abs(q.read_interval(0) - 24.0) < 0.01             # half the read budget gone: poll half as often
        assert abs(q.read_interval(3 * 3600) - 6.0) < 0.01        # an hour left, 600 polls affordable: every 6 seconds
        assert q.read_interval(4 * 3600) == 5.0                   # past the planned end: floor at the minimum poll time
        await q.spend(3000)
        assert q.read_interval(0) == 60.0                         # read budget spent: slow, but still moderating
        await q.spend(3700)
        assert q.read_interval(0) is None                         # only the action reserve is left: stop reading
        assert q.remaining == 300 and q.can_afford("ban") and q.can_afford("chat_delete")
        await q.spend(150)
        assert q.remaining == 150 and not q.can_afford("ban") and q.can_afford("chat_delete")
        q2 = QuotaTracker(cfg, Store(db))                         # persisted: survives a restart
        await q2.sync()
        assert q2.used == 9850
    run(go())


def test_quota_day_rolls_over_at_pacific_midnight():
    async def go():
        db = Database(":memory:")
        await db.connect()
        clock = {"t": 1793613600.0}                              # 2026-11-02 10:00 UTC = 02:00 Pacific
        q = QuotaTracker(StaticConfig(), Store(db), now_fn=lambda: clock["t"])
        await q.spend(500)
        assert q.day() == "2026-11-02"
        clock["t"] += 7 * 3600                                    # 17:00 UTC = 09:00 Pacific, still the same day
        await q.sync()
        assert q.used == 500
        clock["t"] += 15 * 3600 + 60                              # 22 hours after the start: just past midnight Pacific
        await q.sync()
        assert q.day() == "2026-11-03" and q.used == 0
    run(go())


# ---------------------------------------------------------------- OAuth
def test_oauth_flow_stores_refresh_token_and_state_is_single_use():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake, YOUTUBE_REFRESH_TOKEN="", BOT_MODE="demo")
        g = c.google
        assert not await g.connected()
        state = g.new_state()
        url = urlparse(g.auth_url(state))
        q = parse_qs(url.query)
        assert q["client_id"] == ["cid.apps"] and q["state"] == [state] and q["access_type"] == ["offline"]
        assert q["redirect_uri"] == ["https://bot.example/api/youtube/oauth/callback"]
        assert "youtube.force-ssl" in q["scope"][0]
        assert g.check_state(state) is True and g.check_state(state) is False and g.check_state("forged") is False
        await g.exchange_code("auth-code-1")
        assert await g.connected() and await g.refresh_token() == "rt-new"
        assert fake.calls("/token")[0]["body"]["redirect_uri"] == "https://bot.example/api/youtube/oauth/callback"
        await g.disconnect()
        assert not await g.connected()
        await c.stop()
    run(go())


def test_revoked_refresh_token_gives_an_actionable_error():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake, YOUTUBE_REFRESH_TOKEN="rt-revoked", BOT_MODE="demo")
        try:
            await c.google.access_token()
            assert False, "should have raised"
        except RuntimeError as exc:
            assert "Reconnect YouTube" in str(exc) and "revoked" in str(exc)
        await c.stop()
    run(go())


# ---------------------------------------------------------------- live polling
def test_not_connected_state_without_credentials():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake, GOOGLE_CLIENT_ID="", YOUTUBE_REFRESH_TOKEN="")
        assert await wait_for(lambda: c.youtube.state == "not_connected")
        assert c.youtube.status()["connected"] is False and not fake.calls("/liveBroadcasts")
        await c.stop()
    run(go())


def test_detects_stream_ingests_chat_and_backfills_history_without_judging_it():
    async def go():
        fake = FakeYouTube()
        fake.pages = [(200, {"items": [item("old1", "UCold", SPAM, "OldSpammer")], "nextPageToken": "t1", "pollingIntervalMillis": 10}),
                      (200, {"items": [item("n1", "UCfan", "great stream!", "Fan"), item("n2", "UCmod", "welcome all", "TheMod", isChatModerator=True)],
                             "nextPageToken": "t2", "pollingIntervalMillis": 10})]
        c = await boot(fake)
        assert await wait_for(lambda: len(c.hub.buffer) >= 3)
        assert c.youtube.state == "live" and c.hub.stream_live and c.hub.stream_title == "Friday Night Stream"
        texts = [m["text"] for m in c.hub.buffer]
        assert texts[:3] == [SPAM, "great stream!", "welcome all"]
        assert c.hub.buffer[0]["verdict"] == "allow"                     # history is stored, not moderated
        assert await c.store.pending_actions() == []
        polls = fake.calls("/liveChat/messages", "GET")
        assert polls[0]["query"]["liveChatId"] == "chat1" and "pageToken" not in polls[0]["query"]
        assert polls[1]["query"]["pageToken"] == "t1"                    # resumes from the last token
        assert polls[0]["auth"].startswith("Bearer at-")
        await c.stop()
    run(go())


def test_spam_waits_for_approval_then_approval_deletes_and_bans_on_youtube():
    async def go():
        fake = FakeYouTube()
        fake.pages = [(200, {"items": [], "nextPageToken": "t1", "pollingIntervalMillis": 10}),
                      (200, {"items": [item("bad1", "UCspam", SPAM, "Spammer")], "nextPageToken": "t2", "pollingIntervalMillis": 10})]
        c = await boot(fake)
        assert await wait_for(lambda: c.hub.buffer and c.hub.buffer[-1]["author_name"] == "Spammer")
        assert await wait_for(lambda: True)
        pend = await c.store.pending_actions()
        assert len(pend) == 1 and pend[0]["action"] == "ban" and pend[0]["platform"] == "youtube"
        assert fake.calls("/liveChat/bans") == []                         # nothing happens without approval
        used_before = c.quota.used
        res = await c.hub.approve(pend[0]["id"])
        assert res["ok"] and res["status"] == "executed"
        dele = fake.calls("/liveChat/messages", "DELETE")[0]
        assert dele["query"]["id"] == "bad1"
        ban = fake.calls("/liveChat/bans", "POST")[0]["body"]["snippet"]
        assert ban == {"liveChatId": "chat1", "type": "permanent", "bannedUserDetails": {"channelId": "UCspam"}}
        assert c.quota.used - used_before >= 20 + 200                    # delete + ban were charged to the quota
        assert c.engine.strikes("youtube:UCspam") == 1
        await c.stop()
    run(go())


def test_auto_mode_timeouts_run_without_approval():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake, MOD_MODE="auto", MOD_AUTO_ACTIONS="delete,timeout,ban")
        assert await live_and_polled(c)
        c.engine.add_strike("youtube:UCrude")
        c.engine.add_strike("youtube:UCrude")
        fake.pages = [(200, {"items": [item("r1", "UCrude", "get free robux now", "Rude")], "nextPageToken": "t9", "pollingIntervalMillis": 10})]
        assert await wait_for(lambda: fake.calls("/liveChat/bans"))
        body = fake.calls("/liveChat/bans", "POST")[0]["body"]["snippet"]
        assert body["type"] == "temporary" and body["banDurationSeconds"] == 60 and body["bannedUserDetails"]["channelId"] == "UCrude"
        assert fake.calls("/liveChat/messages", "DELETE")
        await c.stop()
    run(go())


def test_bot_replies_to_commands_in_youtube_chat_and_ignores_its_own_echo():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake)
        assert await live_and_polled(c)
        fake.pages = [(200, {"items": [item("c1", "UCv", "!hello", "Viewer")], "nextPageToken": "t5", "pollingIntervalMillis": 10})]
        assert await wait_for(lambda: fake.calls("/liveChat/messages", "POST"))
        sent = fake.calls("/liveChat/messages", "POST")[0]
        assert sent["query"]["part"] == "snippet"
        assert sent["body"]["snippet"]["textMessageDetails"]["messageText"] == "Hello Viewer! Welcome to the stream."
        fake.pages = [(200, {"items": [item("c2", "UCowner", "Hello Viewer! Welcome to the stream.", "Me", isChatOwner=True)],
                             "nextPageToken": "t6", "pollingIntervalMillis": 10})]
        assert await wait_for(lambda: any(m["msg_id"] == "c2" for m in c.hub.buffer))
        assert [m for m in c.hub.buffer if m["msg_id"] == "c2"][0]["from_bot"] is True
        assert len(fake.calls("/liveChat/messages", "POST")) == 1
        await c.stop()
    run(go())


def test_stream_end_returns_to_offline_and_detection_resumes():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake)
        assert await wait_for(lambda: c.youtube.state == "live")
        fake.live = False
        fake.pages = [(403, {"error": {"errors": [{"reason": "liveChatEnded"}]}})]
        assert await wait_for(lambda: c.youtube.state == "offline" and not c.hub.stream_live)
        assert c.youtube.status()["chat_attached"] is False
        fake.live = True
        assert await wait_for(lambda: c.youtube.state == "live" and c.hub.stream_live, timeout=6)
        await c.stop()
    run(go())


def test_expired_access_token_is_refreshed_and_the_call_retried():
    async def go():
        fake = FakeYouTube()
        fake.reject_first_api_call = True
        c = await boot(fake)
        assert await wait_for(lambda: c.youtube.state == "live")
        assert fake.token_calls >= 2                                       # initial token + forced refresh after the 401
        await c.stop()
    run(go())


def test_quota_exhaustion_stops_polling_and_reports_failed_actions():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake, YT_DAILY_QUOTA="400")
        assert await live_and_polled(c)
        fake.pages = [(200, {"items": [item("bad2", "UCspam2", SPAM, "Spammer2")], "nextPageToken": "t3", "pollingIntervalMillis": 10})]
        assert await wait_for(lambda: len(c.hub.buffer) >= 1)
        await c.quota.spend(250)                                           # leave about 150 units: a ban (200) is out of reach
        pend = await c.store.pending_actions()
        res = await c.hub.approve(pend[0]["id"])
        assert res["ok"] is False and "quota too low" in res["error"] and "needs 220" in res["error"]
        assert (await c.store.get_action(pend[0]["id"]))["status"] == "failed"
        assert fake.calls("/liveChat/messages", "DELETE") == [] and fake.calls("/liveChat/bans") == []   # all-or-nothing
        assert await wait_for(lambda: c.youtube.state == "quota_low")
        polls = len(fake.calls("/liveChat/messages", "GET"))
        await asyncio.sleep(0.3)
        assert len(fake.calls("/liveChat/messages", "GET")) == polls       # reading stopped to protect the reserve
        assert "quota" in c.youtube.status()["last_error"].lower()
        await c.stop()
    run(go())


def test_youtube_rejecting_the_daily_limit_marks_quota_exhausted():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake)
        assert await wait_for(lambda: c.youtube.state == "live")
        fake.action_status["bans"] = (403, {"error": {"errors": [{"reason": "quotaExceeded"}]}})
        ok, err = await c.youtube.ban("UCx")
        assert ok is False and "quota" in err.lower() and c.quota.remaining == 0
        await c.stop()
    run(go())


def test_pinned_video_id_uses_the_videos_endpoint():
    async def go():
        fake = FakeYouTube()
        orig = fake._handle

        def handler(method, path, query, body, headers):
            if path.endswith("/videos"):
                return 200, {"items": [{"id": "vid123", "snippet": {"title": "Pinned stream", "channelId": OWNER_CH}, "liveStreamingDetails": {"activeLiveChatId": "chatP"}}]}
            return orig(method, path, query, body, headers)

        fake.server.close()
        fake.server = FakeServer(handler)
        c = await boot(fake, YOUTUBE_VIDEO_ID="vid123")
        assert await wait_for(lambda: c.youtube.state == "live")
        assert fake.calls("/videos")[0]["query"]["id"] == "vid123" and not fake.calls("/liveBroadcasts")
        assert c.hub.stream_title == "Pinned stream"
        await c.stop()
    run(go())


def test_switching_between_demo_and_live_modes_at_runtime():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake, BOT_MODE="demo")
        assert c.hub.status()["source"] == "demo" and c.youtube.state == "stopped"
        await c.cfg.set("bot_mode", "live")
        assert await wait_for(lambda: c.youtube.state == "live" and c.hub.status()["source"] == "youtube")
        await c.cfg.set("bot_mode", "demo")
        assert await wait_for(lambda: c.hub.status()["source"] == "demo" and c.youtube.state == "stopped")
        assert c.hub.stream_title.endswith("(demo stream)")
        await c.stop()
    run(go())
