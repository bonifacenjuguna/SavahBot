"""Regression tests for the safeguards found missing in the cross-version review.

Every test here runs against a FAKE YouTube/Google server. They prove that SavahBot asks for things correctly and reacts safely to the
answers it is given. They do NOT prove what the real YouTube API allows a moderator-only account to do."""
import asyncio
import json
import time
from contextlib import asynccontextmanager

import uvicorn
from fakes import wait_for
from test_api import e2e, free_port
from test_youtube import MOD_CH, OWNER_CH, FakeYouTube, boot, env, item, run
from test_youtube_target import FAST, FORBIDDEN, moderator_setup

from app.config import Settings
from app.container import Container
from app.db import Database
from app.http import request_raw
from app.main import create_app

OTHER_CH = "UC" + "x" * 22
ENDED = {"id": "e1", "snippet": {"type": "chatEndedEvent", "publishedAt": "2026-11-02T10:00:00Z"}, "authorDetails": {}}


QUIET = {"YT_MIN_POLL_SECONDS": "30", "YT_MAX_POLL_SECONDS": "30"}   # polling spends quota too; keep it out of tests that measure action costs


async def approval(c, ids, action="delete"):
    return await c.store.create_action({"ts": time.time(), "platform": "youtube", "author_id": "UCspam", "author_name": "Spammer",
                                        "message_ids": ids, "action": action, "status": "pending"})


# ================================================================ A. deletion batches and the permission cooldown
def test_batch_stops_after_the_first_permission_refusal():
    async def go():
        fake = FakeYouTube()
        fake.action_status = {"messages": FORBIDDEN}
        c = await boot(fake, **QUIET)
        assert await wait_for(lambda: c.youtube.state == "live" and c.youtube.polls >= 1)
        used = c.quota.used
        res = await c.hub.approve(await approval(c, [f"m{i}" for i in range(5)]))
        assert res["status"] == "failed"
        assert len(fake.calls("/liveChat/messages", "DELETE")) == 1, "one refusal must end the batch"
        assert c.quota.used - used == 20, "only the one request YouTube actually received is charged"
        assert "not allowed to delete messages" in res["error"] and res["error"].count(";") == 0
        await c.stop()
    run(go())


def test_repeated_attempts_during_the_cooldown_send_nothing_and_cost_nothing_then_resume():
    async def go():
        fake = FakeYouTube()
        fake.action_status = {"messages": FORBIDDEN}
        c = await boot(fake, **QUIET)
        assert await wait_for(lambda: c.youtube.state == "live" and c.youtube.polls >= 1)
        await c.hub.approve(await approval(c, ["a1", "a2"]))
        used = c.quota.used
        for _ in range(3):
            res = await c.hub.approve(await approval(c, ["b1", "b2", "b3"]))
            assert res["status"] == "failed" and "not allowed to delete" in res["error"]
        assert len(fake.calls("/liveChat/messages", "DELETE")) == 1, "cooldown: YouTube is not asked again"
        assert c.quota.used == used
        until, msg = c.youtube._denied["delete"]
        assert 290 < until - time.time() <= 300, "default cooldown is five minutes"
        c.youtube._denied["delete"] = (time.time() - 1, msg)   # the cooldown ends
        await c.hub.approve(await approval(c, ["c1"]))
        assert len(fake.calls("/liveChat/messages", "DELETE")) == 2, "after the cooldown YouTube is asked again"
        await c.stop()
    run(go())


def test_cooldown_length_is_configurable():
    async def go():
        fake = FakeYouTube()
        fake.action_status = {"messages": FORBIDDEN}
        c = await boot(fake, YOUTUBE_PERMISSION_RETRY_SECONDS="42")
        assert await wait_for(lambda: c.youtube.state == "live")
        await c.youtube.delete("m1")
        assert 40 < c.youtube._denied["delete"][0] - time.time() <= 42
        await c.stop()
    run(go())


def test_refused_ban_blocks_the_whole_approval_before_any_delete():
    async def go():
        fake = FakeYouTube()
        fake.action_status = {"bans": FORBIDDEN}
        c = await boot(fake)
        assert await wait_for(lambda: c.youtube.state == "live")
        res = await c.hub.approve(await approval(c, ["d1", "d2"], action="ban"))
        assert res["status"] == "failed" and len(fake.calls("/liveChat/bans", "POST")) == 1
        deletes, bans = len(fake.calls("/liveChat/messages", "DELETE")), len(fake.calls("/liveChat/bans", "POST"))
        res = await c.hub.approve(await approval(c, ["e1", "e2"], action="ban"))
        assert res["status"] == "failed" and "not allowed to ban" in res["error"]
        assert len(fake.calls("/liveChat/messages", "DELETE")) == deletes, "all-or-nothing: no deletes when the ban is known to be refused"
        assert len(fake.calls("/liveChat/bans", "POST")) == bans
        await c.stop()
    run(go())


