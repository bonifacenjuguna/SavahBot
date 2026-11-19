package com.androx.app.platform

import android.app.AlarmManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.core.app.NotificationManagerCompat

data class PermissionStatus(
    val notificationsAllowed: Boolean,
    /** Android 13+ shows a runtime prompt; before that the user can only toggle it in system settings. */
    val notificationsNeedRuntimePrompt: Boolean,
    val exactAlarmsAllowed: Boolean,
    val exactAlarmsApply: Boolean,
    val batteryUnrestricted: Boolean,
)

object Permissions {
    private fun safeStart(context: Context, intent: Intent) {
        try {
            context.startActivity(intent)
        } catch (e: android.content.ActivityNotFoundException) {
            // Some OEM builds lack individual settings screens; fall back to the app's details page.
            val fallback = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            runCatching { context.startActivity(fallback) }
        }
    }

    fun status(context: Context): PermissionStatus {
        val alarm = context.getSystemService(AlarmManager::class.java)
        val power = context.getSystemService(PowerManager::class.java)
        val exactApplies = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
        return PermissionStatus(
            notificationsAllowed = NotificationManagerCompat.from(context).areNotificationsEnabled(),
            notificationsNeedRuntimePrompt = Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU,
            exactAlarmsAllowed = !exactApplies || alarm.canScheduleExactAlarms(),
            exactAlarmsApply = exactApplies,
            batteryUnrestricted = power.isIgnoringBatteryOptimizations(context.packageName),
        )
    }

    fun notificationsEnabled(context: Context): Boolean = NotificationManagerCompat.from(context).areNotificationsEnabled()

    fun openNotificationSettings(context: Context) {
        val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
            .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        safeStart(context, intent)
    }

    fun openExactAlarmSettings(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
        val intent = Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:${context.packageName}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        safeStart(context, intent)
    }

    fun openBatterySettings(context: Context) {
        val intent = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        safeStart(context, intent)
    }
}
