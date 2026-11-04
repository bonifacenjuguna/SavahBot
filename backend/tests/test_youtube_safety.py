"""Regression tests for the safety fixes on top of the account/target-channel work.

Everything here runs against a scripted FAKE of Google and YouTube. These tests prove SavahBot's own decisions (what it refuses,
what it saves, what it stops doing). They do NOT prove what the real YouTube API allows a moderator-only account to do."""
import asyncio
import time

from fakes import wait_for
from test_youtube import MOD_CH, OWNER_CH, SPAM, FakeYouTube, boot, item, live_and_polled, run
from test_youtube_target import FAST, FORBIDDEN, OTHER_CH, moderator_setup, video

import app.services.youtube as yt
from app.services.youtube import PendingLogin, YouTubeSource

NO_REASON = (500, {"error": {"errors": [{"reason": "backendError"}]}})
QUOTA = (403, {"error": {"errors": [{"reason": "quotaExceeded"}]}})


class SafetyFake(FakeYouTube):
    """FakeYouTube plus: tokens that belong to specific accounts, scripted sign-in responses, and failing identity lookups."""

    def __init__(self):
        super().__init__()
        self.channels_status = None                                      # e.g. (500, {...}): the identity lookup fails
        self.token_owner = {}                                            # access token -> channel id it belongs to
        self.refresh_owner = {}                                          # refresh token -> channel id its access tokens belong to
        self.code_tokens = {"access_token": "at-code", "refresh_token": "rt-new", "expires_in": 3600}
        self.identity_calls = []                                         # Authorization header of each identity lookup

    def _handle(self, method, path, query, body, headers):
        auth = headers.get("Authorization", "")
        if path == "/token":
            if body.get("grant_type") == "authorization_code":
                return 200, dict(self.code_tokens)
            rt = body.get("refresh_token")
            if rt in self.refresh_owner:
                self.token_calls += 1
                tok = f"at-{rt}-{self.token_calls}"
                self.token_owner[tok] = self.refresh_owner[rt]
                return 200, {"access_token": tok, "expires_in": 3600}
        if path.endswith("/channels") and not query.get("forHandle"):
            self.identity_calls.append(auth)
            if self.channels_status:
                return self.channels_status
            owner = self.token_owner.get(auth.replace("Bearer ", ""))
            if owner is not None:
                saved, self.account_channel = self.account_channel, owner
                try:
                    return super()._handle(method, path, query, body, headers)
                finally:
                    self.account_channel = saved
        return super()._handle(method, path, query, body, headers)


def safety_moderator_setup():
    """moderator_setup() (Creator A streams, Creator B is signed in) on the fake that can script identity and sign-in answers."""
    fake = SafetyFake()
    fake.account_channel = MOD_CH
    fake.search_ids = ["vidA"]
    fake.videos = {"vidA": video("vidA", OWNER_CH)}
    return fake


async def boot_fast(fake, **extra):
    YouTubeSource.IDENTITY_RETRY_EXPECTED = 0.2
    YouTubeSource.IDENTITY_RETRY = 0.2
    return await boot(fake, **extra)


def reset_class_timers():
    YouTubeSource.IDENTITY_RETRY_EXPECTED = 30.0
    YouTubeSource.IDENTITY_RETRY = 600.0


def calls_made(fake):
    """Everything after the identity lookup: anything that would attach to a stream or moderate."""
    return [p for p in ("/liveBroadcasts", "/search", "/videos", "/liveChat/messages", "/liveChat/bans") if fake.calls(p)]