def test_protected_user_refusal_does_not_start_a_cooldown():
    async def go():
        fake = FakeYouTube()
        fake.action_status = {"bans": (403, {"error": {"errors": [{"reason": "liveChatBanInsertionNotAllowed"}]}})}
        c = await boot(fake)
        assert await wait_for(lambda: c.youtube.state == "live")
        ok, err = await c.youtube.ban("UC" + "t" * 22)
        assert not ok and "moderator or the channel owner" in err
        assert c.youtube.refused("ban") == "", "a protected user says nothing about this account's permission"
        await c.stop()
    run(go())


def test_rejected_login_during_a_batch_stops_it_and_is_not_repeated():
    async def go():
        fake = FakeYouTube()
        fake.action_status = {"messages": (401, {"error": {"errors": [{"reason": "authError"}]}})}
        c = await boot(fake)
        assert await wait_for(lambda: c.youtube.state == "live")
        res = await c.hub.approve(await approval(c, [f"m{i}" for i in range(5)]))
        assert res["status"] == "failed" and "Reconnect" in res["error"]
        assert len(fake.calls("/liveChat/messages", "DELETE")) <= 2, "one try plus the single token-refresh retry, never the whole batch"
        n = len(fake.calls("/liveChat/messages", "DELETE"))
        await c.hub.approve(await approval(c, ["z1"]))
        assert len(fake.calls("/liveChat/messages", "DELETE")) == n
        await c.stop()
    run(go())


def test_a_successful_action_is_recorded_as_a_real_permission():
    async def go():
        fake = FakeYouTube()
        c = await boot(fake)
        assert await wait_for(lambda: c.youtube.state == "live")
        assert c.youtube.status()["permissions"]["delete"] is None
        ok, _ = await c.youtube.delete("m1")
        assert ok and c.youtube.status()["permissions"]["delete"] is True
        await c.stop()
    run(go())


# ================================================================ B. the moderator-account check must fail closed
def test_identity_lookup_failure_with_expected_account_means_no_monitoring():
    async def go():
        fake = moderator_setup()
        fake.identity_status = (500, {"error": {"errors": [{"reason": "backendError"}]}})
        c = await boot(fake, YOUTUBE_MODERATOR_ACCOUNT=MOD_CH, **FAST)
        assert await wait_for(lambda: c.youtube.state == "config_error")
        await asyncio.sleep(0.5)
        assert "will not monitor or moderate" in c.youtube.last_error and "YOUTUBE_MODERATOR_ACCOUNT" in c.youtube.last_error
        assert not c.youtube.chat_id and c.youtube.polls == 0
        assert fake.calls("/liveChat/messages", "GET") == [] and fake.calls("/search") == [], "nothing is read or searched without a confirmed account"
        fake.identity_status = None   # Google answers again: the account is confirmed and monitoring may proceed
        assert await c.youtube._prepare() == "" and c.youtube.account["channel_id"] == MOD_CH
        await c.stop()
    run(go())


def test_identity_lookup_failure_without_an_expected_account_keeps_the_old_behaviour():
    async def go():
        fake = moderator_setup()
        fake.identity_status = (500, {"error": {"errors": [{"reason": "backendError"}]}})
        c = await boot(fake, **FAST)   # YOUTUBE_MODERATOR_ACCOUNT not set: nothing to check against
        assert await wait_for(lambda: c.youtube.state == "live", timeout=15)
        await c.stop()
    run(go())


def test_wrong_account_with_a_failing_lookup_is_still_not_monitored():
    async def go():
        fake = moderator_setup()
        fake.identity_status = (500, {"error": {"errors": [{"reason": "backendError"}]}})
        c = await boot(fake, YOUTUBE_MODERATOR_ACCOUNT=OTHER_CH, **FAST)
        assert await wait_for(lambda: c.youtube.state == "config_error")
        await asyncio.sleep(0.4)
        assert not c.youtube.chat_id and c.youtube.polls == 0
        await c.stop()
    run(go())


