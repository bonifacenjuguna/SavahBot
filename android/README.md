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

1. **JDK 17 or JDK 21.** JDK 17 is the minimum for this Android Gradle Plugin setup; JDK 21 is also supported and is the version used for the tested Windows build.
2. **Android SDK command-line tools.** Android Studio is not required. The installation steps below show how to install the tools manually.
3. **Git** to clone or update the source.
4. **Visual Studio Code** (or another editor) to edit Kotlin and Gradle files.
5. **Gradle 8.7** only for the initial wrapper-generation step if the Gradle wrapper scripts/JAR are missing.

You do not need an Android emulator. A physical Android phone with USB debugging is sufficient and is often lighter on lower-spec computers.

### 1.1 Install Android SDK command-line tools and packages

Android Studio is optional. To install the SDK without it, first install and configure a JDK by following section **1.3 Configure Java**. The SDK manager needs Java when it installs packages.

1. Open the official Android Studio download page:
   `https://developer.android.com/studio#command-line-tools-only`
2. Under **Command line tools only**, download the **Windows** ZIP.
3. Rename the downloaded ZIP to `commandlinetools-win-latest.zip` and leave it in your Downloads folder.
4. Open PowerShell and run the following. If you saved the ZIP somewhere else, change `$Zip`.

```powershell
$Sdk = "$env:LOCALAPPDATA\Android\Sdk"
$Zip = "$env:USERPROFILE\Downloads\commandlinetools-win-latest.zip"
$TempTools = Join-Path $env:TEMP "android-command-line-tools"

if (-not (Test-Path $Zip)) {
    throw "Command-line tools ZIP not found: $Zip"
}

New-Item -ItemType Directory -Force -Path $Sdk | Out-Null
if (Test-Path $TempTools) {
    Remove-Item $TempTools -Recurse -Force
}
Expand-Archive -LiteralPath $Zip -DestinationPath $TempTools
New-Item -ItemType Directory -Force -Path "$Sdk\cmdline-tools\latest" | Out-Null
Copy-Item "$TempTools\cmdline-tools\*" "$Sdk\cmdline-tools\latest" -Recurse -Force

Write-Host "Android command-line tools installed under $Sdk\cmdline-tools\latest"
```

The final folder layout must contain:

```text
%LOCALAPPDATA%\Android\Sdk\cmdline-tools\latest\bin\sdkmanager.bat
```

### 1.2 Set Android SDK environment variables and PATH

Run this PowerShell block once. It sets the SDK variables permanently for your Windows user and adds the required folders to User PATH without adding duplicate entries:

```powershell
$Sdk = "$env:LOCALAPPDATA\Android\Sdk"
[Environment]::SetEnvironmentVariable("ANDROID_HOME", $Sdk, "User")
[Environment]::SetEnvironmentVariable("ANDROID_SDK_ROOT", $Sdk, "User")

$RequiredPaths = @(
    "$Sdk\platform-tools",
    "$Sdk\cmdline-tools\latest\bin"
)
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$PathEntries = @($UserPath -split ";" | Where-Object { $_ })

foreach ($Entry in $RequiredPaths) {
    if ($PathEntries -notcontains $Entry) {
        $PathEntries += $Entry
    }
}

[Environment]::SetEnvironmentVariable("Path", ($PathEntries -join ";"), "User")
$env:ANDROID_HOME = $Sdk
$env:ANDROID_SDK_ROOT = $Sdk
$env:Path = "$env:Path;$($RequiredPaths -join ';')"
```

Close and reopen PowerShell so the permanent User PATH is loaded. Confirm the SDK manager is available:

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
Test-Path "$env:ANDROID_HOME\build-tools\34.0.0"
```

Both commands should return `True`.

> Keep the SDK packages aligned with this project's `compileSdk = 34` and `buildToolsVersion = 34.0.0`. Installing newer Android platforms does not automatically change this project's compile SDK.

### 1.3 Configure Java

Install a JDK 17 or JDK 21 distribution first. Set `JAVA_HOME` to the JDK installation directory (not its `bin` folder). Change the example path to match the JDK folder actually installed on your computer:

```powershell
$JavaHome = "C:\Program Files\Java\jdk-21"
if (-not (Test-Path "$JavaHome\bin\java.exe")) {
    throw "JDK not found at $JavaHome. Correct the JavaHome path before continuing."
}

[Environment]::SetEnvironmentVariable("JAVA_HOME", $JavaHome, "User")
$JavaBin = "$JavaHome\bin"
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$PathEntries = @($UserPath -split ";" | Where-Object { $_ })
if ($PathEntries -notcontains $JavaBin) {
    $PathEntries += $JavaBin
}
[Environment]::SetEnvironmentVariable("Path", ($PathEntries -join ";"), "User")
$env:JAVA_HOME = $JavaHome
$env:Path = "$env:Path;$JavaBin"
```

Close and reopen PowerShell, then verify:

```powershell
java --version
javac --version
$env:JAVA_HOME
```

The commands should identify the JDK you installed. The project compiles Java/Kotlin source to JVM target 17. JDK 21 can compile for target 17.

### 1.4 Install Gradle for the first-time wrapper setup only

The project uses the Gradle Wrapper pinned to **Gradle 8.7**. You normally do not need to install Gradle separately: use the committed wrapper files and continue to section 3.

Only install system Gradle if the wrapper launcher or `gradle/wrapper/gradle-wrapper.jar` is missing and you need to regenerate it.

For Windows:

1. Open the official Gradle releases page: `https://gradle.org/releases/`.
2. Download the **binary-only ZIP** for Gradle **8.7**.
3. Extract it so the resulting folder is `C:\Gradle\gradle-8.7\` (the `bin` folder should be `C:\Gradle\gradle-8.7\bin\`).
4. Add that `bin` folder to User PATH and verify:

```powershell
$GradleBin = "C:\Gradle\gradle-8.7\bin"
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$PathEntries = @($UserPath -split ";" | Where-Object { $_ })
if ($PathEntries -notcontains $GradleBin) {
    $PathEntries += $GradleBin
}
[Environment]::SetEnvironmentVariable("Path", ($PathEntries -join ";"), "User")
$env:Path = "$env:Path;$GradleBin"
gradle --version
```

The output should report Gradle 8.7. On macOS/Linux, install Gradle 8.7 using the official instructions at `https://gradle.org/install/`.

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
