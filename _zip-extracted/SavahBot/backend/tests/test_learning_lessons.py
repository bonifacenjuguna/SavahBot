"""Learning 2.0: the lesson ledger, honest accuracy, review queue, snapshots, import/export and the cold-start guard."""
import asyncio
import json
import time

import pytest

from app.store import ValidationFailed
from tests.test_intel_knowledge import rig


def run(coro):
    return asyncio.run(coro)


SPAM = ["double your bitcoin send now whatsapp me", "free robux click my profile now", "claim your prize winner selected click link",
        "buy followers cheap dm me now", "earn money fast from home contact us", "sub for sub subscribe to me now", "giveaway send me your password to win"]
HAM = ["what game are we playing today", "that was an amazing play nice one", "hello from nairobi good evening everyone", "how long is the stream tonight",
       "can you show the settings again please", "great stream thanks for the fun", "i like the new overlay it looks clean"]


def test_teach_adds_lessons_dedupes_and_relabels():
    async def go():
        r = await rig()
        a = await r.learn.teach("Free Robux click my profile", "spam")
        assert a["status"] == "added"
        assert (await r.learn.teach("free   robux click my PROFILE", "spam"))["status"] == "duplicate"
        b = await r.learn.teach("free robux click my profile", "ham")
        assert b["status"] == "relabelled" and b["id"] != a["id"]
        counts = await r.learn.ledger.counts()
        assert counts["spam"] == 0 and counts["ham"] == 1
        with pytest.raises(ValidationFailed):
            await r.learn.teach("x", "maybe")
        with pytest.raises(ValidationFailed):
            await r.learn.teach("   ", "spam")
    run(go())


def test_forget_removes_a_lesson_and_its_effect():
    async def go():
        r = await rig()
        for t in SPAM:
            await r.learn.teach(t, "spam")
        for t in HAM:
            await r.learn.teach(t, "ham")
        assert r.intel.learned_nb.docs["spam"] == 2 * len(SPAM)
        row = (await r.learn.ledger.search(label="spam"))["items"][0]
        assert await r.learn.forget(row["id"])
        assert not await r.learn.forget(row["id"])           # already gone
        assert r.intel.learned_nb.docs["spam"] == 2 * (len(SPAM) - 1)
    run(go())


def test_learning_survives_a_restart_because_the_ledger_is_in_the_database():
    async def go():
        r = await rig()
        for t in SPAM:
            await r.learn.teach(t, "spam")
        r.intel.set_learned(None, [], None)                   # forget everything in memory, as a restart would
        r.intel.learned_nb.docs = {"spam": 0, "ham": 0}
        await r.learn.load()
        assert r.intel.learned_nb.docs["spam"] == 2 * len(SPAM) and len(r.intel.learned_examples) == len(SPAM)
    run(go())


def test_cold_start_guard_keeps_a_few_lessons_from_changing_the_model():
    async def go():
        r = await rig({"INTEL_LEARN_MIN_LESSONS": "10"})
        before = r.intel.nb.docs["spam"]
        for t in SPAM[:3]:
            await r.learn.teach(t, "spam")
        assert r.intel.nb.docs["spam"] == before              # 3 lessons < 10: not used yet
        for t in SPAM[3:] + HAM:
            await r.learn.teach(t, "ham" if t in HAM else "spam")
        assert r.intel.nb.docs["spam"] > before               # 14 lessons >= 10: now counted
        q = await r.learn.quality()
        assert q["active"] and q["needed"] == 10
    run(go())


def test_accuracy_is_measured_on_messages_the_model_had_not_seen():
    async def go():
        r = await rig({"INTEL_LEARN_MIN_LESSONS": "1"})
        # the built-in model is trained, so it has an opinion before learning each lesson
        await r.learn.teach("double your bitcoin send me 0.1 btc and get 0.2 back whatsapp me", "spam")   # it should already know this
        await r.learn.teach("what time does the stream start tonight", "ham")
        q = await r.learn.quality()
        assert q["overall"]["n"] == 2 and q["overall"]["accuracy"] == 1.0
        # a wrong guess lowers it: label an obviously friendly sentence as spam
        await r.learn.teach("good morning everyone how are you all doing today", "spam")
        q = await r.learn.quality()
        assert q["overall"]["n"] == 3 and q["overall"]["accuracy"] < 1.0 and q["overall"]["false_alarms"] + q["overall"]["missed"] == 1
    run(go())