def test_actions_are_refused_while_the_account_is_unconfirmed_or_wrong():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, YOUTUBE_MODERATOR_ACCOUNT=MOD_CH, **FAST)
        assert await wait_for(lambda: c.youtube.state == "live")
        ok, _ = await c.youtube.delete("m1")
        assert ok, "the confirmed, matching account may act"
        before = len(fake.calls("/liveChat/messages", "DELETE"))
        c.youtube.account = None
        ok, err = await c.youtube.delete("m2")
        assert not ok and "not been confirmed" in err
        ok, err = await c.youtube.preflight(1, "delete")
        assert not ok and "not been confirmed" in err
        c.youtube.account = {"channel_id": OTHER_CH, "title": "Someone else", "handle": ""}
        ok, err = await c.youtube.ban("UC" + "s" * 22)
        assert not ok and "expects" in err
        assert len(fake.calls("/liveChat/messages", "DELETE")) == before and fake.calls("/liveChat/bans", "POST") == []
        await c.stop()
    run(go())


def test_identity_lookup_does_not_spend_quota_it_does_not_have():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, BOT_MODE="demo")
        await c.quota.mark_exhausted()
        assert await c.youtube.refresh_identity() is None and "quota" in c.youtube._identity_error
        assert fake.calls("/channels") == []
        await c.stop()
    run(go())


def test_remembered_account_is_bound_to_the_refresh_token_it_was_read_with():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, **FAST)
        assert await wait_for(lambda: c.youtube.state == "live")
        saved = json.loads(await c.google.db.kv_get("youtube_account"))
        assert saved["account"]["channel_id"] == MOD_CH and saved["fp"] == await c.google.token_fingerprint()
        assert "rt-1" not in json.dumps(saved), "the token itself is never stored beside the account"
        assert (await c.youtube._load_identity())["channel_id"] == MOD_CH
        await c.google.db.kv_set("youtube_refresh_token", "rt-someone-else")   # the login changed behind the cache's back
        assert await c.youtube._load_identity() is None, "an account read with another token must never be reused"
        await c.stop()
    run(go())


