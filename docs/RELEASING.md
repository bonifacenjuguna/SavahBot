# Releasing SavahLive (and keeping releases safe)

Signed APKs live in `releases/savahlive/<version>/` and are **write-once**: a new build is a new folder, an old one is never edited, replaced or deleted.
Three layers protect that: the files are made read-only when created, a GitHub workflow (`.github/workflows/protect-releases.yml`) rejects any change to an existing release folder,
and a GitHub ruleset (one-time setup below) makes that check mandatory.

## One-time setup

**1. Commit the Gradle wrapper.** The repo currently has no `gradlew`, `gradlew.bat` or `gradle-wrapper.jar`, so a fresh clone cannot build. From the repo root:
```powershell
git add -f android/gradlew android/gradlew.bat android/gradle/wrapper/gradle-wrapper.jar
git commit -m "Add Gradle wrapper"
```
(`-f` only because some global ignore rules hide `.jar` files.) Also commit this release setup: `.gitignore`, `.gitattributes`, `.github/`, `scripts/`, `releases/`, `docs/RELEASING.md`.

**2. Create your signing key, once.** Follow `android/README.md` section 6 (keytool, then `android/keystore.properties`).
Back up `android/savahlive.jks` and its passwords somewhere safe and **private** (password manager, USB stick, cloud vault). They are in `.gitignore` and must never be committed.
Android only installs an update if it is signed with the same key. Lose it, and everybody has to uninstall SavahLive and pair again.

**3. Turn on the protection in GitHub** (otherwise the workflow only warns after the fact). Repo > Settings > Rules > Rulesets > New ruleset > New branch ruleset:
- Name `Protect main`, Enforcement `Active`, target the default branch (`main`).
- Tick **Restrict deletions** and **Block force pushes**.
- Tick **Require a pull request before merging** (required approvals: 0 is fine when you work alone).
- Tick **Require status checks to pass** and add **immutable** (the "Protect releases" job). It only appears in the list after the workflow has run once, so open any pull request that touches `releases/` first, then come back and add it.
- Optional: a second ruleset of type **Tag** for `savahlive-v*` with **Restrict updates** and **Restrict deletions**, so a published version tag can never be moved.

You, as the owner, can still bypass rules if you ever truly must. Make that a deliberate act, not an accident.

## Making a release

1. Finish and test the change. Run the tests (`docs/TESTING.md`; `npm test` in `frontend/`).
2. Bump the version everywhere with one command, then write the CHANGELOG section:
   ```powershell
   python scripts\bump_version.py 1.5.1
   ```
   It updates the dashboard, service worker, `package.json`, backend and the Android `versionName`/`versionCode` (1.5.1 becomes 10501). It refuses to go backwards, because Android will not install an older `versionCode` over a newer one. Add a `## 1.5.1` section to `CHANGELOG.md` (it is copied into the release notes).
   `python scripts\bump_version.py --check` shows whether all places agree (a backend test runs the same check).
3. Commit your changes, then build and file the release:
   ```powershell
   .\scripts\release-savahlive.ps1
   ```
   It builds the signed release APK, verifies the signature with `apksigner`, refuses to run if that version folder already exists or if the APK is signed with the debug key, then creates `releases\savahlive\1.5.1\` with `SavahLive-1.5.1.apk`, `SHA256SUMS` and `RELEASE.md`.
4. Publish through a branch so the protection can do its job:
   ```powershell
   git checkout -b release/1.5.1
   git add releases/savahlive/1.5.1
   git commit -m "SavahLive 1.5.1 release APK"
   git push -u origin release/1.5.1
   ```
   Open the pull request on GitHub, wait for the green **Protect releases** check, merge, then tag:
   ```powershell
   git checkout main; git pull
   git tag savahlive-v1.5.1; git push origin savahlive-v1.5.1
   ```
5. Install on your phone to test the real thing. A **release** APK has a different signature from the **debug** one you have installed now, so Android will refuse to update over it (`INSTALL_FAILED_UPDATE_INCOMPATIBLE`). Uninstall the debug build once (`adb uninstall com.savahbot.live`; you will need to pair again), then install the release APK. After that, every later release installs over the last one and keeps the pairing.

## If a released APK has a problem
Never edit or delete it. Fix the code, bump the version, release a new one. Say in the new `CHANGELOG.md` section which older version to avoid.

## Where people get the APK
Anyone with access to the repo can open `releases/savahlive/<version>/` and download the APK. For a public repo, the direct link has the form
`https://github.com/<owner>/<repo>/raw/main/releases/savahlive/1.5.0/SavahLive-1.5.0.apk`.
Each APK adds about 2 MB to the repo for good. If that ever matters, GitHub Releases (attach the same APK to the tag) keeps the repo small; the checksum in `SHA256SUMS` stays the same.

## Tips
- **Railway and Vercel** redeploy when the repo changes. In Railway set the watch paths to `/backend/**`; in Vercel set the root directory to `frontend` and "Ignored Build Step" so a new APK commit does not rebuild your site.
- Android Play Protect may show "unknown app" the first time you install outside Google Play. That is normal for a sideloaded APK.
- `scripts\check_releases.py` (run by the workflow) verifies every release folder: one APK named for its version, a matching checksum, a `RELEASE.md`.
