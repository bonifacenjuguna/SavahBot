"""Plain data objects shared across the bot."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    platform: str
    author_id: str
    author_name: str
    text: str
    level: str = "everyone"  # everyone | member | regular | mod | owner | bot
    ts: float = field(default_factory=time.time)
    msg_id: str = ""  # id on the platform (needed to delete the message)
    backfill: bool = False  # history found on connect: stored but never moderated or answered
    demo: bool = False
    from_bot: bool = False  # sent by SavahBot itself
    id: int | None = None
    score: int = 0
    verdict: str = "allow"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "platform": self.platform, "msg_id": self.msg_id, "author_id": self.author_id,
            "author_name": self.author_name, "text": self.text, "level": self.level, "ts": self.ts,
            "score": self.score, "verdict": self.verdict, "demo": self.demo, "from_bot": self.from_bot,
        }
