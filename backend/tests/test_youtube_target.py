"""The signed-in Google account (the moderator) and the channel being moderated (the target) are different things.

Scenarios A-G from the cross-channel moderation spec. Everything runs against a fake YouTube server; nothing here proves what
the real API allows a moderator-only account to do, only that SavahBot asks for it correctly and reports the answer honestly."""
import asyncio

from fakes import wait_for
from test_youtube import MOD_CH, OWNER_CH, FakeYouTube, boot, item, run

from app.services.youtube import parse_video_id

OTHER_CH = "UC" + "x" * 22
FAST = {"YOUTUBE_TARGET_DETECT_INTERVAL_SECONDS": "1"}
FORBIDDEN = (403, {"error": {"errors": [{"reason": "forbidden"}]}})


def video(id_, channel, chat="chatA", title="Creator A live"):
    return {"id": id_, "snippet": {"title": title, "channelId": channel}, "liveStreamingDetails": {"activeLiveChatId": chat}}


def moderator_setup():
    """Creator A (OWNER_CH) is streaming. Creator B (MOD_CH) is signed in and is only a moderator."""
    fake = FakeYouTube()
    fake.account_channel = MOD_CH
    fake.search_ids = ["vidA"]
    fake.videos = {"vidA": video("vidA", OWNER_CH)}
    return fake


def test_parse_video_id_accepts_ids_and_links():
    assert parse_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=5") == "dQw4w9WgXcQ"
    assert parse_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("https://www.youtube.com/live/dQw4w9WgXcQ?feature=share") == "dQw4w9WgXcQ"
    assert parse_video_id("") == ""


# ---- A: the owner signs in and the target is their own channel -> the cheap own-broadcast path still works
def test_a_owner_uses_own_broadcast_lookup_and_never_searches():
    async def go():
        fake = FakeYouTube()                      # account_channel == OWNER_CH == target
        c = await boot(fake)
        assert await wait_for(lambda: c.youtube.state == "live")
        st = c.youtube.status()
        assert st["account"]["channel_id"] == OWNER_CH and st["target"]["channel_id"] == OWNER_CH
        assert fake.calls("/liveBroadcasts") and not fake.calls("/search")
        await c.stop()
    run(go())


# ---- B: the signed-in account is only a moderator of the target channel
def test_b_moderator_finds_and_moderates_another_channels_stream_with_its_own_credentials():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, **FAST)
        assert await wait_for(lambda: c.youtube.state == "live")
        st = c.youtube.status()
        assert st["account"]["channel_id"] == MOD_CH and st["target"]["channel_id"] == OWNER_CH   # two different identities
        assert st["video_channel_id"] == OWNER_CH and c.youtube.chat_id == "chatA"
        assert not fake.calls("/liveBroadcasts"), "must not look at the moderator's own broadcasts"
        search = fake.calls("/search")[0]["query"]
        assert search["channelId"] == OWNER_CH and search["eventType"] == "live" and search["type"] == "video"
        assert await wait_for(lambda: fake.calls("/liveChat/messages", "GET"))
        assert fake.calls("/liveChat/messages", "GET")[0]["query"]["liveChatId"] == "chatA"
        ok, err = await c.youtube.delete("msg-1")
        assert ok and not err
        ok, err = await c.youtube.ban("UC" + "s" * 22)
        assert ok
        ban = fake.calls("/liveChat/bans", "POST")[0]
        assert ban["body"]["snippet"]["liveChatId"] == "chatA" and ban["auth"].startswith("Bearer at-")
        assert fake.calls("/liveChat/messages", "DELETE")[0]["auth"].startswith("Bearer at-")
        await c.stop()
    run(go())


def test_b_moderator_can_pin_a_video_by_link():
    async def go():
        fake = moderator_setup()
        fake.videos = {"dQw4w9WgXcQ": video("dQw4w9WgXcQ", OWNER_CH)}
        c = await boot(fake, YOUTUBE_VIDEO_ID="https://youtu.be/dQw4w9WgXcQ")
        assert await wait_for(lambda: c.youtube.state == "live")
        assert fake.calls("/videos")[0]["query"]["id"] == "dQw4w9WgXcQ" and not fake.calls("/search")
        await c.stop()
    run(go())


def test_handle_target_is_resolved_to_a_channel_id():
    async def go():
        fake = moderator_setup()
        fake.handles = {"@creatora": OWNER_CH}
        c = await boot(fake, YOUTUBE_TARGET_CHANNEL_ID="@creatora", **FAST)
        assert await wait_for(lambda: c.youtube.state == "live")
        assert c.youtube.status()["target"]["channel_id"] == OWNER_CH
        await c.stop()
    run(go())


# ---- C: the stream does not belong to the configured target channel -> refuse, never attach
def test_c_pinned_video_from_another_channel_is_rejected():
    async def go():
        fake = moderator_setup()
        fake.videos = {"vidX": video("vidX", OTHER_CH, chat="chatX")}
        c = await boot(fake, YOUTUBE_VIDEO_ID="vidX")
        assert await wait_for(lambda: c.youtube.state == "config_error")
        assert "did not attach" in c.youtube.last_error and OTHER_CH in c.youtube.last_error
        await asyncio.sleep(0.3)
        assert not c.youtube.chat_id and not fake.calls("/liveChat/messages", "GET")
        await c.stop()
    run(go())


def test_c_search_results_from_other_channels_are_ignored():
    async def go():
        fake = moderator_setup()
        fake.videos = {"vidA": video("vidA", OTHER_CH)}
        c = await boot(fake, **FAST)
        assert await wait_for(lambda: len(fake.calls("/search")) >= 1 and c.youtube.state == "offline")
        assert not c.youtube.chat_id and not fake.calls("/liveChat/messages", "GET")
        await c.stop()
    run(go())


