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
        self._dirty = 0
        self.last_refresh = 0.0

    # ------------------------------------------------------------------ persistence
    async def load(self) -> None:
        nb = NaiveBayes()
        raw = await self.db.kv_get("intel_bayes")
        if raw:
            try:
                nb = NaiveBayes.load(raw)
            except (ValueError, TypeError):
                logger.warning("Ignoring unreadable learned model")
        examples: list[str] = []
        try:
            examples = [str(x) for x in json.loads(await self.db.kv_get("intel_examples") or "[]")]
        except ValueError:
            pass
        scales: dict[str, float] = {}
        try:
            scales = {k: float(v) for k, v in json.loads(await self.db.kv_get("intel_scale") or "{}").items() if k in DETECTORS}
        except (ValueError, TypeError):
            pass
        self.intel.set_learned(nb, examples, scales)
        self.last_refresh = float(await self.db.kv_get("intel_last_refresh") or 0)
        if not await self.db.kv_get("intel_backfilled"):
            await self._backfill()

    async def persist(self) -> None:
        if not self._dirty:
            return
        self._dirty = 0
        await self.db.kv_set("intel_bayes", self.intel.learned_nb.dump())
        await self.db.kv_set("intel_examples", json.dumps(self.intel.learned_examples))

    async def _save_scales(self) -> None:
        await self.db.kv_set("intel_scale", json.dumps({k: round(v, 3) for k, v in self.intel.learned_scale.items() if abs(v - 1) > 1e-6}))

    # ------------------------------------------------------------------ live feedback
    def _learn(self, text: str, label: str) -> None:
        self.intel.learned_nb.train(text, label, times=2)
        self.intel.nb.train(text, label, times=2)  # the live model learns immediately
        if label == "spam":
            key = flat(text)
            if key and all(flat(e) != key for e in self.intel.learned_examples):
                self.intel.learned_examples.append(text[:300])
                del self.intel.learned_examples[:-MAX_EXAMPLES]
        self._dirty += 1

    async def feedback(self, action: dict[str, Any], label: str) -> None:
        """Called by the hub when an action is approved (label 'spam') or rejected (label 'ham')."""
        text = (action.get("body") or action.get("text") or "").strip()
        if not text or action.get("demo") or label not in ("spam", "ham"):
            return
        self._learn(text, label)
        if self._dirty >= 10:
            await self.persist()
            self.intel.set_learned()

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
        for r in await self._resolved(500):
            if (r["body"] or "").strip():
                self._learn(r["body"], "ham" if r["status"] == "rejected" else "spam")
        await self.persist()
        self.intel.set_learned()
        await self.db.kv_set("intel_backfilled", "1")

    # ------------------------------------------------------------------ statistics
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
        nb = self.intel.learned_nb
        return {
            "decisions": approved + rejected, "approved": approved, "rejected": rejected,
            "precision": round(approved / (approved + rejected), 2) if approved + rejected else None,
            "signals": signals, "learned_spam": nb.docs["spam"] // 2, "learned_ham": nb.docs["ham"] // 2,
            "examples": len(self.intel.learned_examples), "auto_changes": log_auto["n"] if log_auto else 0,
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
