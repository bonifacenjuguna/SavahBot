"""Auto-reply matching: the pure, tested core of the future automated reply feature.

STATUS: foundation only. Rules can be stored and tested from the dashboard, but nothing in the chat pipeline calls
`find_reply` yet, so the bot does not answer anyone automatically. When the engine is wired into the hub, this module
is what it will use, so the matching behaviour is already settled and covered by tests.

Match types:
  phrase    the whole message equals the trigger (ignoring surrounding spaces and ending punctuation)
  word      the trigger appears as a whole word or phrase inside the message ("rules" matches "what are the rules?")
  contains  the trigger appears anywhere, even inside another word
"""
from __future__ import annotations

import re
from typing import Any

_END_PUNCT = " \t\r\n.!?,;:"


def _norm(text: str, case_sensitive: bool) -> str:
    text = " ".join((text or "").split())
    return text if case_sensitive else text.lower()


def trigger_matches(trigger: str, message: str, match_type: str = "phrase", case_sensitive: bool = False) -> bool:
    t, m = _norm(trigger, case_sensitive), _norm(message, case_sensitive)
    t = t.strip(_END_PUNCT)
    if not t or not m:
        return False
    if match_type == "phrase":
        return m.strip(_END_PUNCT) == t
    if match_type == "word":
        return re.search(rf"(?<!\w){re.escape(t)}(?!\w)", m) is not None
    if match_type == "contains":
        return t in m
    return False


def find_reply(rules: list[dict[str, Any]], message: str) -> dict[str, Any] | None:
    """First enabled rule (lowest priority number wins) with a matching trigger. Returns {rule, trigger, reply} or None."""
    for rule in sorted((r for r in rules if r.get("enabled")), key=lambda r: (r.get("priority", 100), r.get("id", 0))):
        for trig in rule["triggers"]:
            if trigger_matches(trig, message, rule.get("match_type", "phrase"), bool(rule.get("case_sensitive"))):
                responses = rule.get("responses") or []
                return {"rule": rule, "trigger": trig, "reply": responses[0] if responses else ""}
    return None


def test_message(rules: list[dict[str, Any]], message: str) -> list[dict[str, Any]]:
    """Every rule that would match, enabled or not, in the order the bot would consider them. For the dashboard's tester."""
    out = []
    for rule in sorted(rules, key=lambda r: (r.get("priority", 100), r.get("id", 0))):
        for trig in rule["triggers"]:
            if trigger_matches(trig, message, rule.get("match_type", "phrase"), bool(rule.get("case_sensitive"))):
                out.append({"id": rule["id"], "name": rule["name"], "trigger": trig, "enabled": rule["enabled"], "reply": (rule["responses"] or [""])[0]})
                break
    return out
