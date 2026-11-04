"""Natural reminder-time parsing (standard library only).

Accepted forms for the first part of the text:
  10m | 2h | 1d | 2h30m                 relative duration
  18:30                                 next time it is 18:30 (owner's timezone)
  today 18:30 | tomorrow 09:00          explicit day
  2026-11-05 14:00                      explicit date and time
  daily 08:00 | weekly 08:00            repeating at a time of day
  every 2h | every 30m                  repeating at an interval
The remaining words are the reminder text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_DUR_PART = re.compile(r"(\d+)\s*([dhms])", re.I)
_DUR_FULL = re.compile(r"^(?:\d+\s*[dhms])+$", re.I)
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UNIT = {"d": 86400, "h": 3600, "m": 60, "s": 1}


class ReminderParseError(ValueError):
    pass


@dataclass
class ParsedReminder:
    due_utc: datetime  # naive UTC
    text: str
    repeat: str = "none"  # none | daily | weekly | interval
    interval_seconds: int | None = None


def parse_duration(token: str) -> int | None:
    if not _DUR_FULL.match(token.strip()):
        return None
    return sum(int(n) * _UNIT[u.lower()] for n, u in _DUR_PART.findall(token))


def _to_utc_naive(local: datetime) -> datetime:
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _hhmm(token: str) -> tuple[int, int]:
    m = _HHMM.match(token)
    if not m:
        raise ReminderParseError(f"Expected a time like 18:30, got '{token}'.")
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        raise ReminderParseError(f"'{token}' is not a valid time.")
    return h, mi


def parse_reminder(args: str, tz_name: str = "UTC", now_utc: datetime | None = None) -> ParsedReminder:
    tokens = args.split()
    if len(tokens) < 2:
        raise ReminderParseError("Use: /remind <when> <text>, e.g. /remind 30m stretch")
    tz = ZoneInfo(tz_name)
    now_utc = now_utc or datetime.now(timezone.utc).replace(tzinfo=None)
    now_local = now_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    first = tokens[0].lower()

    def need_text(idx: int) -> str:
        text = " ".join(tokens[idx:]).strip()
        if not text:
            raise ReminderParseError("The reminder needs some text.")
        return text

    # every <duration> <text>
    if first == "every":
        if len(tokens) < 3:
            raise ReminderParseError("Use: /remind every 2h <text>")
        secs = parse_duration(tokens[1])
        if not secs or secs < 60:
            raise ReminderParseError("Repeat interval must be at least 1m, e.g. every 2h.")
        return ParsedReminder(now_utc + timedelta(seconds=secs), need_text(2), "interval", secs)

    # daily|weekly HH:MM <text>
    if first in ("daily", "weekly"):
        if len(tokens) < 3:
            raise ReminderParseError(f"Use: /remind {first} 08:00 <text>")
        h, mi = _hhmm(tokens[1])
        due_local = now_local.replace(hour=h, minute=mi, second=0, microsecond=0)
        if due_local <= now_local:
            due_local += timedelta(days=1)
        return ParsedReminder(_to_utc_naive(due_local), need_text(2), first)

    # relative duration
    secs = parse_duration(tokens[0])
    if secs is not None:
        if secs <= 0:
            raise ReminderParseError("Duration must be above zero.")
        return ParsedReminder(now_utc + timedelta(seconds=secs), need_text(1))

    # today|tomorrow HH:MM
    if first in ("today", "tomorrow"):
        if len(tokens) < 3:
            raise ReminderParseError(f"Use: /remind {first} 09:00 <text>")
        h, mi = _hhmm(tokens[1])
        day = now_local + timedelta(days=1 if first == "tomorrow" else 0)
        due_local = day.replace(hour=h, minute=mi, second=0, microsecond=0)
        if due_local <= now_local:
            raise ReminderParseError("That time has already passed today.")
        return ParsedReminder(_to_utc_naive(due_local), need_text(2))

    # YYYY-MM-DD HH:MM
    if _DATE.match(tokens[0]):
        if len(tokens) < 3:
            raise ReminderParseError("Use: /remind 2026-11-05 14:00 <text>")
        h, mi = _hhmm(tokens[1])
        y, mo, d = (int(x) for x in tokens[0].split("-"))
        try:
            due_local = datetime(y, mo, d, h, mi, tzinfo=tz)
        except ValueError as exc:
            raise ReminderParseError(f"Invalid date: {exc}") from exc
        if due_local <= now_local:
            raise ReminderParseError("That date and time is in the past.")
        return ParsedReminder(_to_utc_naive(due_local), need_text(2))

    # HH:MM
    if _HHMM.match(tokens[0]):
        h, mi = _hhmm(tokens[0])
        due_local = now_local.replace(hour=h, minute=mi, second=0, microsecond=0)
        if due_local <= now_local:
            due_local += timedelta(days=1)
        return ParsedReminder(_to_utc_naive(due_local), need_text(1))

    raise ReminderParseError("I could not read the time. Try 30m, 2h, 18:30, tomorrow 09:00 or daily 08:00.")


def next_repeat(due_utc: datetime, repeat: str, interval_seconds: int | None, now_utc: datetime) -> datetime | None:
    """Next due time after a repeating reminder fired; always moves into the future."""
    if repeat == "daily":
        step = timedelta(days=1)
    elif repeat == "weekly":
        step = timedelta(days=7)
    elif repeat == "interval" and interval_seconds:
        step = timedelta(seconds=interval_seconds)
    else:
        return None
    nxt = due_utc + step
    while nxt <= now_utc:
        nxt += step
    return nxt
