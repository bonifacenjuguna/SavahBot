package com.androx.app.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.time.Instant
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime

/** Which editor an automation was last saved from. The data model itself is shared by all three. */
enum class EditorKind { BUILDER, SCRIPT, WORKFLOW }

enum class Comparison(val symbol: String) {
    LT("<"),
    LTE("≤"),
    EQ("="),
    NEQ("≠"),
    GTE("≥"),
    GT(">");

    /** [cmp] is the result of compareTo(left, right). */
    fun test(cmp: Int): Boolean = when (this) {
        LT -> cmp < 0
        LTE -> cmp <= 0
        EQ -> cmp == 0
        NEQ -> cmp != 0
        GTE -> cmp >= 0
        GT -> cmp > 0
    }
}

enum class VariableMode { SET, ADD }

/** What starts an automation. */
@Serializable
sealed interface Trigger {
    @Serializable
    @SerialName("manual")
    data object Manual : Trigger

    /** Runs at [hour]:[minute]. [days] uses ISO numbering (1 = Monday … 7 = Sunday); empty means every day. */
    @Serializable
    @SerialName("schedule")
    data class Schedule(
        val hour: Int = 8,
        val minute: Int = 0,
        val days: List<Int> = emptyList(),
    ) : Trigger {
        fun nextRunMillis(afterMillis: Long, zone: ZoneId = ZoneId.systemDefault()): Long {
            val startDate = Instant.ofEpochMilli(afterMillis).atZone(zone).toLocalDate()
            val time = LocalTime.of(hour.coerceIn(0, 23), minute.coerceIn(0, 59))
            for (offset in 0L..7L) {
                val date = startDate.plusDays(offset)
                if (days.isNotEmpty() && date.dayOfWeek.value !in days) continue
                val candidate = ZonedDateTime.of(date, time, zone).toInstant().toEpochMilli()
                if (candidate > afterMillis) return candidate
            }
            return afterMillis + 24L * 60 * 60 * 1000
        }
    }
}

/** An optional guard evaluated after the trigger fires. */
@Serializable
sealed interface Condition {
    @Serializable
    @SerialName("battery")
    data class BatteryLevel(val op: Comparison = Comparison.LT, val percent: Int = 20) : Condition

    @Serializable
    @SerialName("charging")
    data class Charging(val charging: Boolean = true) : Condition

    @Serializable
    @SerialName("variable")
    data class Variable(
        val name: String = "",
        val op: Comparison = Comparison.EQ,
        val value: String = "",
    ) : Condition
}

const val DEFAULT_SCRIPT = """// Androx script. The only things you can use are the `androx` API and plain JavaScript.
const runs = Number(androx.getVar("runs") || 0) + 1;
androx.setVar("runs", runs);
androx.notify("Androx script", "Run #" + runs + " · battery " + androx.battery() + "%");
"""

/** One step. Actions run in order; the first failure stops the run. */
@Serializable
sealed interface Action {
    @Serializable
    @SerialName("notify")
    data class ShowNotification(val title: String = "Androx", val message: String = "") : Action

    @Serializable
    @SerialName("set_variable")
    data class SetVariable(
        val name: String = "",
        val value: String = "",
        val mode: VariableMode = VariableMode.SET,
    ) : Action

    @Serializable
    @SerialName("run_automation")
    data class RunAutomation(val automationId: String = "", val automationName: String = "") : Action

    @Serializable
    @SerialName("log")
    data class WriteLog(val message: String = "") : Action

    @Serializable
    @SerialName("script")
    data class RunScript(val source: String = DEFAULT_SCRIPT) : Action
}

/**
 * The single representation every editor reads and writes: Trigger → optional Condition → Actions.
 * [graph] only carries the visual layout (and any nodes the user left unconnected) so nothing is lost
 * when switching between the Builder, Script and Workflow editors.
 */
@Serializable
data class Automation(
    val id: String,
    val name: String,
    val enabled: Boolean = true,
    val trigger: Trigger = Trigger.Manual,
    val condition: Condition? = null,
    val actions: List<Action> = emptyList(),
    val editor: EditorKind = EditorKind.BUILDER,
    val graph: WorkflowGraph? = null,
    val createdAt: Long = 0L,
    val updatedAt: Long = 0L,
)

enum class ExecutionStatus { SUCCESS, FAILED, SKIPPED }
enum class RunSource { MANUAL, SCHEDULE }

@Serializable
data class ExecutionRecord(
    val id: String,
    val automationId: String,
    val automationName: String,
    val startedAt: Long,
    val durationMs: Long,
    val status: ExecutionStatus,
    val source: RunSource,
    val message: String? = null,
    val logs: List<String> = emptyList(),
)
