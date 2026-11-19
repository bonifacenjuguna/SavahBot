package com.androx.app.platform

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.androx.app.MainActivity
import com.androx.app.R
import com.androx.app.engine.ActionException
import com.androx.app.engine.DeviceBridge
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.roundToInt

class AndroidDeviceBridge(private val context: Context) : DeviceBridge {
    companion object {
        const val CHANNEL_ID = "automations"
    }

    private val counter = AtomicInteger(1000)

    private fun batteryIntent(): Intent? =
        context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))

    override fun batteryLevel(): Int {
        val intent = batteryIntent()
        val level = intent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = intent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        if (level < 0 || scale <= 0) throw ActionException("Android did not report a battery level.")
        return (level * 100f / scale).roundToInt()
    }

    override fun isCharging(): Boolean {
        val intent = batteryIntent() ?: throw ActionException("Android did not report the charging state.")
        val status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        return status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL
    }

    @Suppress("MissingPermission") // permission state is verified with areNotificationsEnabled() below
    override fun showNotification(title: String, message: String) {
        val manager = NotificationManagerCompat.from(context)
        if (!manager.areNotificationsEnabled()) {
            throw ActionException("Notifications are blocked for Androx. Allow them in Settings → Permissions.")
        }
        ensureChannel()
        val channel = manager.getNotificationChannel(CHANNEL_ID)
        if (channel != null && channel.importance == NotificationManager.IMPORTANCE_NONE) {
            throw ActionException("The \"Automation notifications\" channel is turned off in Android settings.")
        }
        val open = PendingIntent.getActivity(
            context,
            0,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_androx)
            .setContentTitle(title.ifBlank { "Androx" })
            .setContentText(message)
            .setStyle(NotificationCompat.BigTextStyle().bigText(message))
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        try {
            manager.notify(counter.incrementAndGet(), notification)
        } catch (e: SecurityException) {
            throw ActionException("Android blocked the notification: ${e.message}")
        }
    }

    private fun ensureChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            context.getString(R.string.notification_channel_name),
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply { description = context.getString(R.string.notification_channel_description) }
        NotificationManagerCompat.from(context).createNotificationChannel(channel)
    }
}
