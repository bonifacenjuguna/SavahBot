import asyncio
import time

from app.activity import ActivityLog, area_of, importance_of


def test_classification_and_secret_hiding(tmp_path):
    from app.db import Database
    from app.runtime_config import RuntimeConfig
    from app.config import Settings
    assert area_of("telegram_x") == "telegram" and area_of("app_name") == "settings"
    assert importance_of("lockdown_enabled") == "sensitive" and importance_of("mod_auto_mode") == "notable" and importance_of("app_name") == "routine"

    async def go():
        db = Database(f"sqlite:///{tmp_path}/a.db"); await db.connect()
        cfg = RuntimeConfig(Settings(), db)
        log = ActivityLog(db, cfg)
        await log.setting("telegram_bot_token", "old-secret", "new-secret")
        await log.setting("app_name", "A", "B")
        await log.record("moderation", "ban", "Ban for Sam")
        res = await log.query()
        blob = str(res["items"])
        assert "secret" not in blob.replace("secret", "", 0) or "old-secret" not in blob and "new-secret" not in blob
        assert [r["area"] for r in res["items"]] == ["moderation", "settings", "telegram"]
        assert (await log.query(importance="sensitive"))["items"][0]["after_v"] == ""
        assert len((await log.query(q="sam"))["items"]) == 1
        page = await log.query(limit=1)
        assert page["more"] and len((await log.query(before_id=page["items"][-1]["id"]))["items"]) == 2
    asyncio.run(go())


from tests.test_api import e2e  # noqa: E402


@e2e
async def test_notification_changes_and_chat_delete_reach_the_log(api):
    st, _ = await api.call("PATCH", "/api/notify/prefs", {"categories": {"stream.member": {"enabled": False}}})
    assert st == 200
    st, r = await api.call("GET", "/api/activity?area=notifications")
    assert st == 200 and any("notification settings" in i["summary"] for i in r["items"])
    st, r = await api.call("POST", "/api/settings".replace("settings", "variables"), {"name": "Tk", "value": "https://tiktok.com/@a", "kind": "link"})
    assert st == 200
    st, r = await api.call("GET", "/api/activity?area=variables")
    assert [i["summary"] for i in r["items"]] == ["Added $(Tk)"]
