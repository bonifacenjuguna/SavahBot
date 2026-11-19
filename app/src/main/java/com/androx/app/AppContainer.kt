package com.androx.app

import android.app.Application
import com.androx.app.data.AutomationRepository
import com.androx.app.data.HistoryRepository
import com.androx.app.data.SettingsRepository
import com.androx.app.data.VariableRepository
import com.androx.app.engine.ExecutionEngine
import com.androx.app.platform.AlarmScheduler
import com.androx.app.platform.AndroidDeviceBridge
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/** Hand-rolled dependency container: one instance for the whole process, created by [AndroxApp]. */
class AppContainer(app: Application) {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    val settings = SettingsRepository(app)
    val scheduler = AlarmScheduler(app)
    val variables = VariableRepository(app.filesDir, scope)
    val history = HistoryRepository(app.filesDir, scope)
    val automations = AutomationRepository(app.filesDir, scope) { list -> scheduler.reschedule(list) }

    private val bridge = AndroidDeviceBridge(app)
    private val engine = ExecutionEngine(
        device = bridge,
        variables = variables,
        findAutomation = { id -> automations.get(id) },
    )
    val runner = AutomationRunner(automations, history, variables, settings, engine)

    /** True once everything the UI needs from disk has been read. */
    val isReady: Boolean
        get() = automations.loaded.value && history.loaded.value

    init {
        // Restore alarms for saved schedules (the system forgets them after reboots, updates and force-stops).
        scope.launch {
            automations.awaitLoaded()
            scheduler.reschedule(automations.state.value)
        }
    }
}
