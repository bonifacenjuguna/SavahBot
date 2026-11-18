"""Auto-moderation levels: three ready-made sets of the existing thresholds, so you do not have to tune ten numbers.

A level changes only the numbers below. It never touches your word lists, exemptions or allowed domains, and "custom" is just what you get when
you change any of these yourself afterwards. The mode (off / suggest / auto) stays a separate switch.
"""
from __future__ import annotations

from typing import Any

LEVELS: dict[str, dict[str, Any]] = {
    "basic": {"label": "Basic", "blurb": "Gentle. Deletes only clear problems, never times anyone out or bans by itself.",
              "values": {"mod_auto_actions": "delete", "mod_score_flag": 40, "mod_score_delete": 75, "mod_score_timeout": 110, "mod_score_ban": 130,
                         "mod_strikes_to_timeout": 4, "mod_strikes_to_ban": 8, "mod_allow_ban_escalation": False, "mod_max_punishment": "delete", "mod_auto_punish_daily_cap": 0}},
    "balanced": {"label": "Balanced", "blurb": "Deletes, and times out repeat offenders. Bans always wait for your approval.",
                 "values": {"mod_auto_actions": "delete,timeout", "mod_score_flag": 30, "mod_score_delete": 55, "mod_score_timeout": 90, "mod_score_ban": 100,
                            "mod_strikes_to_timeout": 2, "mod_strikes_to_ban": 4, "mod_allow_ban_escalation": True, "mod_max_punishment": "ban", "mod_auto_punish_daily_cap": 0}},
    "strict": {"label": "Strict", "blurb": "Acts sooner and harder, and may ban by itself. Expect the odd false alarm; every action is in the ledger and can be lifted.",
               "values": {"mod_auto_actions": "delete,timeout,ban", "mod_score_flag": 20, "mod_score_delete": 40, "mod_score_timeout": 70, "mod_score_ban": 90,
                          "mod_strikes_to_timeout": 1, "mod_strikes_to_ban": 3, "mod_allow_ban_escalation": True, "mod_max_punishment": "ban", "mod_auto_punish_daily_cap": 50}},
}


def current(cfg: Any) -> str:
    for key, lv in LEVELS.items():
        if all(cfg.get(k) == v for k, v in lv["values"].items()):
            return key
    return "custom"


def describe(cfg: Any) -> dict[str, Any]:
    return {"current": current(cfg), "mode": cfg.get("mod_mode"),
            "levels": [{"id": k, "label": v["label"], "blurb": v["blurb"], "values": v["values"]} for k, v in LEVELS.items()]}
