"""Presentation layer for the Telegram bot: HTML formatting, cards and keyboards.

Everything here is a pure function. Telegram HTML only needs &, < and > escaped, so every piece of user or chat
content passes through `esc()` before it is placed in a message. Nothing in this module decides what the bot does.
"""
from __future__ import annotations

import html
import re
from typing import Any

from ..utils import truncate

Buttons = "list[list[tuple[str, str]]]"

BRAND = "SavahBot"
RULE = "─" * 14


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def strip_tags(text: str) -> str:
    """Plain-text version of a message, used if Telegram refuses the HTML."""
    return html.unescape(re.sub(r"</?(b|i|u|s|code|pre|blockquote|a)(\s[^>]*)?>", "", text))


def title(icon: str, text: str, sub: str = "") -> str:
    return f"{icon} <b>{esc(text)}</b>" + (f"  <i>{esc(sub)}</i>" if sub else "")


def kv(label: str, value: str) -> str:
    """One labelled line. `value` must already be HTML-safe."""
    return f"▫️ {esc(label)}  {value}"


def quote(text: str, limit: int = 160) -> str:
    return f"<blockquote>{esc(truncate(text, limit))}</blockquote>"


def dot(on: bool | None) -> str:
    return "🟢" if on else ("⚪" if on is None else "🔴")


# --------------------------------------------------------------------------------------------- keyboards
def menu_button() -> list[tuple[str, str]]:
    return [("☰ Menu", "nav:home")]


def home_keyboard() -> list[list[tuple[str, str]]]:
    return [
        [("📊 Status", "nav:status"), ("🛡 Waiting", "nav:pending")],
        [("🎛 Modes", "nav:modes"), ("📈 Stats", "nav:stats")],
        [("📝 Notes", "nav:notes"), ("⏰ Reminders", "nav:reminders")],
        [("❔ Help", "nav:help")],
    ]


def back_keyboard(refresh: str | None = None) -> list[list[tuple[str, str]]]:
    row = [("‹ Menu", "nav:home")]
    if refresh:
        row.insert(0, ("↻ Refresh", refresh))
    return [row]


def modes_keyboard(bot_mode: str, mod_mode: str) -> list[list[tuple[str, str]]]:
    def mark(current: str, value: str, label: str) -> str:
        return f"● {label}" if current == value else label

    return [
        [(mark(bot_mode, "demo", "Demo"), "set:mode:demo"), (mark(bot_mode, "live", "Live"), "set:mode:live")],
        [(mark(mod_mode, "off", "Mod off"), "set:mod:off"), (mark(mod_mode, "suggest", "Suggest"), "set:mod:suggest"),
         (mark(mod_mode, "auto", "Auto"), "set:mod:auto")],
        [("‹ Menu", "nav:home")],
    ]


# --------------------------------------------------------------------------------------------- static screens
def welcome(app_name: str, version: str) -> str:
    return "\n".join([
        f"🛡 <b>{esc(app_name)}</b>  <i>v{esc(version)}</i>",
        "Your live-chat companion: moderation, reminders and quick controls.",
        "",
        "Tap a button below, or type a command. <code>/help</code> lists them all.",
    ])


HELP_HTML = "\n".join([
    f"🛡 <b>{BRAND} commands</b>",
    "",
    "📊 <b>Status</b>",
    "/status  overview",
    "/stats [hours]  chat and moderation numbers",
    "/quota  YouTube quota",
    "",
    "🎛 <b>Modes</b>",
    "/mode demo|live  chat source",
    "/mod off|suggest|auto  moderation mode",
    "/tgmode webhook|polling  how Telegram reaches the bot",
    "",
    "🛡 <b>Moderation</b>",
    "/pending  requests waiting for you",
    "/approve &lt;id|all&gt;   /reject &lt;id|all&gt;",
    "/permit &lt;user&gt; [seconds]  allow links briefly",
    "",
    "💬 <b>Chat</b>",
    "/say &lt;text&gt;  post in the stream chat",
    "/demo [scenario]  list or run demo scenarios",
    "",
    "📝 <b>Notes and reminders</b>",
    "/note &lt;text&gt;   /notes   /delnote &lt;id&gt;",
    "/remind &lt;when&gt; &lt;text&gt;   /reminders   /delremind &lt;id&gt;",
    "<i>when: 30m, 2h, 18:30, tomorrow 09:00, 2026-11-05 14:00, daily 08:00, every 2h</i>",
])


# --------------------------------------------------------------------------------------------- notices from the hub
_APPROVAL = re.compile(r"^Approval needed #(\d+): (.+?) for (.+?) \(score (\d+)\)\n“(.*)”\nWhy: (.*?)(\n\(\+.*\))?$", re.S)
_FLAGGED = re.compile(r"^Flagged (.+?) \(score (\d+)\): (.*)$", re.S)


def format_notice(text: str) -> str:
    """Turns the plain notification texts written by the hub and scheduler into a styled card.

    The hub keeps sending plain text (other code and tests depend on it); this only decides how it looks in Telegram.
    Unknown text is escaped and sent as it is.
    """
    m = _APPROVAL.match(text)
    if m:
        id_, what, who, score, body, why, extra = m.groups()
        out = [f"🛡 <b>Approval needed</b>  ·  <code>#{esc(id_)}</code>",
               f"<b>{esc(what)}</b> for <b>{esc(who)}</b>  ·  score {esc(score)}",
               quote(body, 200),
               f"<i>Why:</i> {esc(why) or '—'}"]
        if extra:
            out.append(f"<i>{esc(extra.strip())}</i>")
        return "\n".join(out)
    m = _FLAGGED.match(text)
    if m:
        who, score, body = m.groups()
        return f"🚩 <b>Flagged</b>  {esc(who)}  ·  score {esc(score)}\n{quote(body, 120)}"
    if text.startswith("Reminder: "):
        return f"⏰ <b>Reminder</b>\n{esc(text[len('Reminder: '):])}"
    if text.startswith("Stream is live"):
        name = text.partition(":")[2].strip()
        return "🔴 <b>Stream is live</b>" + (f"\n{esc(name)}" if name else "")
    if text.startswith("Stream has ended"):
        return "⚫ <b>Stream ended</b>"
    if text.startswith("Test message from the dashboard"):
        return f"✅ <b>Telegram is connected</b>\n{esc(text)}"
    return esc(text)


def approval_card(a: dict[str, Any]) -> str:
    what = a["action"] + (f" {a['duration']}s" if a.get("duration") else "")
    return "\n".join([
        f"🛡 <code>#{a['id']}</code>  <b>{esc(what)}</b> for <b>{esc(a['author_name'])}</b>  ·  score {a['score']}",
        quote(a["body"], 120),
        f"<i>Why:</i> {esc('; '.join(a['reasons'][:4])) or '—'}",
    ])


def bar(fraction: float, width: int = 10) -> str:
    """Text progress bar: bar(0.3) -> '▰▰▰▱▱▱▱▱▱▱'."""
    filled = max(0, min(width, round(fraction * width)))
    return "▰" * filled + "▱" * (width - filled)