def test_drift_is_flagged_only_when_recent_accuracy_really_dropped():
    async def go():
        r = await rig()
        now = time.time()
        db = r.db
        async def put(age_days, label, pred, i):
            await db.execute("INSERT INTO learning_lessons (ts, label, source, body, flat, pred) VALUES (?, ?, 'decision', ?, ?, ?)",
                             (now - age_days * 86400, label, f"m{i}", f"m{i}", pred))
        for i in range(12):                                   # a good older period: always right
            await put(30, "spam", 0.9, i)
        for i in range(12, 24):                               # a bad recent period: always wrong
            await put(2, "spam", 0.1, i)
        q = await r.learn.quality(now)
        assert q["drifting"] and q["recent"]["accuracy"] == 0.0 and q["before"]["accuracy"] == 1.0
    run(go())


def test_review_queue_offers_uncertain_real_messages_only():
    async def go():
        r = await rig()
        assert (await r.learn.queue())["ready"] is True       # the built-in model is trained
        now = time.time()
        await r.db.execute("INSERT INTO chat_messages (platform, author_id, author_name, body, ts, demo) VALUES ('youtube','u','Ann',?,?,0)",
                           ("subscribe and check my channel for free stuff", now))
        await r.db.execute("INSERT INTO chat_messages (platform, author_id, author_name, body, ts, demo) VALUES ('demo','u','Demo',?,?,1)",
                           ("subscribe and check my channel for free stuff too", now))
        items = (await r.learn.queue())["items"]
        assert all(i["author"] != "Demo" for i in items)       # simulated chat is never offered
        for it in items:
            assert 0.25 <= it["p_spam"] <= 0.75
        if items:                                              # once taught, a message leaves the queue
            await r.learn.teach(items[0]["text"], "spam")
            assert all(i["text"] != items[0]["text"] for i in (await r.learn.queue())["items"])
    run(go())


def test_snapshots_restore_the_exact_set_and_reset_is_undoable():
    async def go():
        r = await rig()
        for t in SPAM[:4]:
            await r.learn.teach(t, "spam")
        snap = await r.learn.ledger.snapshot("Good state")
        assert snap["count"] == 4
        await r.learn.teach("extra spam line to remove later please", "spam")
        assert (await r.learn.restore(snap["id"])) == 4
        assert (await r.learn.ledger.counts())["total"] == 4
        cleared = await r.learn.reset()
        assert cleared == 4 and (await r.learn.ledger.counts())["total"] == 0
        snaps = await r.learn.ledger.snapshots()
        before_reset = next(s for s in snaps if s["name"] == "Before reset")
        await r.learn.restore(before_reset["id"])
        assert (await r.learn.ledger.counts())["total"] == 4
        with pytest.raises(KeyError):
            await r.learn.restore(99999)
    run(go())


def test_export_import_roundtrip_and_validation():
    async def go():
        r = await rig()
        for t in SPAM[:3]:
            await r.learn.teach(t, "spam")
        await r.learn.teach(HAM[0], "ham")
        data = await r.learn.ledger.export()
        r2 = await rig()
        res = await r2.learn.import_lessons(json.loads(json.dumps(data)))
        assert res["added"] == 4 and (await r2.learn.ledger.counts())["total"] == 4
        again = await r2.learn.import_lessons(data)
        assert again["added"] == 0 and again["skipped"] == 4
        for bad in ({"format": "other"}, {"format": "savahbot-lessons", "lessons": "x"}, [], None):
            with pytest.raises(ValidationFailed):
                await r2.learn.import_lessons(bad)
        mixed = {"format": "savahbot-lessons", "lessons": [{"label": "oops", "text": "x"}, {"label": "spam"}, "junk", {"label": "spam", "text": "ok line here"}]}
        assert (await r2.learn.import_lessons(mixed)) == {"added": 1, "skipped": 3}
    run(go())


