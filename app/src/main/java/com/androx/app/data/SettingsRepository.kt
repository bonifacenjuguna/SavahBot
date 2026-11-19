package com.androx.app.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class ThemeMode { SYSTEM, LIGHT, DARK }

data class AppSettings(
    val themeMode: ThemeMode = ThemeMode.SYSTEM,
    /** Material You colours from the wallpaper (Android 12+). Off by default so the monochrome Androx palette is used. */
    val dynamicColor: Boolean = false,
    /** True-black dark theme. */
    val pureBlack: Boolean = false,
    val historyLimit: Int = 100,
)

class SettingsRepository(context: Context) {
    private val prefs = context.getSharedPreferences("androx_settings", Context.MODE_PRIVATE)
    private val _settings = MutableStateFlow(read())
    val settings: StateFlow<AppSettings> = _settings.asStateFlow()

    private fun read(): AppSettings = AppSettings(
        themeMode = runCatching { ThemeMode.valueOf(prefs.getString("theme", "SYSTEM") ?: "SYSTEM") }
            .getOrDefault(ThemeMode.SYSTEM),
        dynamicColor = prefs.getBoolean("dynamic", false),
        pureBlack = prefs.getBoolean("pure_black", false),
        historyLimit = prefs.getInt("history_limit", 100),
    )

    fun update(transform: (AppSettings) -> AppSettings) {
        val next = transform(_settings.value)
        _settings.value = next
        prefs.edit()
            .putString("theme", next.themeMode.name)
            .putBoolean("dynamic", next.dynamicColor)
            .putBoolean("pure_black", next.pureBlack)
            .putInt("history_limit", next.historyLimit)
            .apply()
    }
}
