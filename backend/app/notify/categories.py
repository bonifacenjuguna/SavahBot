"""Every kind of notification SavahBot can send. Only real events appear here: each one is raised by code that exists.

Other subsystems add their own with `register()` (the weather subsystem does). A category fixes the defaults; the owner's
choices live in the preferences and override them.
"""
from __future__ import annotations

from dataclasses import dataclass

PRIORITIES = ("low", "normal", "high", "critical")
CHANNELS = ("push", "inapp", "telegram")


@dataclass(frozen=True)
class Category:
    id: str
    group: str
    label: str
    description: str
    icon: str = "bell"
    kind: str = "info"                    # info | ok | warn | bad: the colour of the card in the inbox
    priority: str = "normal"
    push: bool = True                     # default for the push channel
    inapp: bool = True
    telegram: bool = False
    telegram_native: bool = False         # Telegram already receives this through its own settings; the centre does not repeat it
    route: str = "#/notifications"        # where a tap leads
    dedupe_seconds: int = 0               # the same dedupe key inside this window folds into one entry
    sensitive: bool = False               # hide the body on a locked screen
    can_override_quiet: bool = False      # may break through quiet hours when its priority is critical


GROUPS = {
    "moderation": "Moderation",
    "stream": "Stream",
    "reminders": "Reminders & timers",
    "system": "System health",
    "security": "Security",
    "backup": "Backup",
    "weather": "Weather",
    "test": "Test",
}

REGISTRY: dict[str, Category] = {}


def register(*cats: Category) -> None:
    for c in cats:
        if c.priority not in PRIORITIES:
            raise ValueError(f"{c.id}: unknown priority {c.priority}")
        REGISTRY[c.id] = c


register(
    Category("moderation.approval", "moderation", "Approval needed", "Moderation wants your decision on a chatter.", "inbox", "warn", "normal",
             telegram_native=True, route="#/moderation", dedupe_seconds=300),
    Category("moderation.failed", "moderation", "Moderation action failed", "YouTube did not carry out an action you or the bot asked for.", "alert", "bad", "high",
             telegram=True, route="#/moderation"),
    Category("moderation.expired", "moderation", "Approvals expired", "Requests timed out without a decision.", "clock", "warn", "low", push=False,
             route="#/moderation", dedupe_seconds=900),
    Category("moderation.raid", "moderation", "Raid wave detected", "Many brand-new accounts started chatting within seconds.", "shield", "bad", "high",
             telegram_native=True, route="#/moderation", dedupe_seconds=600),
    Category("stream.live", "stream", "Stream went live", "The bot attached to your live chat.", "radio", "ok", "normal", telegram_native=True, route="#/desk"),
    Category("stream.ended", "stream", "Stream ended", "The bot is waiting for the next stream.", "power", "info", "low", push=False, telegram_native=True, route="#/desk"),
    Category("stream.mode", "stream", "Mode changed", "Switched between Demo and Live.", "flask", "info", "low", push=False, route="#/desk", dedupe_seconds=60),
    Category("reminders.reminder", "reminders", "Reminder", "A reminder you set is due.", "bell", "ok", "high", telegram_native=True, route="#/notebook"),
    Category("reminders.timer", "reminders", "Timer finished", "A timed message posted its last run and switched itself off.", "timer", "info", "low", push=False, route="#/commands?tab=timers"),
    Category("system.youtube", "system", "YouTube problem", "YouTube reported an error or the connection was lost.", "youtube", "bad", "high", telegram=True,
             route="#/setup", dedupe_seconds=1800),
    Category("system.quota", "system", "YouTube quota warning", "The daily YouTube quota passed 75% or 90%.", "gauge", "warn", "normal", telegram_native=True, route="#/setup", dedupe_seconds=3600),
    Category("system.telegram", "system", "Telegram problem", "Telegram reported an error.", "telegram", "bad", "normal", push=True, route="#/setup", dedupe_seconds=1800),
    Category("system.firebase", "system", "Push delivery problem", "Push messages keep failing to send.", "alert", "bad", "normal", push=False, telegram=True, route="#/notifications", dedupe_seconds=3600),
    Category("security.alert", "security", "Security alert", "Sign-ins, lockdown and other changes to how you get in.", "lock", "bad", "critical", telegram_native=True,
             route="#/security", sensitive=True, can_override_quiet=True, dedupe_seconds=60),
    Category("backup.done", "backup", "Backup events", "A backup was exported, imported or restored.", "database", "ok", "normal", push=False, route="#/backup"),
    Category("test.test", "test", "Test notification", "Sent by the Send test button.", "bell", "info", "normal", route="#/notifications"),
)


def get(cid: str) -> Category | None:
    return REGISTRY.get(cid)


def listing() -> list[dict]:
    return [{"id": c.id, "group": c.group, "group_label": GROUPS.get(c.group, c.group.title()), "label": c.label, "description": c.description, "icon": c.icon,
             "kind": c.kind, "priority": c.priority, "push": c.push, "inapp": c.inapp, "telegram": c.telegram, "telegram_native": c.telegram_native,
             "route": c.route, "sensitive": c.sensitive} for c in REGISTRY.values()]
