"""What every detector shares: the context it is handed, the finding it returns, and the settings it reads."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...moderation.normalize import normalize
from ..text import flat as flat_text
from ..text import lite as lite_text


@dataclass
class Ctx:
    """One message as the detectors see it. The forms of the text are made once and shared."""
    text: str
    author_key: str = ""
    author_name: str = ""
    level: str = "everyone"
    now: float = 0.0
    stateless: bool = False          # True for 'test a message': nothing may be remembered
    is_new: bool = False
    base_score: int = 0              # score from the original signals (plus detectors already applied)
    exact: set[str] = field(default_factory=set)   # flat forms of phrases that already matched exactly
    norm: str = field(init=False, default="")
    flat: str = field(init=False, default="")
    lite: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self.text = (self.text or "")[:1500]
        self.norm = normalize(self.text)
        self.flat = flat_text(self.text)
        self.lite = lite_text(self.text)


@dataclass
class Finding:
    """strength runs from -1 (strong reason to trust) to 1 (strong reason to block). Points = strength x the detector's max points."""
    strength: float
    detail: str = ""
    matched: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


class Detector:
    id = ""
    title = ""
    signal = ""
    description = ""
    needs_history = False            # True when it cannot judge without remembered chat (skipped in 'test a message')

    def __init__(self, svc: Any) -> None:
        self.svc = svc               # the Intelligence service: registry, settings, shared state

    @property
    def registry(self) -> Any:
        return self.svc.registry

    def sensitivity(self) -> float:
        return float(self.svc.cfg.get(f"intel_{self.id}_sensitivity"))

    def analyze(self, ctx: Ctx) -> Finding | None:   # pragma: no cover - interface
        raise NotImplementedError

    def observe(self, ctx: Ctx) -> None:
        """Called for every real message after judging, so stateful detectors can remember it."""
