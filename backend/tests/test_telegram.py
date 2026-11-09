import asyncio

import pytest
from fakes import FakeTelegram, tg_message, wait_for

from app.config import Settings
from app.container import Container
from app.db import Database
from app.models import ChatMessage

OWNER = 4242
ENV = {"TELEGRAM_BOT_TOKEN": FakeTelegram.TOKEN, "PUBLIC_BASE_URL": "https://bot.example", "OWNER_PASSWORD": "pw-secret",
       "DEMO_AUTOSTART": "false", "TELEGRAM_OWNER_ID": str(OWNER)}


def run(coro):
    return asyncio.run(coro)


async def boot(fake, **extra):
    env = {**ENV, "TELEGRAM_API_BASE": fake.base, **extra}
    c = Container(Settings(env=env, env_file=None), Database(":memory:"))
    await c.start(wait_for_telegram=True)
    return c


async def say(c, user, text, chat=None):
    await c.telegram.handle_update(tg_message(user, text, chat))


def test_start_registers_webhook_with_secret_and_public_url():
    async def go():
        fake = FakeTelegram()
        c = await boot(fake)
        assert c.telegram.status()["bot_username"] == "SavahTestBot" and c.telegram.last_error == ""
        hook = fake.server.calls("/setWebhook")[0]["body"]
        assert hook["url"] == "https://bot.example/api/telegram/webhook"
        assert hook["secret_token"] == await c.telegram.webhook_secret() and len(hook["secret_token"]) >= 20
        assert hook["allowed_updates"] == ["message", "callback_query"] and hook["max_connections"] == 40
        assert fake.server.calls("/setMyCommands")
        await c.stop()
    run(go())


def test_webhook_requires_the_secret_header():
    async def go():
        fake = FakeTelegram()
        c = await boot(fake)
        upd = tg_message(OWNER, "/status")
        assert await c.telegram.handle_webhook(None, upd) is False
        assert await c.telegram.handle_webhook("wrong", upd) is False
        assert fake.sent() == []
        assert await c.telegram.handle_webhook(await c.telegram.webhook_secret(), upd) is True
        assert await wait_for(lambda: len(fake.sent()) == 1)
        assert "mode: demo" in fake.texts()[0] and fake.sent()[0]["chat_id"] == OWNER
        await c.stop()
    run(go())


def test_only_the_owner_is_ever_answered():
    async def go():
        fake = FakeTelegram()
        c = await boot(fake)
        await say(c, 999, "/status")                       # a stranger
        await say(c, 999, "/help")
        await say(c, OWNER, "/status", chat=-100123)        # owner, but not in a private chat
        await c.telegram.handle_update({"update_id": 1, "message": {"from": {"id": 999}, "chat": {"id": 999, "type": "private"}, "text": "hi"}})
        await c.telegram.handle_update({"update_id": 2, "callback_query": {"id": "q", "from": {"id": 999}, "data": "approve:1"}})
        assert fake.sent() == [] and not fake.server.calls("/answerCallbackQuery")
        await say(c, OWNER, "/nonsense")
        assert "Unknown command" in fake.texts()[-1]
        await c.stop()
    run(go())


def test_claim_binds_owner_once_and_throttles_guessing():
    async def go():
        fake = FakeTelegram()
        env_without_owner = {"TELEGRAM_OWNER_ID": ""}
        c = await boot(fake, **env_without_owner)
        assert not c.telegram.status()["owner_bound"]
        await say(c, 7, "/status")                          # unbound bot answers nobody
        for _ in range(5):
            await say(c, 7, "/claim wrong")
        assert fake.sent() == []
        await say(c, 7, "/claim pw-secret")                 # throttled now, even with the right password
        assert fake.sent() == []
        await say(c, 8, "/claim pw-secret")                 # a different account that knows the password
        assert "now the owner" in fake.texts()[-1] and await c.telegram.owner_id() == 8
        await say(c, 7, "/status")                          # 7 is not the owner
        assert len(fake.sent()) == 1
        await say(c, 9, "/claim pw-secret")                 # cannot claim again
        assert len(fake.sent()) == 1
        assert await c.db.kv_get("telegram_owner_id") == "8"
        await c.stop()
    run(go())


