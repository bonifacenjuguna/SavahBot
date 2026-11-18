// SavahLive: plain Gradle, no Android Studio needed. Versions are pinned to a combination that is known to work together:
// Android Gradle Plugin 8.5.2 needs Gradle 8.7 or newer and JDK 17 or newer; Kotlin 1.9.24 is the matching compiler.
plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}
