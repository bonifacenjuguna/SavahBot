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
        assert [b["text"] for b in buttons] == ["Approve", "Reject"]

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
