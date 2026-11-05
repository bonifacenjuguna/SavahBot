"""Describes the built-in chat commands for the dashboard. Built-ins are implemented in engine.py; this file only
documents them (syntax, who may use them, category) so the Commands page never shows a command the bot cannot run."""
from __future__ import annotations

from .engine import BUILTIN_NAMES, _MOD_ONLY

# name -> (category, syntax, description). Permission comes from engine._MOD_ONLY, not from this table.
_INFO: dict[str, tuple[str, str, str]] = {
    "commands": ("General", "{p}commands", "Lists the commands the viewer is allowed to use."),
    "uptime": ("General", "{p}uptime", "Says how long the stream has been live."),
    "quote": ("Community", "{p}quote [number]", "Posts a random saved quote, or quote number N."),
    "addquote": ("Community", "{p}addquote <text>", "Saves a new quote, credited to whoever added it."),
    "addcom": ("Management", "{p}addcom <name> <reply>", "Creates a custom command from chat."),
    "editcom": ("Management", "{p}editcom <name> <reply>", "Changes the reply of a custom command."),
    "delcom": ("Management", "{p}delcom <name>", "Removes a custom command."),
    "permit": ("Moderation", "{p}permit <user> [seconds]", "Lets one viewer post links for a short time."),
}


def builtin_catalog(prefix: str) -> list[dict]:
    out = []
    for name in sorted(BUILTIN_NAMES):
        category, syntax, description = _INFO.get(name, ("General", "{p}" + name, ""))
        out.append({"name": name, "category": category, "syntax": syntax.replace("{p}", prefix), "description": description,
                    "userlevel": "mod" if name in _MOD_ONLY else "everyone", "builtin": True})
    return out
