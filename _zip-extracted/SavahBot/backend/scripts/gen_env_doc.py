"""Regenerate docs/ENVIRONMENT.md from the FIELDS table in app/config.py, so the guide can never drift from the code.

    python scripts/gen_env_doc.py          # write the file
    python scripts/gen_env_doc.py --check  # exit 1 if stale
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import BLANK_BECAUSE, FIELDS, NEEDS_EDIT  # noqa: E402

TARGET = ROOT.parent / "docs" / "ENVIRONMENT.md"
SECRET_WORDS = ("secret", "token", "password", "private_key", "api_key", "dsn", "webhook_url", "service_account", "client_email")
PUBLIC_OK = {"firebase_web_api_key", "firebase_web_app_id", "firebase_messaging_sender_id", "firebase_vapid_key", "firebase_auth_domain", "firebase_project_id"}


def kind(name: str) -> str:
    if name in PUBLIC_OK:
        return "public by design"
    return "SECRET" if any(w in name for w in SECRET_WORDS) else ""


def render() -> str:
    out = ["# Environment variables",
           "",
           "Generated from `backend/app/config.py` by `python scripts/gen_env_doc.py`, so it always matches the code. The same table, with defaults, is in `backend/.env.example` (paste it into Railway as is).",
           "",
           "**Where to set them.** Every variable below goes on the **backend (Railway)**. The dashboard (Vercel) needs at most one: `VITE_API_URL`, the backend's address (optional; you can also type it on the sign-in screen). Firebase *web* values are public by design, but you still set them on the backend only: it hands them to the dashboard.",
           "",
           "**The `edit-me` rule.** Lines in `.env.example` that say `edit-me` are the ones only you can fill in. The app treats `edit-me` as empty, so leaving them is harmless.",
           "",
           "**Never commit** secrets (marked SECRET), and never put them on Vercel. Most options can also be changed later in the dashboard under Settings > All settings; secrets cannot, they stay in the environment.",
           "",
           "Removed in 1.2.0: `NTFY_URL`, `NTFY_TOPIC` (push now uses Firebase), `WEATHER_API_KEY` (Open-Meteo needs no key), `GIPHY_API_KEY` (GIPHY was removed).",
           ""]
    group = None
    for f in FIELDS:
        if f.group != group:
            group = f.group
            out += ["", f"## {group}", "", "| Variable | Default | What it does |", "|---|---|---|"]
        name = f.name.upper()
        default = "`edit-me`" if f.name in NEEDS_EDIT else (f"`{f.default}`" if f.default not in ("", None) else (f"blank ({BLANK_BECAUSE[f.name]})" if f.name in BLANK_BECAUSE else "blank"))
        k = kind(f.name)
        tag = f" **{k}**" if k == "SECRET" else (f" _{k}_" if k else "")
        out.append(f"| `{name}`{tag} | {default} | {f.description.replace('|', '/')} |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        sys.exit(0 if TARGET.exists() and TARGET.read_text() == text else 1)
    TARGET.write_text(text)
    print(f"Wrote {TARGET} ({text.count(chr(10))} lines)")
