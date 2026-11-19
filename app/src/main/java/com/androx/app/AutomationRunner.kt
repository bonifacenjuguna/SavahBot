package com.androx.app

import com.androx.app.data.AutomationRepository
import com.androx.app.data.HistoryRepository
import com.androx.app.data.SettingsRepository
import com.androx.app.data.VariableRepository
import com.androx.app.engine.ExecutionEngine
import com.androx.app.model.Automation
import com.androx.app.model.ExecutionRecord
import com.androx.app.model.RunSource
import com.androx.app.model.Trigger

/** Glue between the pure engine and the app's storage: waits for data, runs, records history. */
class AutomationRunner(
    private val automations: AutomationRepository,
    private val history: HistoryRepository,
    private val variables: VariableRepository,
    private val settings: SettingsRepository,
    private val engine: ExecutionEngine,
) {
    private suspend fun awaitData() {
        automations.awaitLoaded()
        history.awaitLoaded()
        variables.awaitLoaded()
    }

    /** Manual run. Works for enabled and disabled automations alike. Returns null if the id no longer exists. */
    suspend fun runManually(id: String): ExecutionRecord? {
        awaitData()
        val automation = automations.get(id) ?: return null
        return runAndRecord(automation, RunSource.MANUAL)
    }

    /** Called by the alarm receiver. Ignores automations that were disabled or re-configured since scheduling. */
    suspend fun runScheduled(id: String): ExecutionRecord? {
        awaitData()
        val automation = automations.get(id) ?: return null
        if (!automation.enabled || automation.trigger !is Trigger.Schedule) return null
        return runAndRecord(automation, RunSource.SCHEDULE)
    }

    private suspend fun runAndRecord(automation: Automation, source: RunSource): ExecutionRecord {
        val record = engine.execute(automation, source)
        history.add(record, settings.settings.value.historyLimit)
        return record
    }
}
