package com.androx.app.engine

import com.androx.app.model.Action
import com.androx.app.model.Automation
import com.androx.app.model.Condition
import com.androx.app.model.ExecutionRecord
import com.androx.app.model.ExecutionStatus
import com.androx.app.model.RunSource
import com.androx.app.model.Templates
import com.androx.app.model.VariableMode
import com.androx.app.model.label
import com.androx.app.model.summary
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.UUID

/** Thrown when Android (or the user's configuration) prevents an action. Always becomes a failed run. */
class ActionException(message: String) : Exception(message)

/** Everything the engine needs from the device. Implemented on Android by AndroidDeviceBridge. */
interface DeviceBridge {
    fun batteryLevel(): Int
    fun isCharging(): Boolean

    /** Must throw [ActionException] if the notification could not be posted. */
    fun showNotification(title: String, message: String)
}

interface VariableStore {
    fun get(name: String): String?
    fun set(name: String, value: String)
    fun remove(name: String)
}

/**
 * Runs an automation: checks its condition, then executes its actions in order.
 * Pure Kotlin (no Android types) so it can be unit-tested on the JVM.
 */
class ExecutionEngine(
    private val device: DeviceBridge,
    private val variables: VariableStore,
    private val findAutomation: (String) -> Automation?,
    private val scripts: ScriptRunner = RhinoScriptRunner(),
    private val clock: () -> Long = { System.currentTimeMillis() },
) {
    companion object {
        const val MAX_DEPTH = 4
    }

    suspend fun execute(automation: Automation, source: RunSource): ExecutionRecord {
        val started = clock()
        val logs = mutableListOf<String>()
        var status = ExecutionStatus.SUCCESS
        var message: String? = null
        try {
            val skipped = runInternal(automation, logs, emptyList())
            if (skipped != null) {
                status = ExecutionStatus.SKIPPED
                message = skipped
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: ActionException) {
            status = ExecutionStatus.FAILED
            message = e.message
        } catch (e: Exception) {
            status = ExecutionStatus.FAILED
            message = e.message ?: e.javaClass.simpleName
        }
        return ExecutionRecord(
            id = UUID.randomUUID().toString(),
            automationId = automation.id,
            automationName = automation.name,
            startedAt = started,
            durationMs = (clock() - started).coerceAtLeast(0),
            status = status,
            source = source,
            message = message,
            logs = logs,
        )
    }

    /** Returns a reason if the run was skipped, null if it ran. Throws on failure. */
    private suspend fun runInternal(a: Automation, logs: MutableList<String>, stack: List<String>): String? {
        if (a.id in stack) throw ActionException("\"${a.name}\" would call itself.")
        if (stack.size >= MAX_DEPTH) throw ActionException("Nested automations are limited to $MAX_DEPTH levels.")

        val condition = a.condition
        if (condition != null) {
            val (passed, why) = evaluate(condition)
            logs += "Condition: $why"
            if (!passed) return "Condition not met: $why"
        }
        val nextStack = stack + a.id
        for ((index, action) in a.actions.withIndex()) {
            currentCoroutineContext().ensureActive()
            logs += "Action ${index + 1}: ${action.label()}"
            perform(action, a, logs, nextStack)
        }
        return null
    }

    private fun evaluate(condition: Condition): Pair<Boolean, String> = when (condition) {
        is Condition.BatteryLevel -> {
            val level = device.batteryLevel()
            condition.op.test(level.compareTo(condition.percent)) to
                "battery is $level% (needs ${condition.op.symbol} ${condition.percent}%)"
        }
        is Condition.Charging -> {
            val now = device.isCharging()
            (now == condition.charging) to
                (if (now) "device is charging" else "device is not charging") +
                " (needs ${if (condition.charging) "charging" else "not charging"})"
        }
        is Condition.Variable -> {
            val current = variables.get(condition.name)
            val left = current ?: ""
            val shown = current ?: "not set"
            val rhs = condition.value
            condition.op.test(Templates.compare(left, rhs)) to
                "${condition.name} is $shown (needs ${condition.op.symbol} $rhs)"
        }
    }

    private suspend fun perform(action: Action, owner: Automation, logs: MutableList<String>, stack: List<String>) {
        val render = { text: String -> Templates.render(text, resolver(owner)) }
        when (action) {
            is Action.ShowNotification -> {
                device.showNotification(render(action.title), render(action.message))
            }
            is Action.SetVariable -> {
                val name = action.name.trim()
                if (name.isEmpty()) throw ActionException("Variable name is empty.")
                val value = render(action.value)
                when (action.mode) {
                    VariableMode.SET -> variables.set(name, value)
                    VariableMode.ADD -> {
                        val delta = value.trim().toDoubleOrNull()
                            ?: throw ActionException("\"$value\" is not a number, so it can't be added to $name.")
                        val currentText = variables.get(name)
                        val current = if (currentText == null) 0.0 else currentText.trim().toDoubleOrNull()
                            ?: throw ActionException("Variable $name holds \"$currentText\", which is not a number.")
                        variables.set(name, Templates.formatNumber(current + delta))
                    }
                }
                logs += "  $name = ${variables.get(name)}"
            }
            is Action.RunAutomation -> {
                val target = findAutomation(action.automationId)
                    ?: throw ActionException(
                        "Automation \"${action.automationName.ifBlank { action.automationId }}\" no longer exists."
                    )
                val skipped = runInternal(target, logs, stack)
                logs += if (skipped == null) "  ran \"${target.name}\"" else "  skipped \"${target.name}\": $skipped"
            }
            is Action.WriteLog -> logs += "  " + render(action.message)
            is Action.RunScript -> runScript(action.source, logs)
        }
    }

    private fun resolver(owner: Automation): (String) -> String? = { key ->
        when (key) {
            "battery" -> device.batteryLevel().toString()
            "charging" -> device.isCharging().toString()
            "time" -> formatNow("HH:mm")
            "date" -> formatNow("yyyy-MM-dd")
            "automation" -> owner.name
            else -> variables.get(key)
        }
    }

    private fun formatNow(pattern: String): String =
        Instant.ofEpochMilli(clock()).atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern(pattern))

    private suspend fun runScript(source: String, logs: MutableList<String>) {
        val host = object : ScriptHost {
            override fun log(message: String) {
                synchronized(logs) { logs += "  [script] $message" }
            }

            override fun notify(title: String, message: String) = device.showNotification(title, message)
            override fun getVar(name: String): String? = variables.get(name)
            override fun setVar(name: String, value: String) = variables.set(name, value)
            override fun deleteVar(name: String) = variables.remove(name)
            override fun batteryLevel(): Int = device.batteryLevel()
            override fun isCharging(): Boolean = device.isCharging()
            override fun nowMillis(): Long = clock()
        }
        val result = withContext(Dispatchers.Default) { scripts.run(source, host) }
        if (result is ScriptResult.Failure) throw ActionException(result.message)
    }
}
