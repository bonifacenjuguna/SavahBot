"""How SavahBot looks in Telegram: HTML cards, meters, menus and date-range words.

Everything here is pure (no network, no database) so it is easy to test. Telegram HTML only understands a few
tags (<b>, <i>, <code>, <pre>, <blockquote>), and every piece of text that came from a viewer MUST go through
`esc()` first: a chat message containing "<" would otherwise make Telegram reject the whole message.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time as dtime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from ..utils import format_duration, truncate

Buttons = list[list[tuple[str, str]]]


class Rich(str):
    """Text that is already Telegram HTML (every viewer-written part passed through esc()). Plain str is sent as plain text."""

RULE = "┄" * 14


def esc(value: object) -> str:
    return escape(str(value), quote=False)


def bar(fraction: float, width: int = 10) -> str:
    """▰▰▰▱▱▱▱▱▱▱ for 0.3. Always `width` characters wide."""
    f = max(0.0, min(1.0, float(fraction)))
    filled = round(f * width)
    return "▰" * filled + "▱" * (width - filled)


def card(title: str, rows: list[str], foot: str = "", icon: str = "") -> str:
    """A titled block: bold heading, a thin rule, one line per row, and an optional muted footer."""
    out = [f"{icon + ' ' if icon else ''}<b>{esc(title)}</b>", RULE, *rows]
    if foot:
        out += ["", f"<i>{foot}</i>"]
    return "\n".join(out)


def kv(icon: str, label: str, value: str) -> str:
    return f"{icon} <b>{esc(label)}</b>  {value}"


def quote(text: str, limit: int = 160) -> str:
    return f"<blockquote>{esc(truncate(text, limit))}</blockquote>"


def mode_dot(value: str) -> str:
    return {"live": "🔴", "demo": "🧪", "auto": "⚡", "suggest": "🔔", "off": "⚪", "webhook": "🔗", "polling": "🔄"}.get(value, "▫️")


# ------------------------------------------------------------------ keyboards
def home_keyboard(pending: int = 0) -> Buttons:
    wait = f"⏳ Waiting ({pending})" if pending else "⏳ Waiting"
    return [
        [("📊 Status", "m:status"), (wait, "m:pending")],
        [("📈 Stats", "m:stats"), ("🎛 Modes", "m:modes")],
        [("🗒 Notes", "m:notes"), ("⏰ Reminders", "m:rem")],
        [("🕘 Recent actions", "m:history"), ("❔ Help", "m:help")],
    ]


def back_row(extra: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    return [*(extra or []), ("‹ Menu", "m:home")]


def modes_keyboard(bot_mode: str, mod_mode: str) -> Buttons:
    tick = lambda cur, v, label: (("✔ " if cur == v else "") + label, f"set:{'bot' if v in ('demo', 'live') else 'mod'}:{v}")
    return [
        [tick(bot_mode, "demo", "🧪 Demo"), tick(bot_mode, "live", "🔴 Live")],
        [tick(mod_mode, "off", "⚪ Off"), tick(mod_mode, "suggest", "🔔 Suggest"), tick(mod_mode, "auto", "⚡ Auto")],
        [("‹ Menu", "m:home")],
    ]


def approval_keyboard(id_: int) -> Buttons:
    return [[("✅ Approve", f"approve:{id_}"), ("❌ Reject", f"reject:{id_}")]]


# ------------------------------------------------------------------ date words
RANGE_HELP = "today, yesterday, week, month, 3d, 12h, 2026-11-05 or 2026-11-01..2026-11-05"
_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_SPAN = re.compile(r"^(\d{1,3})([dh])$")


def _day(s: str) -> date | None:
    m = _DAY.match(s)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def parse_range(words: list[str], tz_name: str, now: datetime | None = None) -> tuple[float | None, float | None, str, list[str]]:
    """Finds ONE date word in `words` and returns (since, until, label, the other words).

    `until` is exclusive and both are epoch seconds in the owner's timezone, so "today" means the owner's today.
    No date word means no limit: (None, None, "", words).
    """
    tz = ZoneInfo(tz_name)
    now = now or datetime.now(tz)
    start_of = lambda d: datetime.combine(d, dtime.min, tz).timestamp()
    today = now.date()
    for i, w in enumerate(words):
        lw = w.lower()
        rest = words[:i] + words[i + 1:]
        if lw == "today":
            return start_of(today), None, "today", rest
        if lw == "yesterday":
            return start_of(today - timedelta(days=1)), start_of(today), "yesterday", rest
        if lw == "week":
            return start_of(today - timedelta(days=6)), None, "the last 7 days", rest
        if lw == "month":
            return start_of(today - timedelta(days=29)), None, "the last 30 days", rest
        m = _SPAN.match(lw)
        if m and int(m[1]) > 0:
            n = int(m[1])
            delta = timedelta(days=n) if m[2] == "d" else timedelta(hours=n)
            return (now - delta).timestamp(), None, f"the last {n}{m[2]}", rest
        if ".." in w:
            a, _, b = w.partition("..")
            da, db = _day(a), _day(b)
            if da and db and da <= db:
                return start_of(da), start_of(db + timedelta(days=1)), f"{da:%d %b} to {db:%d %b %Y}", rest
        d = _day(w)
        if d:
            return start_of(d), start_of(d + timedelta(days=1)), f"{d:%a %d %b %Y}", rest
    return None, None, "", words


# ------------------------------------------------------------------ small formatters
def when(ts: float, tz_name: str, now: datetime | None = None) -> str:
    tz = ZoneInfo(tz_name)
    t = datetime.fromtimestamp(ts, tz)
    today = (now or datetime.now(tz)).date()
    if t.date() == today:
        return f"{t:%H:%M}"
    if t.date() == today - timedelta(days=1):
        return f"yesterday {t:%H:%M}"
    return f"{t:%d %b %H:%M}"


def outcome_icon(status: str) -> str:
    return {"executed": "✅", "approved": "✅", "simulated": "🧪", "rejected": "🚫", "failed": "⚠️", "pending": "⏳", "expired": "⌛"}.get(status, "▫️")


def level_icon(level: str) -> str:
    return {"mod": "🛡", "member": "💎", "regular": "⭐", "bot": "🤖"}.get(level, "")


# ------------------------------------------------------------------ notifications built by the hub
def approval_card(id_: int, r: dict, extra: str = "") -> Rich:
    what = r["action"] + (f" {format_duration(r['duration'])}" if r.get("duration") else "")
    rows = [f"{esc(what)} for <b>{esc(r['author_name'])}</b>  ·  score {esc(r['score'])}", quote(r.get("text") or r.get("body") or "", 140)]
    if r.get("reasons"):
        rows.append("Why: " + ", ".join(f"<code>{esc(x)}</code>" for x in r["reasons"][:4]))
    if extra:
        rows.append(f"<i>{esc(extra)}</i>")
    return Rich(f"⏳ <b>Approval needed</b> #{id_}\n{RULE}\n" + "\n".join(rows))


def stream_card(live: bool, title: str = "") -> Rich:
    if live:
        return Rich("🔴 <b>Stream is live</b>" + (f"\n{esc(title)}" if title else ""))
    return Rich("⚫ <b>Stream has ended</b>")


def flag_card(author: str, score: int, text: str) -> Rich:
    return Rich(f"🚩 <b>Flagged</b> {esc(author)}  ·  score {esc(score)}\n{quote(text, 100)}")


def reminder_card(body: str) -> Rich:
    return Rich(f"⏰ <b>Reminder</b>\n{esc(body)}")
