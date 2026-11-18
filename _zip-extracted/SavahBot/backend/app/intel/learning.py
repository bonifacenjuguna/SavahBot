"""Learning from the owner's decisions, without any AI model.

Every Approve and Reject is a label. Approved means 'this really was a problem', rejected means 'it was not'.
From those labels the bot:
  * trains its Naive Bayes model and remembers approved spam messages for similarity matching (instantly),
  * works out how trustworthy each detector has been (precision from real decisions, computed from history),
  * suggests phrases that keep showing up in approved actions and safe phrases from rejected ones,
  * tests shadow detectors against past decisions and suggests promoting the ones that would have agreed,
  * in 'auto' mode applies the confident suggestions itself.
Every change is written to the log with an undo recipe.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter, defaultdict
from typing import Any

from ..store import ValidationFailed
from .bayes import NaiveBayes
from .lessons import Ledger
from .core import DETECTORS, Intel
from .textkit import deep_normalize, flat, ngrams, tokens

logger = logging.getLogger("savahbot.intel")

_STOP = set("the a an and or but to of in on at is are was were be been it this that these those i you he she we they my your our his her "
            "their me us them for with from as by so if then than too very just not no yes do does did have has had will would can could "
            "should may might am im ive dont cant wont thats its what who how why when where which there here up out all any some more "
            "also now pls please ok okay lol".split())
MAX_EXAMPLES = 300


def _signal_names(reasons: list[str]) -> list[str]:
    return [r.split(":")[0].strip() for r in reasons if r]


class Learning:
    def __init__(self, db: Any, cfg: Any, intel: Intel, knowledge: Any) -> None:
        self.db, self.cfg, self.intel, self.knowledge = db, cfg, intel, knowledge
        self.ledger = Ledger(db, cfg)
        self.last_refresh = 0.0
        self._trusted_times: list[float] = []

    # ------------------------------------------------------------------ persistence
    async def load(self) -> None:
        scales: dict[str, float] = {}
        try:
            scales = {k: float(v) for k, v in json.loads(await self.db.kv_get("intel_scale") or "{}").items() if k in DETECTORS}
        except (ValueError, TypeError):
            pass
        self.intel.learned_scale = scales
        self.last_refresh = float(await self.db.kv_get("intel_last_refresh") or 0)
        if not await self.db.kv_get("lessons_migrated"):
            await self._migrate_legacy()
        await self.retrain()

    async def _migrate_legacy(self) -> None:
        """Bring what earlier versions learned into the ledger: the saved spam examples and the decision history. Safe to repeat."""
        try:
            for text in json.loads(await self.db.kv_get("intel_examples") or "[]"):
                await self.ledger.add(str(text), "spam", "migrated")
        except (ValueError, TypeError):
            pass
        try:  # 1.1.9 stored lessons in its own table; keep them
            for r in await self.db.fetchall("SELECT ts, label, body, author, demo FROM intel_examples ORDER BY ts"):
                await self.ledger.add(r["body"], r["label"], "migrated", author=r["author"], demo=bool(r["demo"]), ts=r["ts"])
        except Exception:  # the table is absent on a database that never had it
            logger.debug("no 1.1.9 lessons to migrate")
        await self._backfill()
        await self.db.kv_set("lessons_migrated", "1")

    async def persist(self) -> None:
        """Lessons are written to the database as they happen, so there is nothing left to save. Kept so shutdown code stays simple."""
        return None

    async def retrain(self) -> None:
        """Rebuild the learned model from the lessons that are still active. Called after a forget, relabel, restore or import."""
        nb = NaiveBayes()
        spam_texts: list[str] = []
        for r in reversed(await self.ledger.active()):
            if r["demo"] and not self.cfg.get("intel_learn_from_demo"):
                continue
            nb.train(r["body"], r["label"], times=2)
            if r["label"] == "spam":
                spam_texts.append(r["body"])
        self.intel.set_learned(nb, spam_texts[-MAX_EXAMPLES:])

    async def _save_scales(self) -> None:
        await self.db.kv_set("intel_scale", json.dumps({k: round(v, 3) for k, v in self.intel.learned_scale.items() if abs(v - 1) > 1e-6}))

    # ------------------------------------------------------------------ lessons
    def _predict(self, text: str) -> float | None:
        """What the model thinks BEFORE it sees this lesson (None until it has learned enough to have an opinion)."""
        return self.intel.nb.predict(text)[0] if self.intel.nb.trained else None

    async def teach(self, text: str, label: str, source: str = "teach", *, author: str = "", action_id: int | None = None, demo: bool = False) -> dict[str, Any]:
        """Learn one message right now. Returns {"status": added|duplicate|relabelled|skipped, "id": ...}."""
        if label not in ("spam", "ham"):
            raise ValidationFailed("The label must be spam or ham.")
        if not (text or "").strip():
            raise ValidationFailed("There is no message text to learn from.")
        pred = self._predict(text)
        res = await self.ledger.add(text, label, source, author=author, action_id=action_id, pred=pred, demo=demo)
        if res["status"] in ("added", "relabelled") and (not demo or self.cfg.get("intel_learn_from_demo")):
            if res["status"] == "relabelled":
                await self.retrain()          # a changed mind removes the old lesson's effect
            else:
                self.intel.learned_nb.train(text, label, times=2)
                if label == "spam":
                    self.intel.learned_examples.append(text[:300])
                    del self.intel.learned_examples[:-MAX_EXAMPLES]
                self.intel.set_learned()
        return res

    async def feedback(self, action: dict[str, Any], label: str) -> None:
        """Called by the hub when an action is approved (label 'spam') or rejected (label 'ham')."""
        text = (action.get("body") or action.get("text") or "").strip()
        demo = bool(action.get("demo"))
        if not text or label not in ("spam", "ham") or (demo and not self.cfg.get("intel_learn_from_demo")):
            return
        await self.teach(text, label, "decision", author=action.get("author_name", ""), action_id=action.get("id"), demo=demo)

    async def trusted(self, msg: Any, action: str) -> None:
        """Ordinary messages from regulars, members and mods are quiet evidence that normal chat looks like this. At most a few per minute."""
        if not self.cfg.get("intel_learn_trusted_ham") or action != "allow" or msg.level not in ("regular", "member", "mod", "owner"):
            return
        if msg.platform == "demo" and not self.cfg.get("intel_learn_from_demo"):
            return
        if len((msg.text or "").split()) < max(3, int(self.cfg.get("intel_intent_min_tokens"))):
            return
        now = time.time()
        self._trusted_times = [t for t in self._trusted_times if now - t < 60]
        if len(self._trusted_times) >= 3:
            return
        self._trusted_times.append(now)
        await self.teach(msg.text, "ham", "trusted", author=msg.author_name, demo=msg.platform == "demo")

    async def forget(self, lesson_id: int) -> bool:
        ok = await self.ledger.forget(lesson_id)
        if ok:
            await self.retrain()
        return ok

    async def relabel(self, lesson_id: int) -> dict[str, Any] | None:
        row = await self.ledger.relabel(lesson_id)
        if row:
            await self.retrain()
        return row

    async def reset(self) -> int:
        await self.ledger.snapshot("Before reset")
        n = await self.db.execute("UPDATE learning_lessons SET active = 0, note = 'cleared by you' WHERE active = 1")
        await self.retrain()
        return n

    async def restore(self, snapshot_id: int) -> int:
        await self.ledger.snapshot("Before restore")
        n = await self.ledger.restore(snapshot_id)
        if n is None:
            raise KeyError(snapshot_id)
        await self.retrain()
        return n

    async def import_lessons(self, data: Any) -> dict[str, Any]:
        await self.ledger.snapshot("Before import")
        try:
            res = await self.ledger.import_lessons(data)
        except ValueError as exc:
            raise ValidationFailed(str(exc)) from exc
        await self.retrain()
        return res

    # ------------------------------------------------------------------ quality and review queue
    async def quality(self, now: float | None = None) -> dict[str, Any]:
        """How well the learned model is doing, measured only on messages it had not yet learned (see lessons.Ledger.accuracy)."""
        now = now if now is not None else time.time()
        counts = await self.ledger.counts()
        recent = await self.ledger.accuracy(now - 14 * 86400)
        before = await self.ledger.accuracy(now - 44 * 86400, now - 14 * 86400)
        overall = await self.ledger.accuracy(0)
        drifting = bool(recent["n"] >= 10 and before["n"] >= 10 and recent["accuracy"] is not None and before["accuracy"] is not None
                        and recent["accuracy"] < before["accuracy"] - 0.10)
        needed = int(self.cfg.get("intel_learn_min_lessons"))
        total = counts["spam"] + counts["ham"]
        return {"counts": counts, "overall": overall, "recent": recent, "before": before, "drifting": drifting,
                "model_ready": self.intel.nb.trained, "active": total >= needed, "needed": needed,
                "balance": round(counts["spam"] / total, 2) if total else None,
                "timeline": await self.ledger.timeline(30, now)}

    async def queue(self, limit: int = 12) -> dict[str, Any]:
        """Recent real chat messages the model is least sure about. Labelling these teaches it the most per click."""
        if not self.intel.nb.trained:
            return {"ready": False, "items": []}
        rows = await self.db.fetchall(
            "SELECT id, author_name, body, ts, score, verdict FROM chat_messages WHERE demo = 0 AND ts >= ? ORDER BY ts DESC LIMIT 800",
            (time.time() - 7 * 86400,))
        known = {r["flat"] for r in await self.ledger.active()}
        seen: set[str] = set()
        scored: list[tuple[float, dict[str, Any]]] = []
        for r in rows:
            text = (r["body"] or "").strip()
            key = flat(text)
            if len(tokens(text)) < 3 or not key or key in known or key in seen:
                continue
            seen.add(key)
            p, words = self.intel.nb.predict(text)
            if 0.25 <= p <= 0.75:
                scored.append((abs(p - 0.5), {"id": r["id"], "author": r["author_name"], "text": text[:300], "ts": r["ts"], "p_spam": round(p, 2),
                                              "words": words, "score": r["score"], "verdict": r["verdict"]}))
        scored.sort(key=lambda t: t[0])
        return {"ready": True, "items": [it for _, it in scored[:max(1, min(limit, 40))]]}

    async def _resolved(self, limit: int = 600) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT author_id, body, reasons, status FROM mod_actions WHERE demo = 0 AND status IN "
            "('executed', 'simulated', 'rejected') ORDER BY ts DESC LIMIT ?", (limit,))
        for r in rows:
            try:
                r["reasons"] = json.loads(r["reasons"] or "[]")
            except ValueError:
                r["reasons"] = []
        return rows

    async def _backfill(self) -> None:
        for r in reversed(await self._resolved(500)):
            if (r["body"] or "").strip():
                await self.ledger.add(r["body"], "ham" if r["status"] == "rejected" else "spam", "decision")
        await self.db.kv_set("intel_backfilled", "1")

    async def stats(self) -> dict[str, Any]:
        rows = await self._resolved(2000)
        ok: Counter[str] = Counter()
        bad: Counter[str] = Counter()
        approved = rejected = 0
        for r in rows:
            good = r["status"] != "rejected"
            approved += good
            rejected += not good
            for name in set(_signal_names(r["reasons"])):
                (ok if good else bad)[name] += 1
        names = sorted(set(ok) | set(bad), key=lambda n: -(ok[n] + bad[n]))
        signals = []
        for n in names:
            total = ok[n] + bad[n]
            signals.append({"name": n, "approved": ok[n], "rejected": bad[n], "precision": round(ok[n] / total, 2) if total else None,
                            "detector": n in DETECTORS})
        log_auto = await self.db.fetchone("SELECT COUNT(*) AS n FROM knowledge_log WHERE summary LIKE 'Auto:%' AND undone = 0")
        counts = await self.ledger.counts()
        return {
            "decisions": approved + rejected, "approved": approved, "rejected": rejected,
            "precision": round(approved / (approved + rejected), 2) if approved + rejected else None,
            "signals": signals, "learned_spam": counts["spam"], "learned_ham": counts["ham"],
            "examples": len(self.intel.learned_examples), "lessons": counts, "auto_changes": log_auto["n"] if log_auto else 0,
            "mode": self.cfg.get("intel_learning_mode"), "last_refresh": self.last_refresh or None,
            "scales": {k: round(v, 2) for k, v in self.intel.learned_scale.items() if abs(v - 1) > 1e-6},
        }

    # ------------------------------------------------------------------ suggestions
    async def suggestions(self, status: str = "new") -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM knowledge_suggestions WHERE status = ? ORDER BY evidence DESC, id DESC LIMIT 100", (status,))

    async def _exists(self, kind: str, pack_id: str, body: str) -> bool:
        return bool(await self.db.fetchone(
            "SELECT 1 AS x FROM knowledge_suggestions WHERE kind = ? AND pack_id = ? AND lower(body) = ?", (kind, pack_id, body.casefold())))

    async def _add_suggestion(self, kind: str, pack_id: str, body: str, detail: str, weight: int, evidence: int) -> bool:
        if await self._exists(kind, pack_id, body):
            return False
        await self.db.execute(
            "INSERT INTO knowledge_suggestions (kind, pack_id, body, detail, weight, evidence, status, created) VALUES (?, ?, ?, ?, ?, ?, 'new', ?)",
            (kind, pack_id, body, detail, weight, evidence, time.time()))
        return True

    def _covered(self, gram: str) -> bool:
        if self.intel.index.scan(gram):
            return True
        g = deep_normalize(gram)
        return any(g in (b := deep_normalize(e.get("phrase") or "")) or (b and b in g) for e in self.intel.blacklist)

    async def refresh(self) -> dict[str, Any]:
        """Work out new suggestions from the owner's past decisions. Safe to run any time; nothing changes unless accepted."""
        rows = await self._resolved(600)
        approved = [r for r in rows if r["status"] != "rejected" and (r["body"] or "").strip()]
        rejected = [r for r in rows if r["status"] == "rejected" and (r["body"] or "").strip()]
        made = 0
        made += await self._phrase_suggestions(approved, rejected)
        made += await self._safe_suggestions(approved, rejected)
        made += await self._scale_suggestions(rows)
        made += await self._promote_suggestions(approved, rejected)
        self.last_refresh = time.time()
        await self.db.kv_set("intel_last_refresh", str(self.last_refresh))
        auto = 0
        if self.cfg.get("intel_learning_mode") == "auto":
            for s in await self.suggestions("new"):
                if self._confident(s):
                    try:
                        await self.accept(s["id"], auto=True)
                        auto += 1
                    except (ValidationFailed, KeyError):
                        logger.info("Could not auto-apply suggestion %s", s["id"])
        return {"new": made, "auto_applied": auto}

    @staticmethod
    def _confident(s: dict[str, Any]) -> bool:
        return {"phrase": s["evidence"] >= 4, "scale": s["evidence"] >= 20, "promote": s["evidence"] >= 8}.get(s["kind"], False)

    async def _phrase_suggestions(self, approved: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> int:
        counts: Counter[str] = Counter()
        authors: dict[str, set[str]] = defaultdict(set)
        for r in approved:
            words = tokens(r["body"], markers=False)
            if len(words) < 2:
                continue
            seen: set[str] = set()
            for n in (2, 3, 4):
                for g in ngrams(words, n):
                    if g not in seen:
                        seen.add(g)
                        counts[g] += 1
                        authors[g].add(str(r["author_id"]))
        ham: set[str] = {g for r in rejected for n in (2, 3, 4) for g in ngrams(tokens(r["body"], markers=False), n)}
        ham_words: set[str] = {w for r in rejected for w in tokens(r["body"], markers=False)}
        for pack in self.intel.packs.values():
            if pack.kind == "corpus" and pack.payload["label"] == "ham":
                for ex in pack.payload["examples"]:
                    w = tokens(ex, markers=False)
                    ham_words.update(w)
                    ham.update(g for n in (2, 3, 4) for g in ngrams(w, n))

        def novel(g: str) -> bool:  # at least one word that normal chat does not use
            return any(w not in ham_words and w not in _STOP and len(w) >= 4 for w in g.split())

        cands = [g for g, n in counts.items() if n >= 3 and len(authors[g]) >= 2 and len(flat(g)) >= 8
                 and not all(w in _STOP for w in g.split()) and g not in ham and novel(g) and not self._covered(g)]
        # shortest first: a short phrase matches every longer variant of the message too
        cands.sort(key=lambda g: (-len(authors[g]), -counts[g], len(g), g))
        chosen: list[str] = []
        for g in cands:
            if any(f" {c} " in f" {g} " for c in chosen):
                continue
            chosen.append(g)
            if len(chosen) >= 5:
                break
        made = 0
        for g in chosen:
            if await self._add_suggestion("phrase", "spam.learned", g, f"Seen in {counts[g]} approved messages from {len(authors[g])} different accounts, and in none you rejected.",
                                          50, len(authors[g])):
                made += 1
        return made

    async def _safe_suggestions(self, approved: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> int:
        bad: Counter[str] = Counter()
        for r in rejected:
            words = tokens(r["body"], markers=False)
            for g in {g for n in (1, 2, 3) for g in ngrams(words, n)}:
                bad[g] += 1
        good = {g for r in approved for n in (1, 2, 3) for g in ngrams(tokens(r["body"], markers=False), n)}
        cands = [g for g, n in bad.items() if n >= 2 and g not in good and len(flat(g)) >= 5 and not all(w in _STOP for w in g.split())
                 and self.intel.index.scan(g)]  # only phrases a rule actually reacts to are worth protecting
        cands.sort(key=lambda g: (-bad[g], len(g), g))
        chosen: list[str] = []
        for g in cands:  # the shortest phrase a rule reacts to protects every longer variant too
            if not any(f" {c} " in f" {g} " for c in chosen):
                chosen.append(g)
        made = 0
        for g in chosen[:3]:
            if await self._add_suggestion("safe", "safe.learned", g, f"You rejected {bad[g]} actions whose messages contained this, and never approved one.", 0, bad[g]):
                made += 1
        return made

    async def _scale_suggestions(self, rows: list[dict[str, Any]]) -> int:
        ok: Counter[str] = Counter()
        bad: Counter[str] = Counter()
        for r in rows:
            for name in set(_signal_names(r["reasons"])):
                (ok if r["status"] != "rejected" else bad)[name] += 1
        made = 0
        for det in DETECTORS:
            n = ok[det] + bad[det]
            if n < 10:
                continue
            precision = ok[det] / n
            cur = self.intel.learned_scale.get(det, 1.0)
            if precision < 0.5 and cur > 0.55:
                new = max(0.5, round(cur * 0.8, 2))
                if await self._add_suggestion("scale", "", det, f"Only {precision:.0%} of the {n} actions this detector took part in were approved. Lower its strength to {new:g}x.",
                                              int(new * 100), n):
                    made += 1
            elif precision >= 0.95 and n >= 20 and cur < 1.0:
                if await self._add_suggestion("scale", "", det, f"{precision:.0%} of {n} actions were approved. Restore its full strength.", 100, n):
                    made += 1
        return made

    async def _promote_suggestions(self, approved: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> int:
        shadow = [d for d in DETECTORS if str(self.cfg.get(f"intel_{d}_mode")) == "shadow"]
        if not shadow or not (approved or rejected):
            return 0
        agree_ok: Counter[str] = Counter()
        agree_bad: Counter[str] = Counter()
        for i, (group, counter) in enumerate(((approved[:300], agree_ok), (rejected[:300], agree_bad))):
            for j, r in enumerate(group):
                fired = self.intel.probe(r["body"])
                for det in shadow:
                    if det in fired:
                        counter[det] += 1
                if j % 25 == 24:
                    await asyncio.sleep(0)
        made = 0
        for det in shadow:
            if agree_ok[det] >= 3 and agree_bad[det] == 0:
                if await self._add_suggestion("promote", "", det,
                                              f"In shadow mode it would have agreed with {agree_ok[det]} of your {len(approved)} approvals and with none of your {len(rejected)} rejections. Switch it to live.",
                                              0, agree_ok[det]):
                    made += 1
        return made

    # ------------------------------------------------------------------ accept / dismiss / undo
    async def _log(self, kind: str, summary: str, undo: dict[str, Any]) -> int:
        return await self.db.insert("INSERT INTO knowledge_log (ts, kind, summary, undo, undone) VALUES (?, ?, ?, ?, 0)",
                                    (time.time(), kind, summary, json.dumps(undo)))

    async def accept(self, sid: int, auto: bool = False) -> dict[str, Any]:
        s = await self.db.fetchone("SELECT * FROM knowledge_suggestions WHERE id = ?", (sid,))
        if not s:
            raise KeyError(sid)
        if s["status"] != "new":
            raise ValidationFailed("That suggestion was already handled.")
        prefix = "Auto: " if auto else ""
        if s["kind"] in ("phrase", "safe"):
            res = await self.knowledge.add_entries(s["pack_id"], [s["body"]], s["weight"], source="learned")
            if not res["added"]:
                raise ValidationFailed("That phrase is already in the pack.")
            title = self.intel.packs[s["pack_id"]].title
            log_id = await self._log(s["kind"], f"{prefix}Added \u201c{s['body']}\u201d to {title}", {"op": "entry", "pack": s["pack_id"], "phrase": s["body"]})
        elif s["kind"] == "scale":
            old = self.intel.learned_scale.get(s["body"], 1.0)
            new = s["weight"] / 100
            self.intel.learned_scale[s["body"]] = new
            await self._save_scales()
            log_id = await self._log("scale", f"{prefix}{DETECTORS[s['body']]['title']} strength {old:g}x \u2192 {new:g}x", {"op": "scale", "det": s["body"], "old": old})
        elif s["kind"] == "promote":
            old = str(self.cfg.get(f"intel_{s['body']}_mode"))
            await self.knowledge.set_detector(s["body"], mode="live")
            log_id = await self._log("promote", f"{prefix}{DETECTORS[s['body']]['title']} switched from {old} to live", {"op": "mode", "det": s["body"], "old": old})
        else:
            raise ValidationFailed("Unknown suggestion type.")
        await self.db.execute("UPDATE knowledge_suggestions SET status = 'accepted' WHERE id = ?", (sid,))
        return {"ok": True, "log_id": log_id}

    async def dismiss(self, sid: int) -> dict[str, Any]:
        n = await self.db.execute("UPDATE knowledge_suggestions SET status = 'dismissed' WHERE id = ? AND status = 'new'", (sid,))
        if not n:
            raise KeyError(sid)
        return {"ok": True}

    async def log(self, limit: int = 40) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT id, ts, kind, summary, undone FROM knowledge_log ORDER BY id DESC LIMIT ?", (limit,))

    async def undo(self, log_id: int) -> dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM knowledge_log WHERE id = ?", (log_id,))
        if not row:
            raise KeyError(log_id)
        if row["undone"]:
            raise ValidationFailed("That change was already undone.")
        u = json.loads(row["undo"] or "{}")
        if u.get("op") == "entry":
            await self.knowledge.remove_entry(u["pack"], u["phrase"])
            await self.db.execute("UPDATE knowledge_suggestions SET status = 'dismissed' WHERE pack_id = ? AND lower(body) = ?", (u["pack"], u["phrase"].casefold()))
        elif u.get("op") == "scale":
            if abs(float(u["old"]) - 1) < 1e-6:
                self.intel.learned_scale.pop(u["det"], None)
            else:
                self.intel.learned_scale[u["det"]] = float(u["old"])
            await self._save_scales()
            await self.db.execute("UPDATE knowledge_suggestions SET status = 'dismissed' WHERE kind = 'scale' AND body = ?", (u["det"],))
        elif u.get("op") == "mode":
            await self.knowledge.set_detector(u["det"], mode=u["old"])
            await self.db.execute("UPDATE knowledge_suggestions SET status = 'dismissed' WHERE kind = 'promote' AND body = ?", (u["det"],))
        else:
            raise ValidationFailed("This change cannot be undone automatically.")
        await self.db.execute("UPDATE knowledge_log SET undone = 1 WHERE id = ?", (log_id,))
        return {"ok": True}
