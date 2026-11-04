import asyncio
from urllib.parse import parse_qs, urlparse

from fakes import FakeServer, wait_for

from app.config import Settings, StaticConfig
from app.container import Container
from app.db import Database
from app.services.youtube import AuthError, QuotaTracker, account_matches, parse_item
from app.store import Store

SPAM = "FREE ROBUX at robux-gift.xyz right now everybody"


def run(coro):
    return asyncio.run(coro)


def item(id_, author, text, name=None, **flags):
    return {"id": id_, "snippet": {"type": "textMessageEvent", "publishedAt": "2026-11-02T10:00:00Z", "authorChannelId": author,
                                   "textMessageDetails": {"messageText": text}},
            "authorDetails": {"channelId": author, "displayName": name or author, **flags}}


OWNER = "UC" + "A" * 22      # Creator A: owns the channel that is streaming
MOD = "UC" + "B" * 22        # Creator B: the account SavahBot is signed in as when it only moderates
OTHER = "UC" + "C" * 22      # an unrelated channel


class FakeYouTube:
    """A scriptable YouTube/Google. `account_id` is WHO the OAuth token belongs to; `stream_owner` is WHOSE stream is live.
    By default they are the same (a channel owner). Set account_id = MOD for the appointed-moderator scenario.

    Owner-only endpoints behave like the real API as documented: liveBroadcasts.list returns only the caller's own broadcasts."""

    def __init__(self):
        self.live = True
        self.pages = []            # scripted responses for liveChat/messages: (status, json)
        self.token_calls = 0
        self.reject_first_api_call = False
        self.action_status = {}    # e.g. {"bans": (403, {...})}
        self.account_id = OWNER
        self.account_title = "Creator"
        self.account_handle = "@creator"
        self.stream_owner = OWNER
        self.video_id = "vidLive"
        self.chat_forbidden = False
        self.moderators = set()    # channel ids appointed as moderators of the stream owner's chat
        self.extra_videos = {}     # video id -> item
        self.upcoming_only = False # the stream is scheduled but has not started
        self.server = FakeServer(self._handle)

    def _live_video(self):
        sn = {"title": "Friday Night Stream", "channelId": self.stream_owner, "channelTitle": "Creator A",
              "liveBroadcastContent": "live" if self.live else "none"}
        lsd = {"activeLiveChatId": "chat1"} if self.live else {"actualEndTime": "2026-11-02T12:00:00Z"}
        return {"id": self.video_id, "snippet": sn, "liveStreamingDetails": lsd}

    def _may_moderate(self):
        return self.account_id == self.stream_owner or self.account_id in self.moderators

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
            return 200, {"items": [{"id": self.account_id, "snippet": {"title": self.account_title, "customUrl": self.account_handle}}]}
        if path.endswith("/liveBroadcasts"):
            if not self.live or self.account_id != self.stream_owner:      # owner-only endpoint
                return 200, {"items": []}
            return 200, {"items": [{"id": "bc1", "snippet": {"liveChatId": "chat1", "title": "Friday Night Stream", "channelId": self.stream_owner}}]}
        if path.endswith("/playlistItems"):
            return 200, {"items": [{"contentDetails": {"videoId": self.video_id}}]}
        if path.endswith("/search"):
            return 200, {"items": [{"id": {"videoId": self.video_id}}] if self.live else []}
        if path.endswith("/videos"):
            wanted = query.get("id", "").split(",")
            items = [self._live_video()] if self.video_id in wanted else []
            items += [v for k, v in self.extra_videos.items() if k in wanted]
            return 200, {"items": items}
        if path.endswith("/liveChat/messages") and method == "GET":
            if self.chat_forbidden:
                return 403, {"error": {"errors": [{"reason": "forbidden"}]}}
            return self.pages.pop(0) if self.pages else (200, {"items": [], "nextPageToken": "tok", "pollingIntervalMillis": 10})
        for key in ("bans", "messages"):
            if path.endswith("/liveChat/" + key) and method in ("POST", "DELETE") and key in self.action_status:
                return self.action_status[key]
        if path.endswith("/liveChat/messages") and method == "DELETE":
            return (204, None) if self._may_moderate() else (403, {"error": {"errors": [{"reason": "forbidden"}]}})
        if path.endswith("/liveChat/bans"):
            return (200, {"kind": "youtube#liveChatBan", "id": "ban1"}) if self._may_moderate() else (403, {"error": {"errors": [{"reason": "insufficientPermissions"}]}})
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
            "YOUTUBE_DETECT_INTERVAL_SECONDS": "1", "OWNER_PASSWORD": "pw", "YOUTUBE_TARGET_CHANNEL_ID": OWNER, **extra}


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
                return 200, {"items": [{"id": "vid123", "snippet": {"title": "Pinned stream", "channelId": OWNER}, "liveStreamingDetails": {"activeLiveChatId": "chatP"}}]}
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