# ---- D: no target channel -> a clear configuration error, and nothing is monitored
def test_d_missing_target_is_an_error_not_a_silent_fallback():
    async def go():
        for blank in ("", "edit-me"):
            fake = FakeYouTube()                  # the signed-in account HAS a live broadcast of its own
            c = await boot(fake, YOUTUBE_TARGET_CHANNEL_ID=blank)
            assert await wait_for(lambda: c.youtube.state == "config_error")
            assert "No target channel is set" in c.youtube.last_error and "YOUTUBE_TARGET_CHANNEL_ID" in c.youtube.last_error
            await asyncio.sleep(0.3)
            assert not c.youtube.chat_id and not fake.calls("/liveBroadcasts") and not fake.calls("/search")
            await c.stop()
    run(go())


def test_d_legacy_channel_id_still_works_as_the_target():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake, YOUTUBE_TARGET_CHANNEL_ID="", YOUTUBE_CHANNEL_ID=OWNER_CH)
        assert await wait_for(lambda: c.youtube.state == "live")
        await c.stop()
    run(go())


def test_target_must_look_like_a_channel_id_or_handle():
    async def go():
        c = await boot(FakeYouTube(), YOUTUBE_TARGET_CHANNEL_ID="https://youtube.com/@x")
        assert await wait_for(lambda: c.youtube.state == "config_error")
        assert "channel ID" in c.youtube.last_error
        await c.stop()
    run(go())


def test_moderator_account_check_reports_a_mismatch_but_grants_nothing():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, YOUTUBE_MODERATOR_ACCOUNT=OTHER_CH, **FAST)
        assert await wait_for(lambda: c.youtube.state == "config_error")
        assert "expects" in c.youtube.last_error and MOD_CH in c.youtube.last_error and not c.youtube.chat_id
        await c.stop()
        c = await boot(fake, YOUTUBE_MODERATOR_ACCOUNT="@signedin", **FAST)        # matches the account's handle
        assert await wait_for(lambda: c.youtube.state == "live")
        await c.stop()
    run(go())


# ---- E: the login is invalid or revoked
def test_e_revoked_login_gives_a_reconnect_instruction():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, YOUTUBE_REFRESH_TOKEN="rt-revoked")
        assert await wait_for(lambda: c.youtube.state == "error")
        assert "Reconnect" in c.youtube.last_error and not c.youtube.chat_id
        await c.stop()
    run(go())


# ---- F: YouTube refuses -> report it accurately, never claim success, never hammer
def test_f_moderator_who_cannot_read_the_chat_gets_a_permission_error_and_no_retry_storm():
    async def go():
        fake = moderator_setup()
        fake.pages = [FORBIDDEN]
        c = await boot(fake, **FAST)
        assert await wait_for(lambda: c.youtube.state == "no_permission")
        assert "appoint" in c.youtube.last_error and "moderator" in c.youtube.last_error
        reads = len(fake.calls("/liveChat/messages", "GET"))
        await asyncio.sleep(0.5)
        assert len(fake.calls("/liveChat/messages", "GET")) == reads, "must wait instead of retrying a call that cannot succeed"
        await c.stop()
    run(go())


def test_f_refused_delete_and_ban_are_reported_as_failures():
    async def go():
        fake = moderator_setup()
        fake.action_status = {"messages": FORBIDDEN, "bans": FORBIDDEN}
        c = await boot(fake, **FAST)
        assert await wait_for(lambda: c.youtube.state == "live")
        ok, err = await c.youtube.delete("m1")
        assert not ok and "not allowed to delete messages" in err and "moderator" in err
        ok, err = await c.youtube.ban("UC" + "s" * 22)
        assert not ok and "not allowed to ban" in err
        assert len(fake.calls("/liveChat/bans", "POST")) == 1 and c.youtube.status()["last_action_error"] == err
        c.youtube._denied.clear()   # the refusal above starts a cooldown (tested separately); clear it to test the protected-user answer
        fake.action_status = {"bans": (403, {"error": {"errors": [{"reason": "liveChatBanInsertionNotAllowed"}]}})}
        ok, err = await c.youtube.ban("UC" + "t" * 22)
        assert not ok and "moderator or the channel owner" in err
        await c.stop()
    run(go())


# ---- G: the stream ends -> stop cleanly, then follow the configured discovery strategy
def test_g_stream_end_detaches_and_discovery_resumes():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, **FAST)
        assert await wait_for(lambda: c.youtube.state == "live")
        searches = len(fake.calls("/search"))
        fake.search_ids = []
        fake.pages = [(403, {"error": {"errors": [{"reason": "liveChatEnded"}]}})]
        assert await wait_for(lambda: c.youtube.state == "offline")
        assert not c.youtube.chat_id and c.hub.status()["stream_live"] is False
        assert await wait_for(lambda: len(fake.calls("/search")) > searches, timeout=15), "discovery should resume"
        await c.stop()
    run(go())


def test_search_spend_is_capped_so_it_cannot_drain_the_daily_quota():
    async def go():
        fake = moderator_setup()
        fake.search_ids = []
        c = await boot(fake, YT_DETECT_BUDGET_FRACTION="0.03", YOUTUBE_TARGET_DETECT_INTERVAL_SECONDS="0.05")   # 300 units = 3 searches
        assert await wait_for(lambda: c.youtube.state == "search_paused", timeout=15)
        assert len(fake.calls("/search")) == 3 and "YOUTUBE_VIDEO_ID" in c.youtube.last_error
        await c.stop()
    run(go())