# ======================================================================== 3. identity check must fail CLOSED
def test_identity_lookup_failure_blocks_monitoring_while_a_moderator_account_is_configured_then_recovers():
    async def go():
        fake = SafetyFake()
        fake.channels_status = NO_REASON
        try:
            c = await boot_fast(fake, YOUTUBE_MODERATOR_ACCOUNT=OWNER_CH)         # the RIGHT account, but it cannot be confirmed
            assert await wait_for(lambda: c.youtube.state == "config_error")
            assert "Could not confirm which Google account" in c.youtube.last_error and OWNER_CH in c.youtube.last_error
            await asyncio.sleep(0.5)                                              # several retries happen, none may attach
            assert not c.youtube.chat_id and calls_made(fake) == [] and len(fake.identity_calls) >= 2
            fake.channels_status = None                                           # Google answers again: now it proceeds
            assert await wait_for(lambda: c.youtube.state == "live", timeout=6)
            await c.stop()
        finally:
            reset_class_timers()
    run(go())


def test_quota_error_or_empty_answer_on_the_identity_lookup_also_blocks():
    async def go():
        try:
            for scripted in (QUOTA, (200, {})):
                fake = SafetyFake()
                fake.channels_status = scripted
                c = await boot_fast(fake, YOUTUBE_MODERATOR_ACCOUNT=OWNER_CH)
                assert await wait_for(lambda: c.youtube.state == "config_error")
                await asyncio.sleep(0.3)
                assert not c.youtube.chat_id and calls_made(fake) == []
                await c.stop()
            fake = SafetyFake()
            fake.account_channel = ""                                            # signed-in account has no YouTube channel at all
            c = await boot_fast(fake, YOUTUBE_MODERATOR_ACCOUNT=OWNER_CH)
            assert await wait_for(lambda: c.youtube.state == "config_error")
            assert "no channel found" in c.youtube.last_error and not c.youtube.chat_id
            await c.stop()
        finally:
            reset_class_timers()
    run(go())


def test_without_a_moderator_account_configured_a_failed_lookup_does_not_block():
    async def go():
        fake = safety_moderator_setup()
        fake.channels_status = NO_REASON            # nothing to enforce, so behaviour is unchanged from before: it is not blocked
        c = await boot(fake, **FAST)
        assert await wait_for(lambda: c.youtube.state == "live")
        assert c.youtube.account is None and c.youtube.chat_id == "chatA"
        await c.stop()
    run(go())


def test_setting_the_moderator_account_mid_stream_detaches_and_refuses_every_action():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, **FAST)
        assert await live_and_polled(c)
        await c.cfg.set("youtube_moderator_account", OTHER_CH)                   # does not match the signed-in account
        assert await wait_for(lambda: c.youtube.state == "config_error" and not c.youtube.chat_id)
        assert c.hub.status()["stream_live"] is False
        polls = len(fake.calls("/liveChat/messages", "GET"))
        ok, err = await c.youtube.delete("m1")
        assert not ok
        ok, err = await c.youtube.ban(OTHER_CH)
        assert not ok
        assert await c.youtube.send("hello") is False
        ok, err = await c.youtube.preflight(1, "ban")
        assert not ok and "expects" in err
        await asyncio.sleep(0.3)
        assert fake.calls("/liveChat/messages", "DELETE") == [] and fake.calls("/liveChat/bans") == [] and fake.calls("/liveChat/messages", "POST") == []
        assert len(fake.calls("/liveChat/messages", "GET")) == polls               # reading stopped too
        await c.stop()
    run(go())


def test_actions_are_refused_when_the_account_is_unknown_and_one_is_required():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, YOUTUBE_MODERATOR_ACCOUNT="@signedin", **FAST)
        assert await wait_for(lambda: c.youtube.state == "live")
        c.youtube.account = None                                                  # identity lost (e.g. a re-login in progress)
        ok, err = await c.youtube.delete("m1")
        assert not ok and "Could not confirm" in err and fake.calls("/liveChat/messages", "DELETE") == []
        await c.stop()
    run(go())


# ======================================================================== 4. deletion safeguards
async def pending_batch(c, n=3, action="ban"):
    rec = {"ts": time.time(), "platform": "youtube", "author_id": "UC" + "s" * 22, "author_name": "Spammer", "message_ids": [f"m{i}" for i in range(n)],
           "text": SPAM, "action": action, "duration": None, "score": 100, "reasons": [], "mode": "suggest", "demo": False, "status": "pending"}
    return await c.store.create_action(rec)