def test_mode_and_moderation_commands_change_runtime_settings():
    async def go():
        fake = FakeTelegram()
        c = await boot(fake)
        await say(c, OWNER, "/mod auto")
        assert c.cfg.get("mod_mode") == "auto" and "now auto" in fake.texts()[-1]
        await say(c, OWNER, "/mod banana")
        assert "Use /mod off" in fake.texts()[-1] and c.cfg.get("mod_mode") == "auto"
        await say(c, OWNER, "/mode live")
        assert c.cfg.get("bot_mode") == "live" and c.hub.status()["source"] == "youtube"
        await say(c, OWNER, "/mode demo")
        assert c.cfg.get("bot_mode") == "demo" and c.hub.status()["stream_live"] is True
        await c.stop()
    run(go())


def test_notes_reminders_permit_and_say():
    async def go():
        fake = FakeTelegram()
        c = await boot(fake)
        await say(c, OWNER, "/note buy a mic stand")
        await say(c, OWNER, "/notes")
        assert "Saved note #1" in fake.texts()[-2] and "buy a mic stand" in fake.texts()[-1]
        await say(c, OWNER, "/delnote 1")
        assert (await c.store.list_notes()) == []

        await say(c, OWNER, "/remind 30m stretch")
        assert "Reminder #1 set" in fake.texts()[-1]
        await say(c, OWNER, "/remind daily 08:00 plan the stream")
        assert "repeating daily" in fake.texts()[-1]
        await say(c, OWNER, "/remind whenever never")
        assert "could not read the time" in fake.texts()[-1]
        await say(c, OWNER, "/reminders")
        assert fake.texts()[-1].count("#") == 2
        await say(c, OWNER, "/delremind 1")
        assert len(await c.store.list_reminders("pending")) == 1

        await say(c, OWNER, "/permit Alice 45")
        assert c.permits.is_permitted("alice")
        await say(c, OWNER, "/say hello chat")
        assert "Sent." in fake.texts()[-1] and c.hub.buffer[-1]["text"] == "hello chat"
        await say(c, OWNER, "/demo")
        assert "spam_raid" in fake.texts()[-1]
        await c.stop()
    run(go())


def test_pending_list_and_inline_buttons_approve_and_reject():
    async def go():
        fake = FakeTelegram()
        c = await boot(fake, MOD_MODE="suggest")
        for i in range(2):
            await c.hub.ingest(ChatMessage("demo", f"s{i}", f"spam{i}", "FREE ROBUX at robux-gift.xyz right now everybody",
                                           "everyone", msg_id=f"m{i}", demo=True))
        assert await wait_for(lambda: any("Approval needed" in t for t in fake.texts()))
        n_before = len(fake.sent())
        await say(c, OWNER, "/pending")
        assert len(fake.sent()) > n_before and "2 waiting" in fake.texts()[-1]
        buttons = [b for b in fake.sent() if b.get("reply_markup")][0]["reply_markup"]["inline_keyboard"][0]
        assert [b["text"] for b in buttons] == ["✅ Approve", "❌ Reject"]

        pending = await c.store.pending_actions()
        cb = lambda uid, data: {"update_id": 5, "callback_query": {"id": "cq1", "from": {"id": uid}, "data": data,
                                "message": {"message_id": 7, "chat": {"id": OWNER}, "text": "Approval needed"}}}
        await c.telegram.handle_update(cb(999, f"approve:{pending[0]['id']}"))     # stranger: ignored
        assert (await c.store.get_action(pending[0]["id"]))["status"] == "pending"
        await c.telegram.handle_update(cb(OWNER, f"approve:{pending[0]['id']}"))
        assert (await c.store.get_action(pending[0]["id"]))["status"] == "simulated"
        assert fake.server.calls("/answerCallbackQuery")[-1]["body"]["text"] == "Done: simulated"
        assert "Approve: Done" in fake.server.calls("/editMessageText")[-1]["body"]["text"]
        await c.telegram.handle_update(cb(OWNER, f"reject:{pending[1]['id']}"))
        assert (await c.store.get_action(pending[1]["id"]))["status"] == "rejected"
        await c.telegram.handle_update(cb(OWNER, f"approve:{pending[1]['id']}"))     # already resolved
        assert fake.server.calls("/answerCallbackQuery")[-1]["body"]["text"] == "This request is no longer pending."
        await say(c, OWNER, "/approve all")
        assert "Approved 0" in fake.texts()[-1]
        await c.stop()
    run(go())


