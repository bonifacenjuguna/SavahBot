package com.androx.app.ui

import androidx.lifecycle.ViewModel
import com.androx.app.AppContainer
import com.androx.app.model.Automation
import com.androx.app.model.ExecutionRecord
import com.androx.app.model.ExecutionStatus
import com.androx.app.samples.Samples
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import java.util.UUID

class MainViewModel(private val container: AppContainer) : ViewModel() {
    val automations = container.automations.state
    val history = container.history.state
    val settings = container.settings.settings
    val variables = container.variables.snapshot
    val loaded = container.automations.loaded

    private val _messages = Channel<String>(Channel.BUFFERED)
    /** One-off messages for the snackbar. */
    val messages = _messages.receiveAsFlow()

    // Work runs in the app scope so it finishes even if the user leaves the screen.
    fun setEnabled(id: String, enabled: Boolean) {
        container.scope.launch { container.automations.setEnabled(id, enabled) }
    }

    fun delete(automation: Automation) {
        container.scope.launch {
            container.automations.delete(automation.id)
            _messages.send("Deleted “${automation.name}”")
        }
    }

    fun duplicate(automation: Automation) {
        container.scope.launch {
            val now = System.currentTimeMillis()
            container.automations.upsert(
                automation.copy(
                    id = UUID.randomUUID().toString(),
                    name = automation.name + " copy",
                    enabled = false,
                    createdAt = now,
                    updatedAt = now,
                )
            )
            _messages.send("Duplicated. The copy is turned off.")
        }
    }

    fun run(automation: Automation) {
        container.scope.launch { _messages.send(describeRun(container.runner.runManually(automation.id), automation.name)) }
    }

    fun addSamples() {
        container.scope.launch {
            container.automations.addAll(Samples.create(System.currentTimeMillis()))
            _messages.send("Added 3 sample automations")
        }
    }

    fun clearHistory() {
        container.scope.launch { container.history.clear() }
    }

    fun setHistoryLimit(limit: Int) {
        container.settings.update { it.copy(historyLimit = limit) }
        container.scope.launch { container.history.trim(limit) }
    }

    fun deleteVariable(name: String) = container.variables.remove(name)
    fun clearVariables() = container.variables.clear()

    fun updateSettings(transform: (com.androx.app.data.AppSettings) -> com.androx.app.data.AppSettings) {
        container.settings.update(transform)
    }
}

fun describeRun(record: ExecutionRecord?, fallbackName: String): String = when {
    record == null -> "“$fallbackName” no longer exists"
    record.status == ExecutionStatus.SUCCESS -> "“${record.automationName}” ran successfully"
    record.status == ExecutionStatus.SKIPPED -> "“${record.automationName}” skipped. ${record.message.orEmpty()}"
    else -> "“${record.automationName}” failed. ${record.message.orEmpty()}"
}
