"""Custom variables: validation, rendering inside commands, nesting, in-use protection."""
import asyncio
import time

from app.variables import CustomVars, VariableError, clean
from app.commands.variables import Ctx, Renderer
import pytest


def test_clean_rules():
    assert clean("$(TikTok)", " https://tiktok.com/@me ", "link") == ("TikTok", "https://tiktok.com/@me")
    for bad in (("1x", "v", "text"), ("user", "v", "text"), ("ok", "", "text"), ("ok", "a b", "link"), ("ok", "abc", "number"), ("ok", "x\ny", "text"), ("ok", "x", "weird")):
        with pytest.raises(VariableError):
            clean(*bad)


def test_render_save_and_delete(tmp_path):
    from app.db import Database
    import app.variables  # registers schema

    async def go():
        db = Database(f"sqlite:///{tmp_path}/v.db"); await db.connect()
        cv = CustomVars(db)
        r = Renderer.__new__(Renderer)
        r.cfg = type("C", (), {"get": lambda self, k: 50})(); r.store = None; r.uptime_fn = lambda: None; r.fetch = None; r.custom = cv
        await cv.save("TikTok", "https://tiktok.com/@me", "link", "", time.time())
        await cv.save("follow", "Find me: $(tiktok)", "text", "", time.time())
        out = await r.render("hi $(FOLLOW) and $(nope)", Ctx(channel="c"))
        assert out == "hi Find me: https://tiktok.com/@me and $(nope)"
        used = await cv.delete("tiktok")
        assert used and used[0]["name"] == "follow"
        assert await cv.delete("tiktok", force=True) == []
        assert await cv.lookup("tiktok") is None
    asyncio.run(go())
