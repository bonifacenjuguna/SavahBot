"""Regenerate docs/API.md from the real route table, so it lists exactly what the server serves.

    python scripts/gen_api_doc.py          # write
    python scripts/gen_api_doc.py --check  # exit 1 if stale
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api import routes  # noqa: E402,F401

TARGET = ROOT.parent / "docs" / "API.md"
AREAS = {
    "auth": "Sign-in (password, passkey, authenticator, recovery) and sessions", "security": "Security & Access Centre: methods, sessions, activity, audit, lockdown",
    "notify": "Notification Centre: preferences, inbox, devices, test, stats", "weather": "Weather: places, forecast, preferences, alert rules", "backup": "Encrypted export, import and restore",
    "settings": "Environment settings and the Settings overview", "system": "Service health and the data inventory", "knowledge": "Knowledge packs, detectors, learning, live lists",
    "bans": "Bans and timeouts", "history": "Long-term history and charts", "youtube": "YouTube connection and quota", "telegram": "Telegram bot control",
}


def render() -> str:
    out = ["# API reference", "",
           "Generated from the server's route table by `python scripts/gen_api_doc.py`. All paths start with `/api`. Send `Authorization: Bearer <session token>` (from `/api/auth/...`). Errors are `{\"error\": \"message\", \"code\"?: \"...\"}` with a matching HTTP status; validation errors are 422.",
           "", "**public** = no sign-in needed. **limited ok** = also allowed for a session in lockdown or one that has not finished two-method sign-in.", "",
           "Secrets are never returned by any route: only whether they are set. Push device tokens, TOTP secrets, recovery codes and session tokens are never listed.", ""]
    groups: dict[str, list] = {}
    for path, methods, public, limited in routes.R.meta:
        parts = path.split("/")
        groups.setdefault(parts[2] if len(parts) > 2 else "", []).append((path, methods, public, limited))
    for g in sorted(groups):
        out += ["", f"## {g or 'root'}", ""]
        if g in AREAS:
            out += [AREAS[g] + ".", ""]
        out += ["| Method | Path | Notes |", "|---|---|---|"]
        for path, methods, public, limited in sorted(groups[g]):
            notes = ", ".join(x for x in ("public" if public else "", "limited ok" if limited else "") if x)
            out.append(f"| {' '.join(sorted(m for m in methods if m != 'HEAD'))} | `{path}` | {notes} |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        sys.exit(0 if TARGET.exists() and TARGET.read_text() == text else 1)
    TARGET.write_text(text)
    print(f"Wrote {TARGET} ({text.count(chr(10))} lines)")