def test_polling_mode_consumes_updates_and_toggle_switches_back():
    async def go():
        fake = FakeTelegram()
        c = await boot(fake, TELEGRAM_MODE="polling")
        assert fake.server.calls("/deleteWebhook") and not fake.server.calls("/setWebhook")
        assert c.telegram.status()["polling"] is True
        fake.updates.append(tg_message(OWNER, "/status"))
        assert await wait_for(lambda: len(fake.sent()) == 1)
        assert c.telegram._offset > 0

        await say(c, OWNER, "/tgmode webhook")             # toggle at runtime
        assert c.cfg.get("telegram_mode") == "webhook"
        assert fake.server.calls("/setWebhook") and c.telegram.status()["polling"] is False
        await say(c, OWNER, "/tgmode polling")
        assert c.telegram.status()["polling"] is True and c.telegram.webhook_url == ""
        await c.stop()
    run(go())


def test_webhook_mode_without_public_url_explains_what_is_missing():
    async def go():
        fake = FakeTelegram()
        c = await boot(fake, PUBLIC_BASE_URL="")
        assert "PUBLIC_BASE_URL" in c.telegram.last_error and not fake.server.calls("/setWebhook")
        await c.stop()
    run(go())


def test_telegram_errors_never_leak_the_bot_token():
    async def go():
        fake = FakeTelegram()
        fake.fail_with = (401, "Unauthorized")
        c = await boot(fake)
        assert "Unauthorized" in c.telegram.last_error and FakeTelegram.TOKEN not in c.telegram.last_error
        await c.telegram.notify("hi")
        assert FakeTelegram.TOKEN not in c.telegram.last_error
        await c.stop()
        # unreachable server: still no token in the message
        c2 = Container(Settings(env={**ENV, "TELEGRAM_API_BASE": "http://127.0.0.1:1"}, env_file=None), Database(":memory:"))
        await c2.start(wait_for_telegram=True)
        assert "network error" in c2.telegram.last_error and FakeTelegram.TOKEN not in c2.telegram.last_error
        await c2.stop()
    run(go())


def test_unconfigured_telegram_is_harmless():
    async def go():
        c = Container(Settings(env={"DEMO_AUTOSTART": "false"}, env_file=None), Database(":memory:"))
        await c.start(wait_for_telegram=True)
        assert c.telegram.status()["configured"] is False
        await c.telegram.notify("nobody to tell")
        await c.hub.ingest(ChatMessage("demo", "s", "spam", "FREE ROBUX at robux-gift.xyz", "everyone", demo=True))
        assert len(await c.store.pending_actions()) == 1        # approvals still queue for the dashboard
        await c.stop()
    run(go())


# ------------------------------------------------------------------ 1.1.2: rich messages, menu buttons, dated search
def test_date_words_become_owner_timezone_ranges():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.services.telegram_ui import parse_range
    tz = "Africa/Nairobi"
    now = datetime(2026, 11, 5, 15, 30, tzinfo=ZoneInfo(tz))
    day = lambda y, m, d: datetime(y, m, d, tzinfo=ZoneInfo(tz)).timestamp()
    assert parse_range(["giveaway", "today"], tz, now) == (day(2026, 11, 5), None, "today", ["giveaway"])
    assert parse_range(["yesterday"], tz, now)[:2] == (day(2026, 11, 4), day(2026, 11, 5))
    assert parse_range(["2026-11-01..2026-11-03", "robux"], tz, now)[:2] == (day(2026, 11, 1), day(2026, 11, 4))   # until is exclusive and covers the whole last day
    assert parse_range(["2026-11-02"], tz, now)[:2] == (day(2026, 11, 2), day(2026, 11, 3))
    assert parse_range(["3d"], tz, now)[0] == now.timestamp() - 3 * 86400
    assert parse_range(["2026-13-45", "hello"], tz, now) == (None, None, "", ["2026-13-45", "hello"])   # an impossible date is just a word
    assert parse_range(["hello"], tz, now) == (None, None, "", ["hello"])


def test_rich_messages_are_html_and_viewer_text_is_escaped():
    async def go():
        fake = FakeTelegram()
        c = await boot(fake)
        await say(c, OWNER, "/status")
        assert fake.sent()[-1]["parse_mode"] == "HTML" and "<b>" in fake.texts()[-1]
        await c.store.add_chat({"platform": "demo", "author_id": "x", "author_name": "<b>evil</b>", "text": "a < b & c", "ts": __import__("time").time(), "demo": True})
        await say(c, OWNER, "/find today")
        out = fake.texts()[-1]
        assert "&lt;b&gt;evil&lt;/b&gt;" in out and "a &lt; b &amp; c" in out and "<b>evil</b>" not in out
        await say(c, OWNER, "/note use <tags> carefully")            # plain replies stay plain text
        assert "parse_mode" not in fake.sent()[-1]
        await c.stop()
    run(go())