# ================================================================ moderator account vs target channel
async def spam_pending(c, fake):
    """Feed one spam message (after the history poll) and return the approval request it creates."""
    assert await live_and_polled(c)
    fake.pages = [(200, {"items": [item("bad1", "UCspam", SPAM, "Spammer")], "nextPageToken": "t2", "pollingIntervalMillis": 10})]
    assert await wait_for(lambda: any(m["author_name"] == "Spammer" for m in c.hub.buffer))
    pend = await c.store.pending_actions()
    assert len(pend) == 1
    return pend[0]


def as_moderator(fake):
    """Creator B is signed in; Creator A owns the livestream and has appointed B as a moderator."""
    fake.account_id, fake.account_title, fake.account_handle = MOD, "Creator B", "@creatorb"
    fake.stream_owner = OWNER
    fake.moderators = {MOD}


def test_scenario_a_channel_owner_keeps_working_through_liveBroadcasts():
    async def go():
        fake = FakeYouTube()                                   # account == stream owner
        c = await boot(fake)
        assert await wait_for(lambda: c.youtube.state == "live")
        st = c.youtube.status()
        assert st["mode"] == "owner" and st["account"]["channel_id"] == OWNER and st["target"]["channel_id"] == OWNER
        assert fake.calls("/liveBroadcasts") and not fake.calls("/playlistItems")
        pend = await spam_pending(c, fake)
        res = await c.hub.approve(pend["id"])
        assert res["ok"] and res["status"] == "executed"
        assert c.youtube.status()["permissions"]["delete"] is True and c.youtube.status()["permissions"]["ban"] is True
        await c.stop()
    run(go())


def test_scenario_b_appointed_moderator_discovers_reads_deletes_and_bans_on_another_channel():
    async def go():
        fake = FakeYouTube()
        as_moderator(fake)
        c = await boot(fake)                                   # target = Creator A's channel, signed in as Creator B
        assert await wait_for(lambda: c.youtube.state == "live")
        st = c.youtube.status()
        assert st["mode"] == "moderator"
        assert st["account"]["channel_id"] == MOD and st["account"]["title"] == "Creator B"      # who is signed in (from Google)
        assert st["target"]["channel_id"] == OWNER and st["target"]["title"] == "Creator A"        # whose stream is moderated
        assert not fake.calls("/liveBroadcasts")                                                   # owner-only endpoint is never used
        assert fake.calls("/playlistItems")[0]["query"]["playlistId"] == "UU" + OWNER[2:]
        assert fake.calls("/channels")[0]["query"]["mine"] == "true"
        pend = await spam_pending(c, fake)
        res = await c.hub.approve(pend["id"])
        assert res["ok"] and res["status"] == "executed"
        assert fake.calls("/liveChat/messages", "DELETE")[0]["query"]["id"] == "bad1"
        assert fake.calls("/liveChat/bans", "POST")[0]["body"]["snippet"]["liveChatId"] == "chat1"
        assert all(r["auth"].startswith("Bearer at-") for r in fake.server.requests if "/youtube/v3" in r["path"])   # always B's credentials
        await c.stop()
    run(go())


