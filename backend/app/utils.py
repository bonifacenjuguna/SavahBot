"""Small shared helpers (standard library only)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utcnow() -> datetime:
    """Naive UTC datetime. The whole app stores naive UTC; the API adds a 'Z' suffix."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.isoformat() + "Z"


def to_epoch(dt: datetime) -> float:
    """Naive-UTC datetime -> unix seconds. The database stores unix seconds everywhere."""
    return dt.replace(tzinfo=timezone.utc).timestamp()


def from_epoch(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)


def split_csv(value: Any) -> list[str]:
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


def truncate(text: str, limit: int) -> str:
    text = text or ""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def format_duration(seconds: float) -> str:
    """12345 -> '3h 25m 45s'. Zero units are omitted; always shows at least seconds."""
    seconds = int(max(0, seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)
