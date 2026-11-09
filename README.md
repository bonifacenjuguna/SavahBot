# SavahBot

A personal, owner-only moderation and utility bot for YouTube live chat, controlled from a web dashboard and from Telegram.

- **Backend** (`backend/`): Python 3.13, Starlette + uvicorn, PostgreSQL (SQLite for local use). Runs on Railway.
- **Dashboard** (`frontend/`): Vite + TypeScript, no framework, responsive for phone, tablet and desktop, installable as an app. Runs on Vercel.
- **Telegram**: webhook or polling, switchable at any time from the dashboard or with `/tgmode`.
- **Demo mode**: simulated chat and nine scenarios (raid, link spammer, caps flood, bot timing, disguised words, ...). Nothing is sent to YouTube or Telegram and no quota is used. Switch between Demo and Live in the sidebar; the status card at the top shows which one you are in (flask = demo, red broadcast icon = on air, power icon = standby). Switching mode redraws every page, so Demo and Live data never mix.

There is no AI in this version. Moderation is a set of explainable algorithms, each of which shows up as a named signal with a weight, so you can always see why a message scored what it did.

---

## Start here

| I want to | Read |
|---|---|
| Deploy it | docs/DEPLOYMENT.md |
| Know every setting | docs/ENVIRONMENT.md |
| Protect sign-in | docs/SECURITY.md |
| Get push notifications | docs/NOTIFICATIONS.md, docs/PWA_AND_PUSH_PLATFORMS.md |
| Add weather | docs/WEATHER.md |
| Back up and restore | docs/BACKUP_AND_RECOVERY.md |
| Fix a problem | docs/TROUBLESHOOTING.md |
| Everything else | docs/README.md |

## Quick start (local)

```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:create_app --factory --reload --port 8000
cd ../frontend && npm install && VITE_API_URL=http://localhost:8000 npm run dev
```

On first start a generated owner password is printed in the log (or set `OWNER_PASSWORD`). Details: docs/TESTING.md.

## What is and is not verified

Automated tests use fakes, never the real YouTube, Firebase or Open-Meteo, and cannot exercise real browsers, phones, hardware passkeys or PostgreSQL. The list and a manual checklist are in docs/TESTING.md. Expect to fix small things on the first real run; Settings > Developer and the logs are designed to make them easy to find.