def test_scenario_b2_moderator_who_is_not_appointed_gets_an_honest_permission_error_and_no_retries():
    async def go():
        fake = FakeYouTube()
        as_moderator(fake)
        fake.moderators = set()                                # Creator A never appointed B
        c = await boot(fake)
        pend = await spam_pending(c, fake)
        used = c.quota.used
        res = await c.hub.approve(pend["id"])
        assert res["ok"] is False and res["status"] == "failed"
        assert "not allowed" in res["error"] and "Creator B" in res["error"] and OWNER in res["error"] and "moderator" in res["error"]
        assert c.youtube.status()["permissions"]["delete"] is False
        assert len(fake.calls("/liveChat/messages", "DELETE")) == 1 and fake.calls("/liveChat/bans") == []     # stopped at the first refusal
        ok, err = await c.youtube.delete("bad1")                # asking again must not hit YouTube or spend quota
        assert ok is False and "not allowed" in err
        assert len(fake.calls("/liveChat/messages", "DELETE")) == 1
        assert c.quota.used - used == c.quota.cost("chat_delete")
        assert (await c.store.get_action(pend["id"]))["status"] == "failed"      # never reported as success
        await c.stop()
    run(go())


def test_scenario_c_video_from_another_channel_is_rejected_not_attached():
    async def go():
        fake = FakeYouTube()
        fake.extra_videos["vidOther"] = {"id": "vidOther", "snippet": {"title": "Someone else", "channelId": OTHER, "channelTitle": "Other"},
                                         "liveStreamingDetails": {"activeLiveChatId": "chatOther"}}
        c = await boot(fake, YOUTUBE_VIDEO_ID="vidOther")
        assert await wait_for(lambda: c.youtube.state == "target_mismatch")
        assert c.youtube.chat_id == "" and not fake.calls("/liveChat/messages", "GET")
        err = c.youtube.status()["last_error"]
        assert OTHER in err and OWNER in err and "Refusing" in err
        assert not fake.calls("/liveBroadcasts")                # and it did not quietly fall back to discovery
        await c.stop()
    run(go())


def test_scenario_c_pinned_video_of_the_right_channel_is_accepted_for_a_moderator():
    async def go():
        fake = FakeYouTube()
        as_moderator(fake)
        c = await boot(fake, YOUTUBE_VIDEO_ID="vidLive")
        assert await wait_for(lambda: c.youtube.state == "live")
        assert c.youtube.video_id == "vidLive" and not fake.calls("/playlistItems") and not fake.calls("/liveBroadcasts")
        await c.stop()
    run(go())


def test_scenario_d_missing_target_is_a_clear_config_error_and_never_monitors_the_own_channel():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake, YOUTUBE_TARGET_CHANNEL_ID="")
        assert await wait_for(lambda: c.youtube.state == "config_error")
        err = c.youtube.status()["last_error"]
        assert "YOUTUBE_TARGET_CHANNEL_ID" in err and "never falls back" in err
        assert OWNER in err                                     # the hint names the connected account's channel, but does not use it
        assert c.youtube.chat_id == "" and not fake.calls("/liveBroadcasts") and not fake.calls("/liveChat/messages")
        await c.stop()
    run(go())


def test_scenario_d_a_handle_is_not_a_channel_id_and_the_old_variable_still_works():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake, YOUTUBE_TARGET_CHANNEL_ID="@creatora")
        assert await wait_for(lambda: c.youtube.state == "config_error")
        assert "24 characters" in c.youtube.status()["last_error"]
        await c.stop()
        fake2 = FakeYouTube()
        c2 = await boot(fake2, YOUTUBE_TARGET_CHANNEL_ID="", YOUTUBE_CHANNEL_ID=OWNER)       # older installs: deprecated alias
        assert await wait_for(lambda: c2.youtube.state == "live")
        assert c2.youtube.status()["target"]["deprecated_variable"] is True
        assert all(i["set"] for i in c2.cfg.requirements_status()["youtube"])
        await c2.stop()
    run(go())


def test_scenario_e_revoked_login_is_an_auth_error_with_recovery_instructions():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake, YOUTUBE_REFRESH_TOKEN="rt-revoked")
        assert await wait_for(lambda: c.youtube.state == "auth_error")
        err = c.youtube.status()["last_error"]
        assert "Reconnect YouTube" in err and "moderator account" in err and "csecret" not in err and "rt-revoked" not in err
        assert not fake.calls("/liveBroadcasts") and not fake.calls("/playlistItems")
        await c.stop()
    run(go())


