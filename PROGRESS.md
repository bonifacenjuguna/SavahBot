
## CP14 review fixes
Independent review found 10 issues; fixed: push with bell off, bare-404 deleting devices, weather cooldown/signature/unmonitored place/staleness, re-register keeping disabled state, per-row delivery guard, summary leaking sensitive titles, null forecast crash, 0,0 location.

## 1.3.0
Bug batch and new features: see CHANGELOG.md. Unverified here: live YouTube/FCM/Telegram/Postgres behaviour, voice output, vite build. One pre-existing failing test (timer modes 400 vs 422) left for the owner's decision.

## 1.5.0 (SavahLive)
Added the Android overlay companion: backend (`savahlive.py`, `api/savahlive_routes.py`, tests in `tests/test_savahlive.py`), the Manage > SavahLive page, the optional "also unpair phones" tickbox on password change, and the `android/` project. Verified here: the service tests (pairing, keys, expiry, revoke, rotation, feed batching/filtering/cut-off) with fakes, the frontend type-check and its 53 tests. NOT verified here: the backend HTTP tests (no starlette/pytest in this environment; docs/API.md and ENVIRONMENT.md were updated by hand/script to match), `vite build`, and every line of Kotlin (no Android SDK, never compiled or run). First real run: `cd android && gradle wrapper && ./gradlew assembleDebug`, then follow the first-run checklist in android/README.md.
