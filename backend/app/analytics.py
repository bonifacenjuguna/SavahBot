"""Dashboard analytics, computed from the stored chat log and moderation history."""
from __future__ import annotations

import time
from collections import Counter
from typing import Any

from .store import Store


def _bucket_seconds(hours: float) -> int:
    if hours <= 3:
        return 60
    if hours <= 12:
        return 300
    if hours <= 48:
        return 900
    return 3600


async def summary(store: Store, hours: float = 24, demo: bool | None = None, now: float | None = None) -> dict[str, Any]:
    now = now if now is not None else time.time()
    hours = max(0.25, min(float(hours), 24 * 14))
    since = now - hours * 3600
    chat = [c for c in await store.chat_since(since) if demo is None or bool(c["demo"]) == demo]
    actions = [a for a in await store.actions_since(since) if demo is None or a["demo"] == demo]

    step = _bucket_seconds(hours)
    start = int(since // step) * step
    n_buckets = int((now - start) // step) + 1
    timeline = [{"t": start + i * step, "messages": 0, "flagged": 0} for i in range(n_buckets)]
    for c in chat:
        i = int((c["ts"] - start) // step)
        if 0 <= i < n_buckets:
            timeline[i]["messages"] += 1
            if c["verdict"] != "allow":
                timeline[i]["flagged"] += 1

    # one entry per person (id + platform), not per display name, so two people with the same name stay apart and a row can open that person's profile
    who: dict[tuple[str, str], str] = {}
    chatters: Counter[tuple[str, str]] = Counter()
    for c in chat:
        if c["level"] == "bot":
            continue
        k = (c.get("platform") or "youtube", c.get("author_id") or c["author_name"])
        who[k] = c["author_name"]
        chatters[k] += 1
    by_action = Counter(a["action"] for a in actions)
    outcomes = Counter(a["status"] for a in actions)
    signals: Counter[str] = Counter()
    for a in actions:
        for reason in a["reasons"]:
            signals[reason.split(":", 1)[0]] += 1
    levels = Counter(c["level"] for c in chat)

    return {
        "hours": hours, "bucket_seconds": step, "since": since, "now": now,
        "totals": {
            "messages": len(chat), "chatters": len(chatters),
            "flagged_messages": sum(1 for c in chat if c["verdict"] != "allow"),
            "actions": len(actions), "pending": outcomes.get("pending", 0),
        },
        "timeline": timeline,
        "top_chatters": [{"name": who[k], "messages": c, "author_id": k[1], "platform": k[0]} for k, c in chatters.most_common(10)],
        "actions_by_type": dict(by_action),
        "outcomes": dict(outcomes),
        "signals": [{"name": n, "count": c} for n, c in signals.most_common()],
        "levels": dict(levels),
    }