def test_a_batch_stops_after_the_first_permission_refusal():
    async def go():
        fake = moderator_setup()
        fake.action_status = {"messages": FORBIDDEN}
        c = await boot(fake, **FAST)
        assert await live_and_polled(c)
        id_ = await pending_batch(c, n=5)
        res = await c.hub.approve(id_)
        assert res["ok"] is False and res["status"] == "failed" and "not allowed to delete messages" in res["error"]
        assert len(fake.calls("/liveChat/messages", "DELETE")) == 1, "four more deletes cannot succeed and must not be attempted"
        assert fake.calls("/liveChat/bans") == [], "the ban must not run after its deletes were refused"
        assert (await c.store.get_action(id_))["status"] == "failed"
        await c.stop()
    run(go())


def test_permission_refusal_starts_a_five_minute_cooldown_with_no_requests_and_no_quota():
    async def go():
        fake = moderator_setup()
        fake.action_status = {"messages": FORBIDDEN}
        c = await boot(fake, **FAST)
        assert await live_and_polled(c)
        ok, first = await c.youtube.delete("m1")
        assert not ok and "not allowed to delete messages" in first and "5 min" in first
        assert 290 <= c.youtube.status()["denied_for"]["delete"] <= 300 and c.youtube.status()["permissions"]["delete"] is False
        used = c.quota.used
        for i in range(4):                                                       # repeated attempts while cooling down
            ok, err = await c.youtube.delete(f"again{i}")
            assert not ok and err == first
        assert len(fake.calls("/liveChat/messages", "DELETE")) == 1 and c.quota.used == used
        ok, err = await c.youtube.ban("UC" + "s" * 22)                           # a different kind of action is judged on its own
        assert ok and len(fake.calls("/liveChat/bans", "POST")) == 1
        c.youtube._denied["delete"] = (time.time() - 1, first)                   # five minutes pass
        fake.action_status = {}
        ok, err = await c.youtube.delete("later")
        assert ok and len(fake.calls("/liveChat/messages", "DELETE")) == 2 and c.youtube.status()["permissions"]["delete"] is True
        await c.stop()
    run(go())


def test_preflight_refuses_whole_approvals_during_the_cooldown():
    async def go():
        fake = moderator_setup()
        fake.action_status = {"messages": FORBIDDEN}
        c = await boot(fake, **FAST)
        assert await live_and_polled(c)
        await c.youtube.delete("m1")
        ok, err = await c.youtube.preflight(2, "ban")
        assert not ok and "not allowed to delete messages" in err
        ok, err = await c.youtube.preflight(0, "ban")                            # a ban with no deletes is not affected
        assert ok
        res = await c.hub.approve(await pending_batch(c, n=2))
        assert res["ok"] is False and len(fake.calls("/liveChat/messages", "DELETE")) == 1 and fake.calls("/liveChat/bans") == []
        await c.stop()
    run(go())


def test_repeated_auto_moderation_hits_youtube_once_not_once_per_message():
    async def go():
        fake = moderator_setup()
        fake.action_status = {"messages": FORBIDDEN}
        c = await boot(fake, MOD_MODE="auto", MOD_AUTO_ACTIONS="delete,timeout,ban", **FAST)
        assert await live_and_polled(c)
        fake.pages = [(200, {"items": [item(f"bad{i}", "UC" + str(i) * 22, SPAM, f"Spammer{i}") for i in range(4)],
                             "nextPageToken": "t9", "pollingIntervalMillis": 10})]
        assert await wait_for(lambda: sum(1 for m in c.hub.buffer if m["author_name"].startswith("Spammer")) == 4)
        await asyncio.sleep(0.3)
        assert len(fake.calls("/liveChat/messages", "DELETE")) == 1 and fake.calls("/liveChat/bans") == []
        await c.stop()
    run(go())