def test_scenario_e_a_token_youtube_keeps_rejecting_is_an_auth_error_not_a_loop():
    async def go():
        fake = FakeYouTube()
        orig = fake._handle
        fake.server.close()
        fake.server = FakeServer(lambda m, p, q, b, h: (401, {"error": {"errors": [{"reason": "authError"}]}}) if "/youtube/v3" in p else orig(m, p, q, b, h))
        c = await boot(fake)
        assert await wait_for(lambda: c.youtube.state == "auth_error")
        assert "Reconnect YouTube" in c.youtube.status()["last_error"]
        await c.stop()
    run(go())


def test_scenario_f_chat_that_forbids_reading_is_reported_and_not_hammered():
    async def go():
        fake = FakeYouTube()
        as_moderator(fake)
        fake.chat_forbidden = True
        c = await boot(fake, YOUTUBE_PERMISSION_RETRY_SECONDS="60")
        assert await wait_for(lambda: c.youtube.state == "no_permission")
        st = c.youtube.status()
        assert st["permissions"]["read"] is False and "Creator B" in st["last_error"] and "Nothing is being moderated" in st["last_error"]
        assert st["chat_attached"] is False and not c.hub.stream_live
        polls = len(fake.calls("/liveChat/messages", "GET"))
        await asyncio.sleep(0.4)
        assert len(fake.calls("/liveChat/messages", "GET")) == polls          # waits the retry interval instead of spinning
        await c.stop()
    run(go())


def test_scenario_f_owner_and_moderator_bans_are_refused_with_the_right_words():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake)
        assert await live_and_polled(c)
        fake.action_status["bans"] = (403, {"error": {"errors": [{"reason": "liveChatBanInsertionNotAllowed"}]}})
        ok, err = await c.youtube.ban("UCsomeMod")
        assert ok is False and "owner or another moderator" in err
        ok, err = await c.youtube.ban("UCsomeMod")                              # a target-specific refusal must not block other users
        assert fake.calls("/liveChat/bans") and len(fake.calls("/liveChat/bans")) == 2
        fake.action_status["messages"] = (403, {"error": {"errors": [{"reason": "modificationNotAllowed"}]}})
        ok, err = await c.youtube.delete("m1")
        assert ok is False and "will not delete" in err
        assert c.youtube.status()["permissions"]["ban"] is None                  # unverified is never shown as verified
        await c.stop()
    run(go())


def test_scenario_g_livestream_ends_and_discovery_resumes_for_a_moderator():
    async def go():
        fake = FakeYouTube()
        as_moderator(fake)
        c = await boot(fake)
        assert await wait_for(lambda: c.youtube.state == "live")
        fake.live = False
        fake.pages = [(403, {"error": {"errors": [{"reason": "liveChatEnded"}]}})]
        assert await wait_for(lambda: c.youtube.state == "offline" and not c.hub.stream_live)
        assert c.youtube.chat_id == ""
        fake.live = True
        assert await wait_for(lambda: c.youtube.state == "live" and c.hub.stream_live, timeout=6)
        await c.stop()
    run(go())


def test_scenario_g_chat_ended_event_stops_monitoring_immediately():
    async def go():
        fake = FakeYouTube()
        as_moderator(fake)
        c = await boot(fake)
        assert await live_and_polled(c)
        fake.live = False
        fake.pages = [(200, {"items": [{"id": "e1", "snippet": {"type": "chatEndedEvent", "publishedAt": "2026-11-02T10:00:00Z"}}],
                             "nextPageToken": "t7", "pollingIntervalMillis": 10})]
        assert await wait_for(lambda: c.youtube.state == "offline" and not c.hub.stream_live)
        await c.stop()
    run(go())


def test_wrong_google_account_is_refused_when_a_moderator_account_is_expected():
    async def go():
        fake = FakeYouTube()
        as_moderator(fake)
        c = await boot(fake, YOUTUBE_MODERATOR_ACCOUNT="@someoneelse")
        assert await wait_for(lambda: c.youtube.state == "wrong_account")
        assert c.youtube.chat_id == "" and not fake.calls("/playlistItems") and not fake.calls("/liveChat/messages")
        assert "Creator B" in c.youtube.status()["last_error"] and "@someoneelse" in c.youtube.status()["last_error"]
        await c.stop()
        fake2 = FakeYouTube()
        as_moderator(fake2)
        c2 = await boot(fake2, YOUTUBE_MODERATOR_ACCOUNT=MOD)                 # right account (channel id) -> proceeds
        assert await wait_for(lambda: c2.youtube.state == "live")
        await c2.stop()
    run(go())


