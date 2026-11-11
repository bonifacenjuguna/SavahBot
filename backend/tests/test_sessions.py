"""Stream sessions: each livestream is its own record with its own chat; a new stream starts empty; a short drop resumes the same stream."""
import asyncio

from helpers import build_stack
from app.models import ChatMessage
from app.sessions import MIN_KEEP, RESUME_WINDOW
from test_api import e2e


async def settle(s):
    """Let the queued begin/end work finish."""
    for _ in range(50):
        await asyncio.sleep(0)
    async with s.hub._session_lock:
        pass


def say(text, who="ann", ts=1_000_000.0, **kw):
    return ChatMessage(platform="demo", author_id=who, author_name=who, text=text, ts=ts, demo=True, **kw)


def test_each_stream_gets_its_own_session_and_chat():
    async def go():
        s = await build_stack()
        await settle(s)
        h = s.hub
        first = h.session_id
        assert first, "starting the demo stream opens a session"
        for i, who in enumerate(["a", "b", "a"]):
            await h.ingest(say(f"hello {i}", who, ts=1_000_000.0 + i * 10))
        assert len(h.buffer) == 3
        # the stream ends
        h.stream_state(False)
        await settle(s)
        assert not h.session_id and len(h.buffer) == 3      # the last lines stay readable until the next stream starts
        done = await h.sessions.get(first)
        assert done["live"] is False and done["messages"] == 3 and done["chatters"] == 2 and done["top"][0] == {"name": "a", "lines": 2}
        # the next stream, some time later: fresh chat, fresh session
        await s.db.execute("UPDATE stream_sessions SET ended = ended - ? WHERE id = ?", (RESUME_WINDOW + 5, first))
        h.stream_state(True, "Second stream")
        await settle(s)
        assert h.session_id and h.session_id != first and not h.buffer and h.lines == 0
        await h.ingest(say("only here", "c"))
        assert [m["text"] for m in await h.sessions.chat(h.session_id)] == ["only here"]
        assert [m["text"] for m in await h.sessions.chat(first)] == ["hello 0", "hello 1", "hello 2"]
    asyncio.run(go())


def test_a_short_drop_resumes_the_same_stream_but_a_new_video_does_not():
    async def go():
        s = await build_stack()
        await settle(s)
        h, db = s.hub, s.db
        sid = h.session_id
        await h.ingest(say("one"))
        h.stream_state(False); await settle(s)
        h.stream_state(True, "again"); await settle(s)
        assert h.session_id == sid and (await h.sessions.get(sid))["resumed"]       # same demo "video", a moment later
        assert [m["text"] for m in h.buffer] == ["one"]                              # its chat is still there
        # too long a gap is a new stream
        h.stream_state(False); await settle(s)
        await db.execute("UPDATE stream_sessions SET ended = ended - ? WHERE id = ?", (RESUME_WINDOW + 5, sid))
        h.stream_state(True, "later"); await settle(s)
        assert h.session_id != sid
        # another video is a new stream even a second after the last one ended
        sid2 = h.session_id
        await h.ingest(say("two"))
        h.stream_state(False); await settle(s)
        h.source = type("Src", (), {"name": "youtube", "video_id": "VID12345678"})()
        h.cfg.set("bot_mode", "live")
        h.stream_state(True, "yt"); await settle(s)
        assert h.session_id not in (sid, sid2)
    asyncio.run(go())


def test_empty_short_sessions_leave_nothing_behind_and_orphans_are_closed():
    async def go():
        s = await build_stack()
        await settle(s)
        h = s.hub
        h.stream_state(False); await settle(s)
        assert (await h.sessions.search(True))["total"] == 0, "no chat and under MIN_KEEP seconds: dropped"
        # a session left open by a crash is closed at its last line
        await s.db.execute("INSERT INTO stream_sessions (id, started, title, demo) VALUES ('sorphan', 100, 'x', 1)")
        await s.db.execute("INSERT INTO chat_messages (platform, author_id, author_name, body, ts, demo, session_id) VALUES ('demo','a','a','hi',160,1,'sorphan')")
        assert await h.sessions.close_orphans() == 1
        r = await h.sessions.get("sorphan")
        assert r["ended"] == 160 and not r["live"]
        assert MIN_KEEP > 0
    asyncio.run(go())


def test_status_names_the_running_session():
    async def go():
        s = await build_stack()
        await settle(s)
        st = s.hub.status()
        assert st["session"]["id"] == s.hub.session_id
        s.hub.stream_state(False); await settle(s)
        assert s.hub.status()["session"] is None
    asyncio.run(go())


@e2e
async def test_streams_api(api):
    c = api.c if hasattr(api, "c") else None
    st, b = await api.call("GET", "/api/streams")
    assert st == 200 and "items" in b and b["retention_days"]
    st, rec = await api.call("GET", "/api/chat/recent?limit=5")
    assert st == 200 and "session" in rec
    st, _ = await api.call("GET", "/api/streams/nope")
    assert st == 404
    st, b = await api.call("PATCH", "/api/streams/nope", {"label": "x"})
    assert st == 404
    st, _ = await api.call("PATCH", "/api/streams/nope", {"bogus": 1})
    assert st == 422
    st, b = await api.call("GET", "/api/streams/last")
    assert st == 200 and "item" in b