def test_find_and_history_filter_by_date_and_explain_themselves():
    async def go():
        import time
        fake = FakeTelegram()
        c = await boot(fake)
        now = time.time()
        await c.store.add_chat({"platform": "demo", "author_id": "a", "author_name": "ann", "text": "old giveaway", "ts": now - 5 * 86400, "demo": True})
        await c.store.add_chat({"platform": "demo", "author_id": "b", "author_name": "bob", "text": "new giveaway", "ts": now - 60, "demo": True})
        await say(c, OWNER, "/find giveaway")
        assert "old giveaway" in fake.texts()[-1] and "new giveaway" in fake.texts()[-1]
        await say(c, OWNER, "/find giveaway today")
        assert "new giveaway" in fake.texts()[-1] and "old giveaway" not in fake.texts()[-1]
        await say(c, OWNER, "/find giveaway 1d")
        assert "old giveaway" not in fake.texts()[-1]
        await say(c, OWNER, "/find")
        assert "Examples" in fake.texts()[-1]
        await say(c, OWNER, "/find nothing-like-this")
        assert "No saved chat matches" in fake.texts()[-1]
        await say(c, OWNER, "/history yesterday")
        assert "Nothing found" in fake.texts()[-1]
        await c.stop()
    run(go())


def test_menu_buttons_edit_the_message_in_place_and_switch_modes():
    async def go():
        fake = FakeTelegram()
        c = await boot(fake)
        await say(c, OWNER, "/menu")
        kb = fake.sent()[-1]["reply_markup"]["inline_keyboard"]
        assert any(b["callback_data"] == "m:status" for row in kb for b in row)
        cb = lambda uid, data: {"update_id": 9, "callback_query": {"id": "q", "from": {"id": uid}, "data": data, "message": {"message_id": 7, "chat": {"id": OWNER}, "text": "x"}}}
        await c.telegram.handle_update(cb(999, "m:status"))                       # a stranger gets nothing
        assert not fake.server.calls("/editMessageText")
        await c.telegram.handle_update(cb(OWNER, "m:status"))
        edit = fake.server.calls("/editMessageText")[-1]["body"]
        assert edit["message_id"] == 7 and edit["parse_mode"] == "HTML" and "mode: demo" in edit["text"]
        await c.telegram.handle_update(cb(OWNER, "set:mod:auto"))
        assert c.cfg.get("mod_mode") == "auto"
        assert "✔ ⚡ Auto" in str(fake.server.calls("/editMessageText")[-1]["body"]["reply_markup"])
        await c.telegram.handle_update(cb(OWNER, "set:bot:live"))
        assert c.cfg.get("bot_mode") == "live"
        await c.telegram.handle_update(cb(OWNER, "set:mod:bogus"))                 # junk never changes anything
        assert c.cfg.get("mod_mode") == "auto"
        await c.stop()
    run(go())


def test_html_that_telegram_rejects_is_resent_as_plain_text():
    async def go():
        fake = FakeTelegram()
        c = await boot(fake)
        from app.services.telegram_ui import Rich
        real = c.telegram.client.call
        calls = []

        async def flaky(method, params=None, timeout=15.0):
            calls.append(dict(params or {}))
            if (params or {}).get("parse_mode") == "HTML":
                from app.services.telegram import TelegramError
                raise TelegramError("sendMessage: Bad Request: can't parse entities (HTTP 400)")
            return await real(method, params, timeout)
        c.telegram.client.call = flaky
        await c.telegram.client.send(OWNER, Rich("<b>Hello</b> &amp; welcome"))
        assert calls[-1].get("parse_mode") is None and calls[-1]["text"] == "Hello & welcome"
        await c.stop()
    run(go())