# ================================================================ C. OAuth sign-in: who signed in is checked before anything is saved
@asynccontextmanager
async def signin_app(fake, **extra):
    port = free_port()
    c = Container(Settings(env=env(fake, **{"BOT_MODE": "demo", "YOUTUBE_REFRESH_TOKEN": "", **extra}), env_file=None), Database(":memory:"))
    server = uvicorn.Server(uvicorn.Config(create_app(c), host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    task = asyncio.ensure_future(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started
    c.base = f"http://127.0.0.1:{port}"
    yield c
    server.should_exit = True
    await asyncio.wait_for(task, 10)


async def sign_in(c) -> str:
    st, raw, _ = await request_raw("GET", f"{c.base}/api/youtube/oauth/callback?state={c.google.new_state()}&code=abc", follow_redirects=False)
    assert st == 200
    return raw.decode() if isinstance(raw, bytes) else str(raw)


def with_signin(fn):
    def wrapper():
        async def go():
            fake = FakeYouTube()
            fake.code_account = MOD_CH
            async with signin_app(fake, **getattr(fn, "env", {})) as c:
                await asyncio.wait_for(fn(fake, c), 60)
        run(go())
    wrapper.__name__ = fn.__name__
    return wrapper


def configured(**e):
    def deco(fn):
        fn.env = e
        return fn
    return deco


async def connect_as(c, refresh, channel, title):
    await c.google.db.kv_set("youtube_refresh_token", refresh)
    await c.youtube.remember_identity({"channel_id": channel, "title": title, "handle": ""})


@with_signin
async def test_signin_by_the_expected_account_is_accepted_and_identified(fake, c):
    await c.cfg.set("youtube_moderator_account", MOD_CH)
    msg = await sign_in(c)
    assert "connected as Signed-in account" in msg
    assert await c.google.connected() and await c.google.refresh_token() == "rt-new"
    assert c.youtube.account["channel_id"] == MOD_CH
    assert json.loads(await c.google.db.kv_get("youtube_account"))["fp"] == await c.google.token_fingerprint()


@with_signin
async def test_signin_by_the_wrong_account_is_rejected_and_nothing_is_saved(fake, c):
    await c.cfg.set("youtube_moderator_account", OTHER_CH)
    msg = await sign_in(c)
    assert "expects" in msg and "Could not connect" in msg
    assert not await c.google.connected() and await c.google.refresh_token() == ""
    assert await c.google.db.kv_get("youtube_account") is None


@with_signin
async def test_wrong_account_never_replaces_a_working_connection(fake, c):
    await c.cfg.set("youtube_moderator_account", OTHER_CH)
    await connect_as(c, "rt-1", OTHER_CH, "The right moderator")
    msg = await sign_in(c)
    assert "expects" in msg and "previous connection" in msg and "unchanged" in msg
    assert await c.google.refresh_token() == "rt-1", "the old refresh token stays"
    assert c.youtube.account["channel_id"] == OTHER_CH, "and so does its identity"
    assert await c.google.access_token(force=True), "the old login still works"


@with_signin
async def test_signin_with_a_failing_identity_lookup_is_rejected_when_an_account_is_expected(fake, c):
    await c.cfg.set("youtube_moderator_account", MOD_CH)
    fake.identity_status = (500, {"error": {"errors": [{"reason": "backendError"}]}})
    msg = await sign_in(c)
    assert "could not confirm" in msg and "not accepted" in msg
    assert not await c.google.connected()


@with_signin
async def test_signin_with_a_failing_lookup_is_accepted_but_unidentified_when_no_account_is_expected(fake, c):
    fake.identity_status = (500, {"error": {"errors": [{"reason": "backendError"}]}})
    msg = await sign_in(c)
    assert "could not say which account" in msg
    assert await c.google.connected() and c.youtube.account is None


@with_signin
async def test_signin_without_a_refresh_token_never_mixes_accounts(fake, c):
    await connect_as(c, "rt-1", OTHER_CH, "Old moderator")
    await c.google.access_token(force=True)
    old_access = c.google._access
    fake.code_refresh = None   # Google returns an access token only
    msg = await sign_in(c)
    assert "did not return a refresh token" in msg and "nothing was changed" in msg
    assert await c.google.refresh_token() == "rt-1", "the old refresh token is untouched"
    assert c.google._access == old_access, "the new account's access token was never adopted"
    assert c.youtube.account["channel_id"] == OTHER_CH


@with_signin
async def test_signin_without_a_refresh_token_and_no_earlier_login_connects_nothing(fake, c):
    fake.code_refresh = None
    msg = await sign_in(c)
    assert "did not return a refresh token" in msg and not await c.google.connected() and c.google._access == ""


@with_signin
async def test_switching_accounts_replaces_token_identity_and_old_refusals_together(fake, c):
    await connect_as(c, "rt-1", OTHER_CH, "Old moderator")
    c.youtube._denied["delete"] = (time.time() + 300, "old account was refused")
    c.youtube.perms["delete"] = False
    fake.code_refresh = "rt-b"
    msg = await sign_in(c)
    assert "connected as Signed-in account" in msg and "changed from Old moderator" in msg
    assert await c.google.refresh_token() == "rt-b" and c.google._access == "at-code"
    assert c.youtube.account["channel_id"] == MOD_CH, "the identity is the new account's"
    assert json.loads(await c.google.db.kv_get("youtube_account"))["fp"] == await c.google.token_fingerprint()
    assert c.youtube.refused("delete") == "" and c.youtube.perms["delete"] is None, "nothing refused for the old account is held against the new one"


@with_signin
async def test_disconnect_forgets_the_token_and_the_account(fake, c):
    await connect_as(c, "rt-1", MOD_CH, "Moderator")
    await c.google.disconnect()
    c.youtube.forget_identity()
    assert not await c.google.connected() and await c.google.db.kv_get("youtube_account") is None and c.youtube.account is None


@with_signin
async def test_signin_state_is_still_single_use_and_forged_states_are_refused(fake, c):
    st, raw, _ = await request_raw("GET", f"{c.base}/api/youtube/oauth/callback?state=forged&code=abc", follow_redirects=False)
    assert b"expired or is not valid" in (raw if isinstance(raw, bytes) else raw.encode())
    assert not await c.google.connected()


# ================================================================ D. chatEndedEvent and backoff
def test_chat_ended_event_stops_monitoring_immediately():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, **FAST)
        assert await wait_for(lambda: c.youtube.state == "live")
        fake.pages = [(200, {"items": [item("m1", "UCa", "hello there"), ENDED], "nextPageToken": "t", "pollingIntervalMillis": 10})]
        assert await wait_for(lambda: c.youtube.state == "offline")
        assert not c.youtube.chat_id and c.hub.status()["stream_live"] is False
        assert [m for m in c.hub.buffer if m["text"] == "hello there"], "messages in the same page are still delivered"
        await c.stop()
    run(go())


def test_error_backoff_is_exponential_capped_and_reset_by_success():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, BOT_MODE="demo")
        y = c.youtube
        assert [y._backoff() for _ in range(7)] == [30.0, 60.0, 120.0, 240.0, 300.0, 300.0, 300.0]
        y._errors = 0
        waits = [y._detect_failure(500, {}, 1) for _ in range(3)]
        assert waits == [30.0, 60.0, 120.0], "repeated server errors while searching back off"
        y._mark_offline()
        assert y._errors == 0 and y._backoff() == 30.0
        await c.stop()
    run(go())


def test_a_good_poll_resets_the_error_count():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, **FAST)
        c.youtube._errors = 4
        assert await wait_for(lambda: c.youtube.state == "live" and c.youtube.polls >= 1)
        assert c.youtube._errors == 0
        await c.stop()
    run(go())