def test_a_protected_user_refusal_is_not_a_permission_denial_and_other_403s_are():
    async def go():
        fake = moderator_setup()
        fake.action_status = {"bans": (403, {"error": {"errors": [{"reason": "liveChatBanInsertionNotAllowed"}]}})}
        c = await boot(fake, **FAST)
        assert await live_and_polled(c)
        for who in ("UC" + "a" * 22, "UC" + "b" * 22):
            ok, err = await c.youtube.ban(who)
            assert not ok and "moderator or the channel owner" in err
        assert len(fake.calls("/liveChat/bans", "POST")) == 2 and "ban" not in c.youtube.status()["denied_for"]
        fake.action_status = {"messages": (403, {"error": {"errors": [{"reason": "liveChatEnded"}]}})}
        ok, err = await c.youtube.delete("m1")
        assert not ok and "no longer available" in err and "delete" not in c.youtube.status()["denied_for"]
        await c.stop()
    run(go())


def test_cooldown_and_permission_knowledge_are_cleared_when_the_stream_or_account_changes():
    async def go():
        fake = moderator_setup()
        fake.action_status = {"messages": FORBIDDEN}
        c = await boot(fake, **FAST)
        assert await live_and_polled(c)
        await c.youtube.delete("m1")
        assert c.youtube.status()["denied_for"] and c.youtube.status()["permissions"]["delete"] is False
        c.youtube.forget_identity()
        assert c.youtube.status()["denied_for"] == {} and c.youtube.status()["permissions"]["delete"] is None
        await c.stop()
    run(go())


# ======================================================================== 5. who signed in is checked before the login is kept
async def saved_login(c, token="rt-ok"):
    """A working connection the owner already has (stored the way the dashboard stores it)."""
    await c.db.kv_set("youtube_refresh_token", token)


def test_wrong_account_signin_is_not_saved_and_the_previous_connection_survives():
    async def go():
        fake = SafetyFake()
        fake.refresh_owner["rt-ok"] = MOD_CH
        c = await boot(fake, BOT_MODE="demo", YOUTUBE_REFRESH_TOKEN="", YOUTUBE_MODERATOR_ACCOUNT=MOD_CH)
        await saved_login(c)
        await c.youtube.refresh_identity()
        assert c.youtube.account["channel_id"] == MOD_CH
        old_access = await c.google.access_token()
        fake.token_owner["at-wrong"] = OTHER_CH
        fake.code_tokens = {"access_token": "at-wrong", "refresh_token": "rt-wrong", "expires_in": 3600}
        kept, msg = await c.youtube.accept_login(await c.google.begin_login("code"))
        assert kept is False and "NOT saved" in msg and OTHER_CH in msg and MOD_CH in msg and "previous connection was left unchanged" in msg
        assert await c.google.refresh_token() == "rt-ok" and await c.google.connected()           # the old login is intact
        assert c.google._access == old_access != "at-wrong"
        assert c.youtube.account["channel_id"] == MOD_CH
        await c.stop()
    run(go())


def test_right_account_signin_is_saved_and_says_who_is_connected():
    async def go():
        fake = SafetyFake()
        fake.token_owner["at-good"] = MOD_CH
        fake.code_tokens = {"access_token": "at-good", "refresh_token": "rt-good", "expires_in": 3600}
        c = await boot(fake, BOT_MODE="demo", YOUTUBE_REFRESH_TOKEN="", YOUTUBE_MODERATOR_ACCOUNT="@signedin")
        fake.account_channel = MOD_CH
        kept, msg = await c.youtube.accept_login(await c.google.begin_login("code"))
        assert kept is True and MOD_CH in msg and "permissions are what SavahBot will use" in msg
        assert await c.google.refresh_token() == "rt-good" and c.google._access == "at-good" and c.youtube.account["channel_id"] == MOD_CH
        assert fake.identity_calls[0] == "Bearer at-good"                          # the NEW token was used to ask who it is
        await c.stop()
    run(go())


