# SavahLive for Android — Build & Developer Guide

SavahLive is the lightweight native Android companion for SavahBot. It is written in Kotlin and intentionally has no third-party runtime libraries.

- **Package:** `com.savahbot.live`
- **Minimum Android version:** Android 8.0 (API 26)
- **Compile / target SDK:** API 34
- **Current app version:** 1.5.0 (versionCode 10500)
- **Java/Kotlin bytecode target:** Java 17
- **Build system:** Gradle 8.7 + Android Gradle Plugin 8.5.2

For the product architecture, pairing flow, backend endpoints, and responsibilities, see [`../docs/SAVAHLIVE.md`](../docs/SAVAHLIVE.md).

This guide is written with **Windows 10/11 + PowerShell + VS Code** as the primary workflow. macOS/Linux equivalents are included where useful.

---

## 1. What you need

Install these tools once:

1. **JDK 17 or newer.** JDK 17 is the project target; JDK 21 is also supported by this setup.
2. **Android SDK command-line tools.** Android Studio is not required.
3. **Git** to clone or update the source.
4. **Visual Studio Code** (or another editor) to edit Kotlin and Gradle files.
5. **Gradle 8.7** only for the initial wrapper-generation step if the Gradle wrapper scripts/JAR are missing.

You do not need an Android emulator. A physical Android phone with USB debugging is sufficient and is often lighter on lower-spec computers.

### 1.1 Install Android SDK packages

After installing the Android command-line tools, open PowerShell and set the SDK location. Replace the path if your SDK is elsewhere:

```powershell
$Sdk = "$env:LOCALAPPDATA\Android\Sdk"
[Environment]::SetEnvironmentVariable("ANDROID_HOME", $Sdk, "User")
[Environment]::SetEnvironmentVariable("ANDROID_SDK_ROOT", $Sdk, "User")
```

Add these folders to your **User PATH** (through Windows Environment Variables, or your preferred PowerShell method):

```text
%LOCALAPPDATA%\Android\Sdk\platform-tools
%LOCALAPPDATA%\Android\Sdk\cmdline-tools\latest\bin
```

Close and reopen PowerShell after changing environment variables. Confirm the SDK manager is available:

```powershell
sdkmanager.bat --version
```

Install the SDK packages required by this project:

```powershell
sdkmanager.bat "platform-tools" "platforms;android-34" "build-tools;34.0.0"
sdkmanager.bat --licenses
```

Read and accept the SDK licence prompts. Confirm the required platform exists:

```powershell
Test-Path "$env:ANDROID_HOME\platforms\android-34"
```

It should return `True`.

> Keep the SDK packages aligned with this project's `compileSdk = 34` and `buildToolsVersion = 34.0.0`. Installing newer Android platforms does not automatically change this project's compile SDK.

### 1.2 Configure Java

Set `JAVA_HOME` to the JDK installation directory (not its `bin` folder). Example:

```powershell
$JavaHome = "C:\Program Files\Java\jdk-21"
[Environment]::SetEnvironmentVariable("JAVA_HOME", $JavaHome, "User")
```

Add `%JAVA_HOME%\bin` to the User PATH, reopen PowerShell, and verify:

```powershell
java --version
javac --version
```

The project compiles Java/Kotlin source to JVM target 17. A JDK 21 installation can compile for target 17.

### 1.3 Install Gradle for the first-time wrapper setup only

The project uses the Gradle Wrapper pinned to **Gradle 8.7**. If `gradlew.bat`, `gradlew`, or `gradle/wrapper/gradle-wrapper.jar` is missing (for example, in a source archive that omits the wrapper JAR), install Gradle 8.7 once.

After installing Gradle and adding its `bin` directory to PATH, verify:

```powershell
gradle --version
```

You only need the system `gradle` command to generate the wrapper. Normal builds should use `gradlew.bat` on Windows or `./gradlew` on macOS/Linux. The wrapper downloads and uses the exact Gradle version configured in `gradle/wrapper/gradle-wrapper.properties`.

---

## 2. Get the source and open it in VS Code

Clone the project if you have not already:

```powershell
git clone https://github.com/bonifacenjuguna/SavahBot.git
Set-Location .\SavahBot
```

