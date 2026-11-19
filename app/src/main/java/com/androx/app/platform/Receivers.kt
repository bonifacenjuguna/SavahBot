package com.androx.app.platform

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.androx.app.AndroxApp
import kotlinx.coroutines.launch

/** Fires when a scheduled automation is due. */
class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getStringExtra(AlarmScheduler.EXTRA_ID) ?: return
        val container = (context.applicationContext as AndroxApp).container
        val pending = goAsync()
        container.scope.launch {
            try {
                container.runner.runScheduled(id)
            } finally {
                // Arm the next occurrence whether or not the run worked.
                container.automations.awaitLoaded()
                container.scheduler.reschedule(container.automations.state.value)
                pending.finish()
            }
        }
    }
}

/** Alarms are cleared by reboots, app updates and clock changes, so schedules are re-armed here. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val container = (context.applicationContext as AndroxApp).container
        val pending = goAsync()
        container.scope.launch {
            try {
                container.automations.awaitLoaded()
                container.scheduler.reschedule(container.automations.state.value)
            } finally {
                pending.finish()
            }
        }
    }
}
