import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.savahbot.live"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.savahbot.live"
        minSdk = 26               // Android 8.0: the first version with the modern overlay window type, so no legacy code paths
        targetSdk = 34
        versionCode = 10601
        versionName = "1.6.1"
    }

    buildFeatures {
        buildConfig = true        // BuildConfig.VERSION_NAME / DEBUG
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // Signing: see android/README.md. Without a keystore.properties file the release build is left unsigned.
            val props = rootProject.file("keystore.properties")
            if (props.exists()) {
                val p = Properties().apply { props.inputStream().use { load(it) } }
                signingConfig = signingConfigs.create("release") {
                    storeFile = rootProject.file(p.getProperty("storeFile"))
                    storePassword = p.getProperty("storePassword")
                    keyAlias = p.getProperty("keyAlias")
                    keyPassword = p.getProperty("keyPassword")
                }
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

// No runtime dependencies on purpose: everything the app needs is in the Android platform.
dependencies {
    testImplementation("junit:junit:4.13.2")
}
