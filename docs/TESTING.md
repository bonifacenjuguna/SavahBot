# Testing guide

## Run it locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env              # optional; everything has a default
uvicorn app.main:create_app --factory --reload --port 8000
python -m pytest

cd ../frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev
```

With no `DATABASE_URL` the backend uses a local SQLite file. On first start it prints a generated owner password in the log unless you set `OWNER_PASSWORD`. Add `CORS_ORIGINS=http://localhost:5173` for the dev server.

`backend/.env.example` is generated from `backend/app/config.py`. After adding a setting there, run `python scripts/gen_env_example.py` (a test fails if the file is stale). Settings marked editable can also be changed from the dashboard and then override the environment until you reset them.


## What the tests cover
`cd backend && python -I -m pytest -q -p no:cacheprovider` runs everything (about 2 minutes). Frontend: `cd frontend && npx tsc --noEmit -p .` (type check) and `npm run build`.

| Area | File |
|---|---|
| Notifications (engine, quiet hours, retries, dedupe, FCM signing, API) | `tests/test_notify.py` |
| Weather (normalization, cache, single flight, stale data, rules, API) | `tests/test_weather.py` |
| Security (crypto, WebAuthn, TOTP, sessions, step-up, lockdown) | `tests/test_access_*.py` |
| Backup (archive format, import/export, rollback, restore token) | `tests/test_backup.py` |
| History, bans, knowledge | `tests/test_history.py`, `test_bans.py`, `test_intel_*.py` |
| Config and generated docs staying current | `tests/test_config.py` |

Style: plain `asyncio.run(go())` tests (no pytest-asyncio), `@e2e` for HTTP-level tests with `api.call(method, path, body)`, fakes for YouTube, Firebase and Open-Meteo.

## What is not tested (be honest with yourself)
- Real Firebase delivery, real browser permission prompts and tokens, iOS/Android behaviour.
- Real Open-Meteo responses (tests use fixtures built from its documented shape).
- Real passkey ceremonies with a hardware authenticator, and real PostgreSQL (use `scripts/check_db.py`).
- A production `vite build` and the Railway/Vercel deploys.
Manual check list after deploying: sign in; add a second method; Notifications > turn on push > Send a test; Weather > add a place; Backup > export, then Import (dry run); install the app on your phone.