def test_decisions_teach_but_simulated_ones_do_not_unless_allowed():
    async def go():
        r = await rig()
        await r.learn.feedback({"body": "free robux click my profile", "demo": 1, "author_name": "x", "id": 1}, "spam")
        assert (await r.learn.ledger.counts())["total"] == 0
        await r.learn.feedback({"body": "free robux click my profile", "demo": 0, "author_name": "x", "id": 2}, "spam")
        c = await r.learn.ledger.counts()
        assert c["spam"] == 1 and c["by_source"] == {"decision": 1}
        r2 = await rig({"INTEL_LEARN_FROM_DEMO": "true"})
        await r2.learn.feedback({"body": "free robux click my profile", "demo": 1, "id": 3}, "spam")
        assert (await r2.learn.ledger.counts())["total"] == 1
    run(go())


class Msg:
    def __init__(self, text, level="regular", platform="youtube"):
        self.text, self.level, self.platform, self.author_name = text, level, platform, "Reg"


def test_trusted_chat_teaches_ham_slowly_and_only_when_allowed():
    async def go():
        r = await rig()
        for i in range(6):
            await r.learn.trusted(Msg(f"this is a normal friendly sentence number {i} here"), "allow")
        assert (await r.learn.ledger.counts())["ham"] == 3     # at most 3 per minute
        await r.learn.trusted(Msg("a flagged line from a regular viewer"), "flag")
        await r.learn.trusted(Msg("hello there everyone watching", level="everyone"), "allow")
        assert (await r.learn.ledger.counts())["ham"] == 3
        r2 = await rig({"INTEL_LEARN_TRUSTED_HAM": "false"})
        await r2.learn.trusted(Msg("normal friendly sentence from a regular"), "allow")
        assert (await r2.learn.ledger.counts())["total"] == 0
    run(go())


def test_cap_forgets_the_oldest_lessons_first_and_retention_purges():
    async def go():
        r = await rig({"INTEL_EXAMPLE_CAP": "100"})
        words = [f"{a}{b}" for a in "bcdfghjklm" for b in "aeiou"]   # distinct words: the ledger folds digits away when comparing lines
        for i in range(105):
            await r.learn.teach(f"lesson {words[i % 50]} {words[(i * 7 + 3) % 50]}{'xyz'[i // 50]} alpha", "spam" if i % 2 else "ham")
        c = await r.learn.ledger.counts()
        assert c["total"] == 100
        oldest = await r.db.fetchone("SELECT note, active FROM learning_lessons ORDER BY ts ASC, id ASC LIMIT 1")
        assert oldest["active"] == 0 and "over the example limit" in oldest["note"]
        await r.db.execute("UPDATE learning_lessons SET ts = ? WHERE active = 0", (time.time() - 40 * 86400,))
        assert await r.learn.ledger.purge(time.time()) >= 5
    run(go())


def test_legacy_examples_and_decisions_are_migrated_once():
    async def go():
        r = await rig()
        await r.db.kv_set("intel_examples", json.dumps(["old saved spam line about bitcoin", "another old spam line"]))
        await r.db.execute("DELETE FROM learning_lessons")
        await r.db.execute("DELETE FROM kv WHERE key = 'lessons_migrated'")
        await r.db.execute("INSERT INTO mod_actions (ts, platform, author_id, author_name, body, action, status, demo) VALUES (?, 'youtube', 'u', 'A', ?, 'delete', 'rejected', 0)",
                           (time.time(), "a perfectly fine message that was rejected"))
        await r.learn.load()
        c = await r.learn.ledger.counts()
        assert c["spam"] == 2 and c["ham"] == 1
        await r.learn.load()
        assert (await r.learn.ledger.counts())["total"] == 3   # a second start does not duplicate anything
    run(go())
