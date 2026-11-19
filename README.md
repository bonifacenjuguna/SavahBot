# Androx v0.0.0

Lightweight, local-only Android automation app. Kotlin, Jetpack Compose, Material 3. No backend, no network.

**Open in Android Studio (Ladybug or newer, JDK 17)** and sync. The Gradle wrapper *properties* are included (Gradle 8.9);
the wrapper JAR/scripts are not (they are binary and could not be generated offline). Android Studio does not need them;
from a terminal run `gradle wrapper` once. Build: `./gradlew :app:assembleDebug`; unit tests: `./gradlew :app:testDebugUnitTest`.

## What is in it
- **Model** (`model/`): one shared representation, Trigger -> optional Condition -> Actions. All three editors read/write it.
- **Engine** (`engine/`): pure Kotlin executor + Rhino JavaScript runner (sandboxed, 5 s limit). Unit-tested on the JVM.
- **Data** (`data/`): JSON files in app storage (atomic writes), SharedPreferences for settings.
- **Platform** (`platform/`): notifications, AlarmManager scheduling, boot re-arm, permission helpers.
- **UI** (`ui/`): Home, Automations, History, Settings, and the editor (Builder / JavaScript / Visual workflow tabs).
- **Brand** (`brand/`): original logo plus transparent white/black/silver/charcoal PNGs, SVG, 512 and 1024 icons.

## Triggers / conditions / actions
Triggers: Manual, Schedule (time + weekdays). Conditions: Battery level, Charging state, Variable comparison.
Actions: Show notification, Set/Add variable, Run another automation, Write to log, Run JavaScript.
Templates in text fields: `{{battery}} {{time}} {{date}} {{automation}} {{yourVariable}}`.

## JavaScript API
`androx.log / notify / getVar / setVar / deleteVar / battery / isCharging / now`, plus `console.log`.
