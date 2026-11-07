"""Accuracy check: runs a fixed set of labelled messages through the moderation engine and reports what it caught.

Reports the engine with and without the intelligence layer, so the gain is visible, plus the exact misses and false
alarms. The messages in benchmark.json are separate from the training examples. Stateless: nothing is recorded.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..moderation.engine import ModInput

CASES = Path(__file__).parent / "benchmark.json"


def load_cases() -> dict[str, list[str]]:
    data = json.loads(CASES.read_text(encoding="utf-8"))
    return {"spam": list(data["spam"]), "ham": list(data["ham"])}


def _score(engine: Any, texts: list[str]) -> list[Any]:
    return [engine.evaluate(ModInput("bench", "bench", "viewer", t, "everyone", 1.0), stateless=True) for t in texts]


def run(engine: Any, cfg: Any) -> dict[str, Any]:
    cases = load_cases()
    flag, delete = int(cfg.get("mod_score_flag")), int(cfg.get("mod_score_delete"))
    intel = engine.intel
    results: dict[str, dict[str, list[Any]]] = {}
    try:  # synchronous on purpose: nothing else can touch engine.intel while it is switched off
        engine.intel = None
        results["without"] = {k: _score(engine, v) for k, v in cases.items()}
        engine.intel = intel
        results["with"] = {k: _score(engine, v) for k, v in cases.items()} if intel is not None else results["without"]
    finally:
        engine.intel = intel

    def metrics(res: dict[str, list[Any]]) -> dict[str, Any]:
        spam, ham = res["spam"], res["ham"]
        tp = sum(v.score >= flag for v in spam)
        fp = sum(v.score >= flag for v in ham)
        return {
            "recall_flag": round(tp / len(spam), 3), "recall_delete": round(sum(v.score >= delete for v in spam) / len(spam), 3),
            "false_alarm_flag": round(fp / len(ham), 3), "false_alarm_delete": round(sum(v.score >= delete for v in ham) / len(ham), 3),
            "precision_flag": round(tp / (tp + fp), 3) if tp + fp else None,
            "caught": tp, "spam_total": len(spam), "false_alarms": fp, "ham_total": len(ham),
        }

    w = results["with"]
    return {
        "thresholds": {"flag": flag, "delete": delete},
        "without_intel": metrics(results["without"]), "with_intel": metrics(w),
        "missed": [{"text": t, "score": v.score} for t, v in zip(cases["spam"], w["spam"]) if v.score < flag][:15],
        "weak": [{"text": t, "score": v.score} for t, v in zip(cases["spam"], w["spam"]) if flag <= v.score < delete][:15],
        "false_alarms": [{"text": t, "score": v.score, "signals": [s.name for s in v.signals]}
                         for t, v in zip(cases["ham"], w["ham"]) if v.score >= flag][:15],
        "note": "Your own blocked phrases are included. The example messages are kept separate from the training examples.",
    }
