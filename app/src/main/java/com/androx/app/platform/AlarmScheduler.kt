package com.androx.app.platform

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import com.androx.app.model.Automation
import com.androx.app.model.Trigger

/**
 * Schedules daily/weekly triggers with AlarmManager.
 * Exact alarms need a user-granted special permission on Android 12+; without it Androx uses inexact alarms
 * (which Android may delay) and says so in Settings.
 */
class AlarmScheduler(private val context: Context) {
    companion object {
        const val ACTION_RUN = "com.androx.app.action.RUN_SCHEDULED"
        const val EXTRA_ID = "automation_id"
        private const val PREFS = "androx_alarms"
        private const val KEY_IDS = "scheduled_ids"
    }

    private val alarmManager: AlarmManager = context.getSystemService(AlarmManager::class.java)
    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun canScheduleExact(): Boolean = Build.VERSION.SDK_INT < Build.VERSION_CODES.S || alarmManager.canScheduleExactAlarms()

    /** Brings the system's alarms in line with the given automations. Safe to call at any time. */
    @Synchronized
    fun reschedule(automations: List<Automation>) {
        val previous = prefs.getStringSet(KEY_IDS, emptySet()).orEmpty()
        val wanted = automations.filter { it.enabled && it.trigger is Trigger.Schedule }
        val wantedIds = wanted.map { it.id }.toSet()
        (previous - wantedIds).forEach { cancel(it) }
        val now = System.currentTimeMillis()
        for (automation in wanted) {
            val trigger = automation.trigger as Trigger.Schedule
            schedule(automation.id, trigger.nextRunMillis(now))
        }
        prefs.edit().putStringSet(KEY_IDS, wantedIds).apply()
    }

    private fun pendingIntent(id: String): PendingIntent {
        val intent = Intent(context, AlarmReceiver::class.java).apply {
            action = ACTION_RUN
            data = Uri.parse("androx://automation/$id")
            putExtra(EXTRA_ID, id)
        }
        return PendingIntent.getBroadcast(context, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    private fun schedule(id: String, atMillis: Long) {
        val pi = pendingIntent(id)
        try {
            if (canScheduleExact()) {
                alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, atMillis, pi)
            } else {
                alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, atMillis, pi)
            }
        } catch (e: SecurityException) {
            alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, atMillis, pi)
        }
    }

    private fun cancel(id: String) {
        alarmManager.cancel(pendingIntent(id))
    }
}
