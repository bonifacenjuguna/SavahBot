
## CP14 review fixes
Independent review found 10 issues; fixed: push with bell off, bare-404 deleting devices, weather cooldown/signature/unmonitored place/staleness, re-register keeping disabled state, per-row delivery guard, summary leaking sensitive titles, null forecast crash, 0,0 location.

## 1.3.0
Bug batch and new features: see CHANGELOG.md. Unverified here: live YouTube/FCM/Telegram/Postgres behaviour, voice output, vite build. One pre-existing failing test (timer modes 400 vs 422) left for the owner's decision.

## 1.5.0 (SavahLive)
Added the Android overlay companion: backend (`savahlive.py`, `api/savahlive_routes.py`, tests in `tests/test_savahlive.py`), the Manage > SavahLive page, the optional "also unpair phones" tickbox on password change, and the `android/` project. Verified here: the service tests (pairing, keys, expiry, revoke, rotation, feed batching/filtering/cut-off) with fakes, the frontend type-check and its 53 tests. NOT verified here: the backend HTTP tests (no starlette/pytest in this environment; docs/API.md and ENVIRONMENT.md were updated by hand/script to match), `vite build`, and every line of Kotlin (no Android SDK, never compiled or run). First real run: `cd android && gradle wrapper && ./gradlew assembleDebug`, then follow the first-run checklist in android/README.md.

## 1.5.0 follow-up (release setup)
The owner built and ran the SavahLive APK (debug) on a phone: the Kotlin compiled unchanged. Added: write-once `releases/` folder and the "Protect releases" workflow, `scripts/release-savahlive.ps1`, `scripts/bump_version.py`, `scripts/check_releases.py`, root `.gitignore` and `.gitattributes`, `docs/RELEASING.md`, and a backend repo-hygiene test (`tests/test_repo.py`). Still to do by the owner: commit the Gradle wrapper, create the release key, turn on the GitHub ruleset, then run the first signed release. Not verified here: the PowerShell script and the GitHub workflow (no PowerShell or GitHub in this environment).

## 1.6.0 (SavahLive redesign)
Panel + edge tab (Panel/Tab/Overlay/PanelView/TabWindow), themes and SVG icons, guided app screens, redesigned web page, `hide_seconds` and `download_url` settings, logo proportion fix. Verified here: backend service tests (10, against this tree), frontend type-check, icon path validation and rendering, theme contrast maths, bracket/cross-reference scans of the Kotlin. NOT verified: any Kotlin compile or run, the backend HTTP tests, `vite build`, the PowerShell script and the workflow.


## 1.6.1 (SavahLive stability rebuild)
Single-window Overlay with PanelView/TabView, guarded callbacks, edge and corner resizing, in-app settings, separate pop-out controls, send-to-chat (backend + phone + dashboard), web page fixes. Verified here: tsc, SavahLive and config backend tests, Geometry logic executed, Kotlin syntax check (no new unresolved names). NOT verified: any Android compile or run.

## 1.6.2 (SavahLive extras)
Pin, milestones, phone moderation (backend route + two switches), saved looks, auto-open/auto-stop, stream summary, connection banner, update check, notification card with look button. Verified here: backend tests (SavahLive incl. HTTP), tsc, the plain Kotlin logic (versions, milestones, tally) by running it, Kotlin syntax check. NOT verified: any Android compile or run.