# ================================================================ E. Verify access
def test_verify_reports_only_what_youtube_really_answered_and_never_searches():
    async def go():
        fake = moderator_setup()
        fake.videos["vidA"] = {"id": "vidA", "snippet": {"channelId": OWNER_CH, "title": "Live"}, "liveStreamingDetails": {"activeLiveChatId": "chatA"}}
        c = await boot(fake, BOT_MODE="demo", YOUTUBE_VIDEO_ID="vidA")
        v = await c.youtube.diagnose()
        by = {x["label"]: x for x in v["checks"]}
        assert by["Signed-in account"]["ok"] is True and by["Target channel"]["ok"] is True and by["Livestream"]["ok"] is True
        assert by["Read chat"]["ok"] is True
        assert by["Delete messages"]["ok"] is None and "no dry run" in by["Delete messages"]["detail"], "delete cannot be tested, so it is not claimed"
        assert by["Ban or time out"]["ok"] is None
        assert fake.calls("/search") == [] and v["ok"] is True
        await c.stop()
    run(go())


def test_verify_shows_a_refused_read_and_a_refused_delete():
    async def go():
        fake = moderator_setup()
        fake.videos["vidA"] = {"id": "vidA", "snippet": {"channelId": OWNER_CH, "title": "Live"}, "liveStreamingDetails": {"activeLiveChatId": "chatA"}}
        fake.pages = [FORBIDDEN]
        c = await boot(fake, BOT_MODE="demo", YOUTUBE_VIDEO_ID="vidA")
        v = await c.youtube.diagnose()
        read = next(x for x in v["checks"] if x["label"] == "Read chat")
        assert read["ok"] is False and "appoint" in read["detail"] and v["ok"] is False
        c.youtube.chat_id = "chatA"
        fake.action_status = {"messages": FORBIDDEN}
        await c.youtube.delete("m1")
        v = await c.youtube.diagnose()
        assert next(x for x in v["checks"] if x["label"] == "Delete messages")["ok"] is False
        await c.stop()
    run(go())


def test_verify_rejects_a_pinned_video_of_another_channel_and_a_missing_target():
    async def go():
        fake = moderator_setup()
        fake.videos["vidB"] = {"id": "vidB", "snippet": {"channelId": OTHER_CH}, "liveStreamingDetails": {"activeLiveChatId": "chatB"}}
        c = await boot(fake, BOT_MODE="demo", YOUTUBE_VIDEO_ID="vidB")
        v = await c.youtube.diagnose()
        live = next(x for x in v["checks"] if x["label"] == "Livestream")
        assert live["ok"] is False and "not the target" in live["detail"] and v["ok"] is False
        await c.stop()
        c = await boot(fake, BOT_MODE="demo", YOUTUBE_TARGET_CHANNEL_ID="")
        v = await c.youtube.diagnose()
        assert v["ok"] is False and any(x["label"] == "Target channel" and x["ok"] is False for x in v["checks"])
        await c.stop()
    run(go())


def test_verify_says_so_when_no_stream_is_attached_and_does_not_search_for_one():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, BOT_MODE="demo")
        v = await c.youtube.diagnose()
        live = next(x for x in v["checks"] if x["label"] == "Livestream")
        assert live["ok"] is None and "does not search" in live["detail"] and fake.calls("/search") == []
        await c.stop()
    run(go())


def test_verify_does_not_change_the_running_state():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, BOT_MODE="demo")
        c.youtube.state, c.youtube.last_error = "offline", "kept"
        await c.youtube.diagnose()
        assert (c.youtube.state, c.youtube.last_error) == ("offline", "kept")
        await c.stop()
    run(go())


@e2e
async def test_verify_route_requires_sign_in_and_reports_a_disconnected_account(api):
    from test_api import Api
    assert (await Api(api.base).call("POST", "/api/youtube/verify", auth=False))[0] == 401
    st, body = await api.call("POST", "/api/youtube/verify")
    assert st == 200 and body["ok"] is False and body["checks"][0]["label"] == "Google account"