def test_signin_whose_identity_cannot_be_confirmed_is_not_saved_when_an_account_is_expected():
    async def go():
        fake = SafetyFake()
        fake.refresh_owner["rt-ok"] = MOD_CH
        c = await boot(fake, BOT_MODE="demo", YOUTUBE_REFRESH_TOKEN="", YOUTUBE_MODERATOR_ACCOUNT=MOD_CH)
        await saved_login(c)
        fake.channels_status = NO_REASON
        kept, msg = await c.youtube.accept_login(await c.google.begin_login("code"))
        assert kept is False and "Could not confirm which Google account just signed in" in msg and "NOT saved" in msg and "previous connection" in msg
        assert await c.google.refresh_token() == "rt-ok"
        await c.stop()
        c2 = await boot(fake, BOT_MODE="demo", YOUTUBE_REFRESH_TOKEN="")           # nothing expected: saved, but honestly labelled
        kept, msg = await c2.youtube.accept_login(await c2.google.begin_login("code"))
        assert kept is True and "could not look up which account" in msg and "nothing was checked" in msg
        assert await c2.google.refresh_token() == "rt-new"
        await c2.stop()
    run(go())


def test_wrong_account_with_no_previous_connection_leaves_nothing_connected():
    async def go():
        fake = SafetyFake()
        fake.token_owner["at-wrong"] = OTHER_CH
        fake.code_tokens = {"access_token": "at-wrong", "refresh_token": "rt-wrong", "expires_in": 3600}
        c = await boot(fake, BOT_MODE="demo", YOUTUBE_REFRESH_TOKEN="", YOUTUBE_MODERATOR_ACCOUNT=MOD_CH)
        kept, msg = await c.youtube.accept_login(await c.google.begin_login("code"))
        assert kept is False and "previous connection" not in msg
        assert not await c.google.connected() and c.google._access == ""
        await c.stop()
    run(go())


def test_switching_to_a_different_account_releases_the_stream_and_old_permissions():
    async def go():
        fake = safety_moderator_setup()
        c = await boot(fake, **FAST)
        assert await live_and_polled(c)
        fake.action_status = {"messages": FORBIDDEN}
        await c.youtube.delete("m1")
        assert c.youtube.status()["denied_for"]
        fake.token_owner["at-other"] = OTHER_CH
        fake.code_tokens = {"access_token": "at-other", "refresh_token": "rt-other", "expires_in": 3600}
        kept, msg = await c.youtube.accept_login(await c.google.begin_login("code"))
        assert kept and "It replaces" in msg and "released" in msg
        assert c.youtube.account["channel_id"] == OTHER_CH and c.youtube.status()["denied_for"] == {}
        assert c.youtube.status()["permissions"] == {"read": None, "delete": None, "ban": None, "send": None}
        assert c.hub.status()["stream_live"] is False and not c.youtube.chat_id          # released until the new account re-discovers it
        await c.stop()
    run(go())


def test_signing_in_again_with_the_same_account_keeps_the_stream_attached():
    async def go():
        fake = SafetyFake()
        fake.account_channel = MOD_CH
        fake.token_owner["at-code"] = MOD_CH
        fake.videos = {"vidA": video("vidA", OWNER_CH)}
        fake.search_ids = ["vidA"]
        c = await boot(fake, **FAST)
        fake.refresh_owner["rt-1"] = MOD_CH
        assert await live_and_polled(c)
        kept, msg = await c.youtube.accept_login(await c.google.begin_login("code"))
        assert kept and "It replaces" not in msg and c.youtube.chat_id == "chatA"
        await c.stop()
    run(go())