def test_control_master_switch_pause_and_read_only():
    async def go():
        fake = FakeTelegram()
        c = await boot(fake)
        ctl = c.telegram.control
        await say(c, OWNER, "/status")
        assert len(fake.sent()) == 1
        # read-only: the show commands work, the changing ones are refused with an explanation
        await ctl.update({"actions": False})
        await say(c, OWNER, "/mode live")
        assert "read-only" in fake.texts()[-1] and c.cfg.get("bot_mode") == "demo"
        await say(c, OWNER, "/status")
        assert "mode: demo" in fake.texts()[-1]
        await c.telegram.handle_update({"update_id": 3, "callback_query": {"id": "q9", "from": {"id": OWNER}, "data": "set:bot:live", "message": {"chat": {"id": OWNER}, "message_id": 1}}})
        assert c.cfg.get("bot_mode") == "demo"
        await ctl.update({"actions": True})
        # pause: silent both ways, then it ends by itself
        await ctl.update({"pause_minutes": 30})
        n = len(fake.sent())
        await say(c, OWNER, "/status")
        await c.telegram.notify("alert")
        assert len(fake.sent()) == n
        await ctl.update({"pause_minutes": 0})
        await c.telegram.notify("alert")
        assert len(fake.sent()) == n + 1
        # master switch: webhook removed, nothing heard, nothing sent
        await ctl.update({"enabled": False})
        assert fake.server.calls("/deleteWebhook") and c.telegram.webhook_url == ""
        n = len(fake.sent())
        await say(c, OWNER, "/status")
        await c.telegram.notify("alert")
        assert len(fake.sent()) == n
        await ctl.update({"enabled": True})
        assert c.telegram.webhook_url
        kinds = {e["kind"] for e in await ctl.entries()}
        assert {"control", "command", "blocked"} <= kinds
        await c.stop()
    run(go())


def test_control_unlink_claim_lock_rotate_and_shutdown():
    async def go():
        fake = FakeTelegram()
        c = await boot(fake, TELEGRAM_OWNER_ID="")
        ctl = c.telegram.control
        await say(c, 777, "/claim pw-secret")
        assert await c.telegram.owner_id() == 777
        old = await c.telegram.webhook_secret()
        await ctl.rotate_secret()
        assert await c.telegram.webhook_secret() != old
        assert await c.telegram.handle_webhook(old, tg_message(777, "/status")) is False
        await ctl.unlink_owner()
        assert await c.telegram.owner_id() == 0
        await ctl.update({"claim_open": False})
        await say(c, 888, "/claim pw-secret")
        assert await c.telegram.owner_id() == 0                  # claiming is closed
        await ctl.update({"claim_open": True})
        await say(c, 888, "/claim pw-secret")
        assert await c.telegram.owner_id() == 888
        out = await ctl.shutdown()
        assert out["ok"] and "/revoke" in out["next"]
        p = await ctl.prefs()
        assert p["enabled"] is False and p["claim_open"] is False and await c.telegram.owner_id() == 0
        text = " ".join(e["detail"] for e in await ctl.entries())
        assert "pw-secret" not in text and FakeTelegram.TOKEN not in text
        await c.stop()
    run(go())


from tests.test_api import e2e  # noqa: E402


@e2e
async def test_telegram_control_api(api):
    st, b = await api.call("GET", "/api/telegram/control")
    assert st == 200 and b["state"] == "on" and b["enabled"] and b["actions"]
    st, b = await api.call("POST", "/api/telegram/control", {"actions": False, "notify": {"reminders": False}})
    assert st == 200 and b["state"] == "read-only" and b["notify"]["reminders"] is False
    st, b = await api.call("POST", "/api/telegram/control", {"pause_minutes": 20})
    assert st == 200 and b["state"] == "paused" and b["pause_until"] > 0
    assert (await api.call("POST", "/api/telegram/control", {"pause_minutes": 0}))[1]["pause_until"] == 0
    assert (await api.call("POST", "/api/telegram/control", {"pause_minutes": -5}))[0] == 422
    assert (await api.call("POST", "/api/telegram/control", {"notify": {"nonsense": True}}))[0] == 422
    assert (await api.call("POST", "/api/telegram/control", {"bogus": 1}))[0] == 422
    assert (await api.call("POST", "/api/telegram/shutdown", {}))[0] == 400            # needs confirmation
    st, b = await api.call("POST", "/api/telegram/shutdown", {"confirm": True})
    assert st == 200 and b["state"] == "off" and b["claim_open"] is False and "/revoke" in b["next"]
    st, b = await api.call("GET", "/api/telegram/log")
    assert st == 200 and any(e["kind"] == "shutdown" for e in b["items"])
    assert (await api.call("DELETE", "/api/telegram/log"))[0] == 200