def test_account_matching_accepts_id_handle_or_name_and_blank_means_no_check():
    acct = {"channel_id": MOD, "title": "Creator B", "handle": "@creatorb"}
    assert account_matches("", acct) and account_matches(MOD, acct) and account_matches("@CreatorB", acct)
    assert account_matches("creatorb", acct) and account_matches("creator b", acct)
    assert not account_matches(OWNER, acct) and not account_matches("@creatora", acct)


def test_identity_after_sign_in_is_read_from_google_remembered_and_refreshed_on_reconnect():
    async def go():
        fake = FakeYouTube()
        as_moderator(fake)
        c = await boot(fake, BOT_MODE="demo")
        verdict, msg = await c.youtube.identify()
        assert verdict == "ok" and c.youtube.account["channel_id"] == MOD
        assert (await c.youtube.account_info())["title"] == "Creator B"
        await c.google.exchange_code("code")                                    # a new sign-in forgets the old identity...
        fake.account_id, fake.account_title, fake.account_handle = OTHER, "Someone New", "@someonenew"   # ...and the next lookup sees whoever signed in
        verdict, msg = await c.youtube.identify()
        assert verdict == "ok" and c.youtube.account["channel_id"] == OTHER
        await c.stop()
        c2 = await boot(fake, BOT_MODE="demo", YOUTUBE_MODERATOR_ACCOUNT="@creatorb")
        verdict, msg = await c2.youtube.identify()
        assert verdict == "rejected" and "Someone New" in msg
        await c2.stop()
    run(go())


def test_discovery_for_a_moderator_is_cheap_and_skips_the_video_lookup_when_nothing_changed():
    async def go():
        fake = FakeYouTube()
        as_moderator(fake)
        fake.live = False
        c = await boot(fake, YOUTUBE_DETECT_INTERVAL_SECONDS="0.05")
        assert await wait_for(lambda: len(fake.calls("/playlistItems")) >= 4)
        assert len(fake.calls("/videos")) == 1                  # same uploads, none live or upcoming: no need to ask again
        assert c.youtube.state == "offline" and not fake.calls("/search")      # search (100 units) is opt-in
        await c.stop()
    run(go())


def test_search_fallback_is_opt_in_and_still_checks_the_channel_owner():
    async def go():
        fake = FakeYouTube()
        as_moderator(fake)
        fake.video_id = "vidNew"
        orig = fake._handle
        fake.server.close()
        fake.server = FakeServer(lambda m, p, q, b, h: (200, {"items": []}) if p.endswith("/playlistItems") else orig(m, p, q, b, h))   # not in recent uploads
        c = await boot(fake, YOUTUBE_DISCOVERY_USE_SEARCH="true")
        assert await wait_for(lambda: c.youtube.state == "live")
        assert fake.calls("/search")[0]["query"]["channelId"] == OWNER and fake.calls("/search")[0]["query"]["eventType"] == "live"
        await c.stop()
    run(go())


def test_diagnose_reports_what_was_really_verified_and_what_cannot_be_tested():
    async def go():
        fake = FakeYouTube()
        as_moderator(fake)
        c = await boot(fake, BOT_MODE="demo")
        res = await c.youtube.diagnose()
        by = {x["label"]: x for x in res["checks"]}
        assert res["ok"] and by["Connected account"]["ok"] is True and by["Role"]["detail"].find("moderator") >= 0
        assert by["Read chat"]["ok"] is True
        assert by["Delete messages"]["ok"] is None and "no dry run" in by["Delete messages"]["detail"]      # honest: unverified
        assert by["Ban / time out"]["ok"] is None
        fake.chat_forbidden = True
        res = await c.youtube.diagnose()
        assert res["ok"] is False and {x["label"]: x for x in res["checks"]}["Read chat"]["ok"] is False
        assert c.youtube.state == "stopped"                                     # a check never disturbs the running state
        await c.stop()
    run(go())


def test_no_secrets_in_status_or_errors():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake, YOUTUBE_REFRESH_TOKEN="rt-revoked")
        assert await wait_for(lambda: c.youtube.state == "auth_error")
        blob = str(c.youtube.status())
        assert "csecret" not in blob and "rt-revoked" not in blob and "rt-1" not in blob
        await c.stop()
    run(go())
