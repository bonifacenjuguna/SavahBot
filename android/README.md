# SavahLive for Android (1.5.0)

A native Kotlin app with no third-party libraries. Package `com.savahbot.live`, Android 8.0 (API 26) and newer, built against API 34.
What it does and how it talks to SavahBot: `../docs/SAVAHLIVE.md`.

## What to install once
1. **JDK 17** (21 also works).
2. **Android SDK command-line tools**, then:
   ```
   sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"
   sdkmanager --licenses
   ```
3. Set `ANDROID_HOME` to the SDK folder (or create `android/local.properties` containing `sdk.dir=/path/to/sdk`).
4. **Gradle 8.7 or newer, once**, only to create the wrapper (the wrapper's .jar cannot be included in this zip):
   ```
   cd android
   gradle wrapper --gradle-version 8.7
   ```
   From then on use `./gradlew` (`gradlew.bat` on Windows) and Gradle itself is not needed any more.

## Build and install
```
cd android
./gradlew assembleDebug                 # app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
./gradlew test                          # the pure-logic unit tests (src/test)
```
Debug builds also accept `http://` addresses (for testing against your own PC on the same network, for example `http://192.168.1.20:8000`). Release builds are HTTPS only.

## Release APK
Create a key once (keep the file and passwords safe; you need the same key for every update):
```
keytool -genkeypair -v -keystore savahlive.jks -alias savahlive -keyalg RSA -keysize 2048 -validity 10000
```
Create `android/keystore.properties`:
```
storeFile=savahlive.jks
storePassword=...
keyAlias=savahlive
keyPassword=...
```
Then `./gradlew assembleRelease` gives `app/build/outputs/apk/release/app-release.apk` (shrunk and signed). Both files are in `.gitignore`.
For Google Play you would also need a newer `targetSdk` as Play requires at the time, and an explanation of the foreground-service use ("special use": a floating livestream overlay).

## Using it
1. In SavahBot: Manage > SavahLive > Pair a phone.
2. On the phone: scan the QR code with the camera and tap **Open SavahLive** (or paste the link / type the code in the app).
3. Allow **Display over other apps**, then **Start overlay**. Open PUBG Mobile or any app.

## Project map
| File | Job |
|---|---|
| `Wire.kt` | Plain Kotlin: number formatting, the stream parser, reconnect timing, pairing-link parsing. Unit-tested. |
| `Store.kt` | What the phone remembers. The device key is encrypted with an Android Keystore key. |
| `Net.kt` | Pairing and key renewal (HttpURLConnection). |
| `Feed.kt` | The one connection: reads SavahBot's feed, reconnects with backoff, pauses when the screen is off. |
| `Overlay.kt` | The floating window: pill, docking, ticker, big chat window, opacity. |
| `OverlayService.kt` | Foreground service tying the two together; ends everything when the overlay is closed. |
| `MainActivity.kt` | The single screen: pair, permissions, start/stop. |

## First-run checklist
- Pair, start the overlay, switch to another app: the pill stays on top.
- Drag to each edge and let go: it docks. Tap: the chat window opens. Long-press the pill: Solid, Glass, Ghost.
- In SavahBot's Demo mode, start the demo: lines slide out under the pill.
- Switch the screen off and on: the connection closes and reopens by itself (the notification shows it).
- Remove the phone in Manage > SavahLive: the overlay says it was unpaired and stops.
- Turn on airplane mode for a minute, then off: it reconnects without asking to pair again.