# ======================================================================== 6. refresh tokens are never mixed between accounts
def test_a_signin_without_a_refresh_token_is_refused_and_never_borrows_the_old_one():
    async def go():
        fake = SafetyFake()
        fake.code_tokens = {"access_token": "at-new-account", "expires_in": 3600}        # Google sent no refresh token
        c = await boot(fake, BOT_MODE="demo", YOUTUBE_REFRESH_TOKEN="")
        await saved_login(c, "rt-old-account")
        before = c.google._access
        for attempt in (lambda: c.google.begin_login("code"), lambda: c.google.exchange_code("code")):
            try:
                await attempt()
                assert False, "must be refused"
            except RuntimeError as exc:
                assert "did not return a refresh token" in str(exc) and "unchanged" in str(exc)
        assert await c.google.refresh_token() == "rt-old-account"                   # still the old account's pair
        assert c.google._access == before != "at-new-account"                       # the new account's access token was never adopted
        await c.stop()
    run(go())


def test_a_refresh_that_was_in_flight_when_the_login_changed_is_discarded():
    async def go():
        fake = SafetyFake()
        c = await boot(fake, BOT_MODE="demo", YOUTUBE_REFRESH_TOKEN="")
        await saved_login(c, "rt-old-account")
        orig, state = yt.request_json, {"done": False}

        async def hooked(method, url, **kw):
            if (kw.get("form") or {}).get("grant_type") == "refresh_token" and not state["done"]:
                state["done"] = True
                await c.google.commit_login(PendingLogin("at-new-account", "rt-new-account", time.time() + 3600))   # user signs in meanwhile
                return 200, {"access_token": "at-OLD-ACCOUNT", "expires_in": 3600}                              # the old refresh answers late
            return await orig(method, url, **kw)

        yt.request_json = hooked
        try:
            tok = await c.google.access_token()
        finally:
            yt.request_json = orig
        assert tok == "at-new-account" and c.google._access == "at-new-account"
        assert await c.google.refresh_token() == "rt-new-account"
        await c.stop()
    run(go())


def test_a_login_commit_and_disconnect_change_the_generation():
    async def go():
        c = await boot(SafetyFake(), BOT_MODE="demo")
        g = c.google.generation
        await c.google.commit_login(PendingLogin("a", "r", time.time() + 100))
        await c.google.disconnect()
        assert c.google.generation == g + 2 and not c.google._access
        await c.stop()
    run(go())


# ======================================================================== 7. chatEndedEvent, backoff, Verify access
def test_chat_ended_event_stops_monitoring_immediately():
    async def go():
        fake = moderator_setup()
        c = await boot(fake, **FAST)
        assert await live_and_polled(c)
        fake.pages = [(200, {"items": [{"id": "e1", "snippet": {"type": "chatEndedEvent", "publishedAt": "2026-11-02T10:00:00Z"}},
                                       item("last", "UCfan", "bye", "Fan")], "nextPageToken": "t7", "pollingIntervalMillis": 10})]
        assert await wait_for(lambda: c.youtube.state == "offline" and not c.hub.stream_live)
        assert not c.youtube.chat_id and any(m["msg_id"] == "last" for m in c.hub.buffer)       # messages in that page were still handled
        await c.stop()
    run(go())


def test_backoff_doubles_up_to_five_minutes_and_resets_on_success():
    async def go():
        fake = SafetyFake()
        c = await boot(fake, BOT_MODE="demo")
        src = c.youtube
        assert [src._backoff() for _ in range(6)] == [30.0, 60.0, 120.0, 240.0, 300.0, 300.0]
        src._errors = 0
        src.chat_id = "chat1"
        fake.pages = [NO_REASON, NO_REASON]
        assert await src._poll() == 30.0 and await src._poll() == 60.0 and src.state == "error"
        assert src._errors == 2
        fake.pages = [(200, {"items": [], "nextPageToken": "t", "pollingIntervalMillis": 10})]
        await src._poll()
        assert src._errors == 0 and src.state == "live"
        await c.stop()
    run(go())


