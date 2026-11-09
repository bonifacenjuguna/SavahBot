"""The intelligence service: owns the knowledge packs, the detectors, the learned model and the shadow log.

The moderation engine calls `analyze()` for every message. Each detector is Off, Shadow or Active (per detector, from
settings). Active findings become ordinary signals in the verdict. Shadow findings are only recorded, so you can see what a
detector would have done before you let it act. Nothing here can raise into the message path: a failing detector is
logged and skipped.
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from ..config import INTEL_DETECTORS
from ..moderation.engine import ACTION_RANK
from ..utils import split_csv
from .text import flat
from .detectors.base import Ctx, Detector, Finding
from .detectors.evasion import EvasionDetector
from .detectors.fuzzy import FuzzyDetector
from .detectors.learning import LearningDetector, NBModel
from .detectors.links import LinkDetector
from .detectors.names import NameDetector
from .detectors.packs import PackDetector
from .detectors.reputation import ReputationDetector
from .detectors.scam import ScamDetector
from .detectors.shape import ShapeDetector
from .knowledge import PackRegistry
from .store import IntelStore

logger = logging.getLogger("savahbot.intel")

SEED_WEIGHT = 0.6        # a shipped training example counts for less than one of your own decisions
TEACH_WEIGHT = 2.0       # 'Teach the bot' is a deliberate lesson
TRUSTED_LEVELS = {"regular", "member", "mod", "owner"}


@dataclass
class Applied:
    detector: str
    signal: str
    weight: int
    detail: str
    mode: str
    strength: float
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"detector": self.detector, "signal": self.signal, "weight": self.weight, "detail": self.detail, "mode": self.mode, "strength": round(self.strength, 3), "meta": self.meta}


@dataclass
class Outcome:
    active: list[Applied] = field(default_factory=list)
    shadow: list[Applied] = field(default_factory=list)


class Intelligence:
    def __init__(self, cfg: Any, db: Any = None, registry: PackRegistry | None = None) -> None:
        self.cfg = cfg
        self.store: IntelStore | None = IntelStore(db) if db is not None else None
        self.registry = registry or PackRegistry()
        self.model = NBModel(prior=self._prior())
        self.blacklist: list[dict] = []
        self.blacklist_revision = 0
        self._seen_names: "OrderedDict[str, str]" = OrderedDict()
        self._conf_rev = -1
        self._conf: tuple[dict[str, str], dict[str, str]] = ({}, {})
        self._trusted_last: dict[str, float] = {}
        self._trusted_window: list[float] = []
        order = [PackDetector, ScamDetector, LinkDetector, EvasionDetector, NameDetector, ShapeDetector, LearningDetector, FuzzyDetector, ReputationDetector]
        self.detectors: dict[str, Detector] = {d.id: d for d in (cls(self) for cls in order)}
        titles = {i: t for i, t, *_ in INTEL_DETECTORS}
        assert set(self.detectors) == set(titles), "every detector needs a settings entry in config.INTEL_DETECTORS"

    # ------------------------------------------------------------------ lifecycle
    def _prior(self) -> float:
        try:
            return min(0.5, max(0.01, float(self.cfg.get("intel_learn_prior"))))
        except Exception:
            return 0.15

    async def start(self) -> None:
        """Load packs from disk, then your pack choices and learned examples from the database."""
        self.registry.load()
        if self.store is not None:
            off, added, muted = await self.store.pack_state()
            self.registry.apply_state(off, added, muted)
        await self.rebuild_model()
        logger.info("Intelligence ready: %d packs, %d problems, model %s", len(self.registry.packs), len(self.registry.problems), "ready" if self.model.ready else "warming up")

    async def rebuild_model(self) -> None:
        model = NBModel(prior=self._prior())
        for text, label in self.registry.corpus():
            model.add(text, label, SEED_WEIGHT)
        if self.store is not None:
            for r in await self.store.all_examples(int(self.cfg.get("intel_example_cap"))):
                model.add(r["body"], r["label"], float(r["weight"] or 1.0))
        self.model = model

    # ------------------------------------------------------------------ small shared helpers
    def set_blacklist(self, entries: list[dict]) -> None:
        self.blacklist = list(entries)
        self.blacklist_revision += 1

    def protected_names(self) -> list[str]:
        return [n for n in split_csv(self.cfg.get("intel_protected_names")) if n] + list(self._seen_names.values())

    def refold(self, text: str) -> str:
        """Undo extra look-alike letters and symbol pairs from the disguise maps (used by fuzzy matching)."""
        if self._conf_rev != self.registry.revision:
            self._conf, self._conf_rev = self.registry.confusables(), self.registry.revision
        single, multi = self._conf
        t = text.casefold()
        for k, v in multi.items():
            t = t.replace(k, v)
        return t.translate({ord(k): v for k, v in single.items()}) if single else t

    def mode(self, det_id: str) -> str:
        return str(self.cfg.get(f"intel_{det_id}_mode"))

    def cap(self, det_id: str) -> int:
        return int(self.cfg.get(f"intel_{det_id}_weight"))

    # ------------------------------------------------------------------ the message path
    def observe_author(self, m: Any) -> None:
        """Called before any exemption check: owners and mods are the names worth guarding against copycats."""
        if m.level in ("owner", "mod") and m.author_name and len(m.author_name) >= 4:
            self._seen_names[m.author_name.casefold()] = m.author_name
            self._seen_names.move_to_end(m.author_name.casefold())
            while len(self._seen_names) > 40:
                self._seen_names.popitem(last=False)

    async def prepare(self, m: Any) -> None:
        """Before judging a chatter we have not seen since a restart, read their history once."""
        rep: ReputationDetector = self.detectors["reputation"]  # type: ignore[assignment]
        key = f"{m.platform}:{m.author_id}"
        rec = rep.records.get(key)
        if (rec is None or not rec.hydrated) and self.store is not None and not getattr(m, "demo", False):
            try:
                rep.hydrate(key, await self.store.author_history(m.platform, m.author_id), time.time())
            except Exception:
                logger.exception("Could not read chatter history")

    def analyze(self, m: Any, *, base_score: int, matched: list[str] | None = None, is_new: bool = False,
                stateless: bool = False, now: float | None = None) -> Outcome:
        out = Outcome()
        if not self.cfg.get("intel_enabled"):
            return out
        ctx = Ctx(text=m.text, author_key=f"{m.platform}:{m.author_id}", author_name=getattr(m, "author_name", ""), level=m.level,
                  now=now if now is not None else time.time(), stateless=stateless, is_new=is_new, base_score=base_score, exact={flat(p) for p in (matched or ())})
        running = base_score
        for det in self.detectors.values():
            mode = self.mode(det.id)
            if mode == "off" or (stateless and det.needs_history):
                continue
            ctx.base_score = running
            try:
                f = det.analyze(ctx)
            except Exception:
                logger.exception("Detector %s failed on a message; skipped", det.id)
                continue
            if f is None:
                continue
            ctx.exact.update(f.matched)
            w = self._points(det.id, f, running)
            if w == 0:
                continue
            item = Applied(det.id, det.signal, w, f.detail, mode, f.strength, f.meta)
            if mode == "active":
                out.active.append(item)
                running += w
            else:
                out.shadow.append(item)
        self._agree(out.active)
        self._agree(out.shadow)
        if not stateless:
            for det in self.detectors.values():
                if self.mode(det.id) != "off":
                    try:
                        det.observe(ctx)
                    except Exception:
                        logger.exception("Detector %s could not remember a message", det.id)
        return out

    def _agree(self, items: list[Applied]) -> None:
        """Detectors that agree are mostly echoing the same evidence, so the second counts 40% and any further 20%.
        Together they can never add more than the timeout line: intelligence alone does not time out or ban anyone."""
        pos = sorted((a for a in items if a.weight > 0), key=lambda a: -a.weight)
        for rank, a in enumerate(pos):
            if rank:
                a.weight = max(1, round(a.weight * (0.4 if rank == 1 else 0.2)))
        ceiling = max(1, int(self.cfg.get("mod_score_timeout")) - 1)
        over = sum(a.weight for a in pos) - ceiling
        for a in reversed(pos):
            if over <= 0:
                break
            cut = min(over, a.weight - 1) if a is not pos[0] else min(over, a.weight)
            a.weight -= cut
            over -= cut

    def _points(self, det_id: str, f: Finding, running: int) -> int:
        w = round(f.strength * self.cap(det_id))
        if w == 0 and f.strength != 0:
            w = 1 if f.strength > 0 else -1
        if w < 0:
            w = max(w, -int(0.4 * running))     # trust can soften a score, never erase it
        return w

    def record(self, m: Any, action: str, now: float | None = None) -> None:
        """After a verdict: remember the message result for reputation."""
        if self.mode("reputation") == "off" or not self.cfg.get("intel_enabled"):
            return
        rep: ReputationDetector = self.detectors["reputation"]  # type: ignore[assignment]
        rep.note_result(f"{m.platform}:{m.author_id}", now if now is not None else time.time(), action)

    def note_punished(self, platform: str, author_id: str, text: str) -> None:
        rep: ReputationDetector = self.detectors["reputation"]  # type: ignore[assignment]
        rep.note_punished(f"{platform}:{author_id}", text, time.time())

    # ------------------------------------------------------------------ 'test a message'
    def test(self, text: str, name: str = "", level: str = "everyone") -> list[dict[str, Any]]:
        """Run every detector (even Off ones) on a text, remembering nothing. Used by the dashboard's 'try it here'."""
        ctx = Ctx(text=text, author_name=name, level=level, now=time.time(), stateless=True)
        rows = []
        for det in self.detectors.values():
            row = {"id": det.id, "title": det.title, "signal": det.signal, "mode": self.mode(det.id), "ran": True, "strength": 0.0, "weight": 0, "detail": ""}
            if det.needs_history:
                row.update(ran=False, detail="Needs chat history, so it cannot be tested on a single message.")
            else:
                try:
                    f = det.analyze(ctx)
                except Exception as exc:
                    f, row["detail"] = None, f"Failed: {exc}"
                if f is not None:
                    ctx.exact.update(f.matched)
                    row.update(strength=round(f.strength, 3), weight=round(f.strength * self.cap(det.id)), detail=f.detail, meta=f.meta)
            rows.append(row)
        return rows

    # ------------------------------------------------------------------ learning
    async def learn(self, text: str, label: str, *, source: str, author: str = "", weight: float = 1.0, demo: bool = False) -> dict[str, Any]:
        if label not in ("spam", "ham") or self.store is None:
            raise ValueError("label must be 'spam' or 'ham'")
        text = " ".join(text.split())[:1000]
        if len(text) < 2:
            raise ValueError("There is nothing to learn from an empty message.")
        for old in await self.store.find_examples(text):
            if old["label"] == label:
                return {"skipped": True, "id": old["id"], "reason": "already learned"}
            self.model.remove(old["body"], old["label"], float(old["weight"] or 1.0))      # you changed your mind
            await self.store.delete_example(old["id"])
        pred = self.model.score(text)[0] if self.model.ready else None
        eid = await self.store.add_example(label, text, source=source, author=author, pred=pred, weight=weight, demo=demo)
        self.model.add(text, label, weight)
        await self.store.trim_examples(int(self.cfg.get("intel_example_cap")))
        return {"skipped": False, "id": eid, "label": label, "predicted": None if pred is None else round(pred, 3)}

    async def learn_decision(self, text: str, label: str, author: str, demo: bool) -> None:
        """You approved (spam) or rejected (not spam) a moderation request."""
        if not self.cfg.get("intel_enabled") or not self.cfg.get("intel_learn_auto") or (demo and not self.cfg.get("intel_learn_from_demo")):
            return
        try:
            await self.learn(text, label, source="decision", author=author, weight=1.0, demo=demo)
        except Exception:
            logger.exception("Could not learn from a decision")

    async def maybe_learn_trusted(self, m: Any, action: str) -> None:
        """Quietly learn that ordinary messages from trusted chatters are fine (a few a minute at most)."""
        if (action != "allow" or m.level not in TRUSTED_LEVELS or not self.cfg.get("intel_enabled") or not self.cfg.get("intel_learn_trusted_ham")
                or getattr(m, "demo", False) or len(m.text.strip()) < 8 or m.text.lstrip().startswith(("!", "/"))):
            return
        now = time.time()
        self._trusted_window = [t for t in self._trusted_window if now - t < 60]
        key = f"{m.platform}:{m.author_id}"
        if len(self._trusted_window) >= 3 or now - self._trusted_last.get(key, 0) < 90:
            return
        self._trusted_window.append(now)
        self._trusted_last[key] = now
        if len(self._trusted_last) > 2000:
            self._trusted_last = {k: v for k, v in self._trusted_last.items() if now - v < 300}
        try:
            await self.learn(m.text, "ham", source="trusted", author=m.author_name, weight=0.5)
        except Exception:
            logger.exception("Could not learn from a trusted message")

    async def forget(self, example_id: int) -> bool:
        if self.store is None:
            return False
        row = await self.store.get_example(example_id)
        if not row:
            return False
        self.model.remove(row["body"], row["label"], float(row["weight"] or 1.0))
        await self.store.delete_example(example_id)
        return True

    async def reset_learning(self) -> int:
        n = await self.store.clear_examples() if self.store else 0
        await self.rebuild_model()
        return n

    async def accuracy(self, days: int = 90) -> dict[str, Any]:
        """Test-then-train: every example was guessed at before it was learned, so these figures are honest, not memorised."""
        rows = await self.store.prediction_rows(time.time() - days * 86400) if self.store else []
        ok = [((r["pred"] >= 0.5) == (r["label"] == "spam"), r["ts"], r["label"], r["pred"]) for r in rows]
        series = []
        for i in range(0, len(ok), 10):
            block = ok[i:i + 10]
            series.append({"t": block[-1][1], "acc": round(sum(1 for b in block if b[0]) / len(block), 3), "n": len(block)})
        spam = [o for o in ok if o[2] == "spam"]
        ham = [o for o in ok if o[2] == "ham"]
        rate = lambda xs: round(sum(1 for x in xs if x[0]) / len(xs), 3) if xs else None
        return {"n": len(ok), "overall": rate(ok), "recent": rate(ok[-50:]), "catches_spam": rate(spam), "spares_ham": rate(ham), "series": series[-40:]}

    async def learning_stats(self) -> dict[str, Any]:
        counts = await self.store.example_counts() if self.store else {"spam": 0, "ham": 0, "total": 0}
        seed = self.registry.corpus()
        return {"examples": counts, "seed": {"spam": sum(1 for _, l in seed if l == "spam"), "ham": sum(1 for _, l in seed if l == "ham")},
                "ready": self.model.ready, "vocabulary": len(self.model.counts), "prior": self.model.prior,
                "accuracy": await self.accuracy(), "distrust": self.model.distrust(20, "spam"), "trust": self.model.distrust(20, "ham"),
                "mode": self.mode("learning")}

    # ------------------------------------------------------------------ shadow log
    async def log_shadow(self, m: Any, verdict: Any, ladder: Any) -> None:
        """Record what shadow detectors found on one message and what they would have changed."""
        if self.store is None or not getattr(verdict, "shadow", None):
            return
        rows = []
        for s in verdict.shadow:
            reached = ladder(min(100, verdict.score + max(0, s["weight"])))
            would = reached if ACTION_RANK.get(reached, 0) > ACTION_RANK.get(verdict.action, 0) else verdict.action
            rows.append({"ts": m.ts, "platform": m.platform, "author_id": m.author_id, "author_name": m.author_name, "body": m.text,
                         "detector": s["detector"], "signal": s["signal"], "weight": s["weight"], "detail": s["detail"],
                         "would": would, "actual": verdict.action, "demo": getattr(m, "demo", False)})
        try:
            await self.store.add_shadow(rows)
        except Exception:
            logger.exception("Could not write the shadow log")

    # ------------------------------------------------------------------ dashboard views
    def describe_detectors(self) -> list[dict[str, Any]]:
        return [{"id": d.id, "title": d.title, "signal": d.signal, "description": d.description, "needs_history": d.needs_history,
                 "mode": self.mode(d.id), "weight": self.cap(d.id), "sensitivity": float(self.cfg.get(f"intel_{d.id}_sensitivity"))}
                for d in self.detectors.values()]

    async def refresh_state(self) -> None:
        """Re-read your pack choices (on/off, added and muted entries) after a change."""
        if self.store is not None:
            off, added, muted = await self.store.pack_state()
            self.registry.apply_state(off, added, muted)

    async def overview(self, hours: float = 24) -> dict[str, Any]:
        since = time.time() - hours * 3600
        stats = {r["detector"]: r for r in (await self.store.shadow_summary(since) if self.store else [])}
        dets = []
        for d in self.describe_detectors():
            r = stats.get(d["id"], {})
            dets.append(d | {"hits": int(r.get("hits") or 0), "differs": int(r.get("differs") or 0), "authors": int(r.get("authors") or 0)})
        packs = self.registry.summary()
        acc = await self.accuracy()
        counts = await self.store.example_counts() if self.store else {"spam": 0, "ham": 0, "total": 0}
        return {
            "enabled": bool(self.cfg.get("intel_enabled")), "hours": hours, "detectors": dets,
            "modes": {m: sum(1 for d in dets if d["mode"] == m) for m in ("off", "shadow", "active")},
            "packs": {"total": len(packs), "enabled": sum(1 for p in packs if p["enabled"]), "entries": sum(p["entries"] for p in packs if p["enabled"]), "problems": self.registry.problems},
            "learning": {"ready": self.model.ready, "examples": counts, "accuracy_recent": acc["recent"], "accuracy_n": acc["n"]},
            "shadow": {"hits": sum(d["hits"] for d in dets), "differs": sum(d["differs"] for d in dets)},
        }

    async def shadow_report(self, hours: float = 168, detector: str = "", limit: int = 30, offset: int = 0, only_differs: bool = False) -> dict[str, Any]:
        """What shadow detectors found, how often it would have changed the outcome, and how often you agreed (from your decisions)."""
        since = time.time() - hours * 3600
        if self.store is None:
            return {"hours": hours, "detectors": [], "recent": [], "total": 0, "series": []}
        summary = {r["detector"]: r for r in await self.store.shadow_summary(since)}
        out = []
        for d in self.describe_detectors():
            r = summary.get(d["id"], {})
            spam, ham = int(r.get("spam") or 0), int(r.get("ham") or 0)
            out.append(d | {"hits": int(r.get("hits") or 0), "differs": int(r.get("differs") or 0), "authors": int(r.get("authors") or 0),
                            "agreed": spam, "disagreed": ham, "precision": round(spam / (spam + ham), 3) if spam + ham else None})
        rows, total = await self.store.shadow_recent(since, detector, limit, offset, only_differs)
        bucket = 3600 if hours <= 48 else 6 * 3600 if hours <= 24 * 7 else 86400
        return {"hours": hours, "detectors": out, "recent": rows, "total": total, "series": await self.store.shadow_series(since, bucket), "bucket": bucket}