If it is already cloned, open PowerShell in the existing project folder and update it when you intend to use the latest committed version:

```powershell
git pull
```

Open the Android project folder in VS Code:

```powershell
code .\android
```

The Android project root is the **`android`** directory (the directory containing `settings.gradle.kts` and `app\build.gradle.kts`).

Useful VS Code extensions are a Kotlin language-support extension and a Gradle extension. They are editor conveniences; Gradle CLI commands below perform the actual build.

---

## 3. Generate the Gradle Wrapper (first setup only)

In PowerShell, move into the Android project:

```powershell
Set-Location "C:\path\to\SavahBot\android"
```

If the wrapper files are already present, skip wrapper generation and go to the next section.

If they are missing, run:

```powershell
gradle wrapper --gradle-version 8.7
```

On macOS/Linux, run the equivalent command from the `android` directory:

```bash
gradle wrapper --gradle-version 8.7
```

The wrapper files include:

- `gradlew.bat` — Windows launcher
- `gradlew` — macOS/Linux launcher
- `gradle/wrapper/gradle-wrapper.jar`
- `gradle/wrapper/gradle-wrapper.properties`

Verify the wrapper:

**Windows PowerShell**
```powershell
.\gradlew.bat --version
```

**macOS/Linux**
```bash
./gradlew --version
```

The output should report **Gradle 8.7**. The first wrapper run downloads the Gradle distribution; allow it to finish.

> Do not run the system `gradle` command for routine builds. Use the wrapper so everyone builds with the same Gradle version.

---

## 4. Build the debug APK

Run commands from the **`android`** directory.

**Windows PowerShell**
```powershell
.\gradlew.bat assembleDebug
```

**macOS/Linux**
```bash
./gradlew assembleDebug
```

The first build may take several minutes while Gradle downloads the Android Gradle Plugin and dependencies. A successful build ends with:

```text
BUILD SUCCESSFUL
```

The debug APK is created at:

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

Debug builds allow HTTP addresses for development/testing. Do not use an insecure HTTP endpoint in a production release. Release builds are HTTPS-only.

### Run automated unit tests

**Windows PowerShell**
```powershell
.\gradlew.bat test
```

**macOS/Linux**
```bash
./gradlew test
```

A successful test task ends with `BUILD SUCCESSFUL`. Test reports are normally written under:

```text
app/build/reports/tests/testDebugUnitTest/
```

### Clean and rebuild (only when needed)

**Windows PowerShell**
```powershell
.\gradlew.bat clean
.\gradlew.bat assembleDebug
```

**macOS/Linux**
```bash
./gradlew clean
./gradlew assembleDebug
```

---

## 5. Install and run on a physical Android phone

1. Enable **Developer options** on the phone.
2. Enable **USB debugging**.
3. Connect the phone to the computer with a data-capable USB cable.
4. Unlock the phone and accept the USB debugging authorization prompt.

Check that ADB detects the phone:

```powershell
adb devices
```

The device should show the state `device`. If it shows `unauthorized`, unlock the phone and accept the authorization prompt. If no device appears, check the USB cable/port and USB debugging.

Install or update the debug APK from the Android project directory:

**Windows PowerShell**
```powershell
adb install -r "app\build\outputs\apk\debug\app-debug.apk"
```