def test_loop_errors_back_off_instead_of_retrying_every_30_seconds():
    async def go():
        fake = SafetyFake()
        c = await boot(fake, BOT_MODE="demo")
        src = c.youtube
        waits = []

        async def boom():
            raise RuntimeError("Could not reach Google")

        src._step = boom
        real_sleep = asyncio.sleep

        async def fake_sleep(w):
            waits.append(w)
            if len(waits) >= 5:
                raise asyncio.CancelledError
            await real_sleep(0)

        orig = asyncio.sleep
        asyncio.sleep = fake_sleep
        try:
            try:
                await src._run()
            except asyncio.CancelledError:
                pass
        finally:
            asyncio.sleep = orig
        assert waits == [0.0, 30.0, 60.0, 120.0, 240.0]
        await c.stop()
    run(go())


def test_verify_access_is_honest_about_what_it_tested_and_never_searches():
    async def go():
        fake = SafetyFake()
        fake.account_channel = MOD_CH
        fake.videos = {"vidA": video("vidA", OWNER_CH)}
        c = await boot(fake, BOT_MODE="demo", YOUTUBE_VIDEO_ID="vidA")
        before = (c.youtube.state, c.youtube.last_error)
        res = await c.youtube.diagnose()
        by = {x["label"]: x for x in res["checks"]}
        assert res["ok"] and by["Signed-in account"]["ok"] and MOD_CH in by["Signed-in account"]["detail"]
        assert "moderator" in by["Role"]["detail"] and by["Livestream"]["ok"] and by["Read chat"]["ok"] is True
        assert by["Delete messages"]["ok"] is None and "no dry run" in by["Delete messages"]["detail"] and by["Ban / time out"]["ok"] is None
        assert not fake.calls("/search") and not fake.calls("/liveChat/messages", "DELETE") and not fake.calls("/liveChat/bans")
        assert (c.youtube.state, c.youtube.last_error) == before                       # a check never disturbs the running state
        fake.pages = [FORBIDDEN]
        res = await c.youtube.diagnose()
        assert res["ok"] is False and {x["label"]: x for x in res["checks"]}["Read chat"]["ok"] is False and c.youtube.status()["permissions"]["read"] is False
        await c.stop()
    run(go())


def test_verify_access_reports_account_and_target_problems_without_touching_the_chat():
    async def go():
        fake = SafetyFake()
        fake.account_channel = MOD_CH
        c = await boot(fake, BOT_MODE="demo", YOUTUBE_MODERATOR_ACCOUNT=OTHER_CH)
        res = await c.youtube.diagnose()
        by = {x["label"]: x for x in res["checks"]}
        assert res["ok"] is False and by["Expected account"]["ok"] is False and "expects" in by["Expected account"]["detail"]
        assert not fake.calls("/liveChat/messages") and not fake.calls("/videos") and not fake.calls("/search")
        await c.stop()
        c = await boot(SafetyFake(), BOT_MODE="demo")                                  # no stream and no pinned video: nothing to test, honestly
        res = await c.youtube.diagnose()
        by = {x["label"]: x for x in res["checks"]}
        assert by["Livestream"]["ok"] is None and "never searches" in by["Livestream"]["detail"] and "Read chat" not in by
        await c.stop()
        c = await boot(SafetyFake(), BOT_MODE="demo", YOUTUBE_REFRESH_TOKEN="", GOOGLE_CLIENT_ID="")
        res = await c.youtube.diagnose()
        assert res["ok"] is False and "Not connected" in res["checks"][0]["detail"]
        await c.stop()
    run(go())


def test_status_never_contains_tokens_or_secrets():
    async def go():
        fake = SafetyFake()
        c = await boot(fake, BOT_MODE="demo", YOUTUBE_MODERATOR_ACCOUNT=MOD_CH)
        await c.youtube.accept_login(await c.google.begin_login("code"))
        blob = str(c.youtube.status()) + str(await c.youtube.diagnose())
        for secret in ("csecret", "rt-1", "rt-new", "at-code"):
            assert secret not in blob
        await c.stop()
    run(go())