**macOS/Linux**
```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

The `-r` option reinstalls the app while retaining app data where Android permits.

To launch it, open **SavahLive** from the phone's app drawer. To inspect Android logs while testing:

```powershell
adb logcat
```

Stop the log stream with `Ctrl+C`. To filter for the app's package on Windows:

```powershell
adb logcat | Select-String "savahbot"
```

---

## 6. Create a signed release APK (when you are ready)

**You do not need to do this for normal development or debug testing.** Debug APKs are automatically signed with Android's debug key. The following is the release-signing procedure for when you want to distribute a release APK.

### 6.1 Create a signing keystore — once only

Run this from the **`android`** directory. Keep the keystore in a safe, backed-up location. Do not commit it or send it to anyone:

```powershell
keytool -genkeypair -v -keystore savahlive.jks -alias savahlive -keyalg RSA -keysize 2048 -validity 10000
```

You will be prompted to create a keystore password, confirm it, and enter certificate details. Remember the passwords. The keystore and its passwords are essential for signing future updates with the same app identity.

**Important:** Back up the keystore securely. If you lose it, you may not be able to publish updates signed with the same key. Never put the keystore or passwords in Git, screenshots, source code, or a public ZIP.

### 6.2 Create the local signing properties file

Create this file:

```text
android/keystore.properties
```

Example contents (replace the placeholders with your actual values):

```properties
storeFile=savahlive.jks
storePassword=YOUR_KEYSTORE_PASSWORD
keyAlias=savahlive
keyPassword=YOUR_KEY_PASSWORD
```

Because the keystore was created from the `android` directory, `storeFile=savahlive.jks` points to `android/savahlive.jks`. If you store the keystore somewhere else, set `storeFile` to the correct path relative to the Android project directory, or use an appropriate absolute path.

The existing `android/.gitignore` excludes `*.jks`, `*.keystore`, and `keystore.properties`. Keep those protections in place. Do not commit these files.

### 6.3 Build the signed release APK

From the **`android`** directory:

```powershell
.\gradlew.bat assembleRelease
```

macOS/Linux:

```bash
./gradlew assembleRelease
```

With a valid `keystore.properties` file, the Gradle release build uses that signing configuration. The release APK is created at:

```text
app/build/outputs/apk/release/app-release.apk
```

If `keystore.properties` is absent, the current Gradle configuration leaves the release APK unsigned. Do not distribute an unsigned release APK.

### 6.4 Verify the release signature

Use the Android SDK Build Tools' `apksigner`. On Windows, for the SDK path used in this guide:

```powershell
& "$env:ANDROID_HOME\build-tools\34.0.0\apksigner.bat" verify --verbose --print-certs "app\build\outputs\apk\release\app-release.apk"
```

A successful verification reports that the APK verified. Review the certificate information and keep it consistent across future updates.

### 6.5 Install the release APK for a local test

```powershell
adb install -r "app\build\outputs\apk\release\app-release.apk"
```

A release build is minified and resource-shrunk by the current Gradle configuration. Test its pairing, permissions, overlay, reconnect behaviour, and notifications before distributing it.

> **Google Play note:** Before publishing, review the current Google Play target API requirements and foreground-service policy. This app declares a special-use foreground service for its floating livestream overlay; Play submission may require a clear justification and supporting declaration. The current target SDK 34 may need to be raised for a future Play release.

---

## 7. SavahLive first-run and functional test checklist

1. In SavahBot, open **Manage → SavahLive → Pair a phone**.
2. On the phone, scan the QR code and tap **Open SavahLive**, or enter the pairing code in the app.
3. Allow **Display over other apps** when Android requests it.
4. Start the overlay, then open another app (for example, PUBG Mobile).
5. Confirm the overlay remains visible above the other app.
6. Drag the pill to each screen edge and confirm it docks.
7. Tap the pill to open the chat window. Long-press to test the available visual modes.
8. Use SavahBot Demo mode to confirm sample chat lines appear.
9. Turn the screen off and on; confirm the feed reconnects.
10. Briefly enable airplane mode, then disable it; confirm the feed reconnects without requiring a new pairing.
11. Remove/revoke the phone from **Manage → SavahLive** and confirm the companion stops as expected.

---

## 8. Project file map

| File | Responsibility |
|---|---|
| `app/build.gradle.kts` | Android build configuration, SDK levels, app version, release signing |
| `gradle/wrapper/gradle-wrapper.properties` | Pins the Gradle distribution to 8.7 |
| `Wire.kt` | Number formatting, stream parser, reconnect timing, pairing-link parsing |
| `Store.kt` | Local device state; device key encrypted with Android Keystore |
| `Net.kt` | Pairing and key renewal over `HttpURLConnection` |
| `Feed.kt` | Feed connection, reconnect/backoff, screen-off handling |
| `Overlay.kt` | Floating window UI, docking, ticker, chat window, opacity |
| `OverlayService.kt` | Foreground service that owns the overlay/feed lifecycle |
| `MainActivity.kt` | Pairing, permissions, and start/stop screen |
| `../docs/SAVAHLIVE.md` | Overall architecture and backend integration |

The Android app is intentionally a companion display client. SavahBot remains responsible for YouTube integration, livestream discovery, chat processing, and moderation.

---

## 9. Common build and device commands

Run these from the **`android`** directory unless stated otherwise.

| Task | Windows PowerShell |
|---|---|
| Check Java | `java --version` |
| Check Gradle wrapper | `.\gradlew.bat --version` |
| Build debug APK | `.\gradlew.bat assembleDebug` |
| Run unit tests | `.\gradlew.bat test` |
| Clean build outputs | `.\gradlew.bat clean` |
| Build release APK | `.\gradlew.bat assembleRelease` |
| List connected devices | `adb devices` |
| Install debug APK | `adb install -r app\build\outputs\apk\debug\app-debug.apk` |
| View Android logs | `adb logcat` |

### Troubleshooting

- **`gradlew.bat` is not recognized / not found:** Confirm PowerShell is in the `android` directory and that `gradlew.bat` exists. If the wrapper is missing, follow section 3.
- **Gradle cannot find Java:** Check `JAVA_HOME`, add its `bin` directory to PATH, reopen the terminal, and run `java --version`.
- **Android SDK location not found:** Set `ANDROID_HOME` / `ANDROID_SDK_ROOT`, or create `android/local.properties` with `sdk.dir=C:\\Users\\YOUR_USER\\AppData\\Local\\Android\\Sdk`. Do not commit `local.properties`.
- **SDK platform or Build Tools missing:** Install `platforms;android-34` and `build-tools;34.0.0` using `sdkmanager`, then accept licences.
- **Phone shows `unauthorized`:** Unlock it, accept the USB debugging prompt, then run `adb devices` again.
- **App installs but overlay does not appear:** Check Android's Display over other apps permission and the app's foreground-service notification. Also check that the overlay was explicitly started.
- **A build fails after changing code:** Read the first actual `What went wrong` / compiler error in the Gradle output. Warnings alone do not necessarily mean the build failed.

---

## 10. Before committing changes

- Run `.\gradlew.bat test` and `.\gradlew.bat assembleDebug` on Windows (or the equivalent wrapper commands on macOS/Linux).
- Test the changed behaviour on a physical Android device.
- Do not commit `local.properties`, signing properties, keystores, passwords, generated APKs, or build output.
- Keep the app's thin-client responsibility intact: YouTube and moderation logic belong in SavahBot/backend, not in the Android overlay.

---

## 11. Publishing a release

Signed APKs are filed, checksummed and protected from overwriting by `scripts\release-savahlive.ps1`. The full procedure (version bump, signing key, GitHub protection, installing over a debug build) is in [`../docs/RELEASING.md`](../docs/RELEASING.md). Releases live in `../releases/savahlive/<version>/`.


---

## 12. First-run checklist for 1.6.1 (rebuilt panel and tab)

The 1.6.1 Kotlin was written without a compiler. If `./gradlew assembleDebug` prints errors, send the first few red lines. For a crash, run `adb logcat -b crash` and send the output.
`./gradlew test` runs the theme and geometry unit tests (`src/test`).

1. **Pair and allow:** the three-step flow works.
2. **Panel:** Start overlay. Drag the header to move. Drag each of the four **sides** and four **corners** to resize; there are no grip lines. A simple tap on an edge changes nothing.
3. **Expand:** tap expand: bigger window, icon becomes collapse. Tap again: smaller. The chat scrolls in both.
4. **Tuck:** tap the tuck button. The tab appears; tap it: the panel opens. Repeat 20 times quickly. No crash.
5. **Tab drag:** drag the tab to the centre, to all four edges, away and back. It snaps to an edge and never crashes.
6. **In-app settings:** change panel opacity, text size, theme, tab opacity, Slide away, pop-out size and opacity. Each applies live. Reset size and position works.
7. **Pop-out:** in Demo mode, new chat slides a card out of the tab, using the pop-out size and opacity.
8. **Send:** in Manage > SavahLive turn on Let phones send chat and Can send chat for the phone. A message box appears in the panel; send a line and see it on YouTube and as "You".
9. **Rotate the phone:** panel and tab keep their relative place.
10. **Lock** from the notification: touches pass through; unlock from the notification.
