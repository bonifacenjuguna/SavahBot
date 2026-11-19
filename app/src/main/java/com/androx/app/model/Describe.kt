package com.androx.app.model

import java.util.Locale

private val DAY_NAMES = listOf("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

fun formatClock(hour: Int, minute: Int): String = String.format(Locale.US, "%02d:%02d", hour, minute)

fun describeDays(days: List<Int>): String {
    val set = days.filter { it in 1..7 }.toSortedSet()
    return when {
        set.isEmpty() || set.size == 7 -> "Every day"
        set == setOf(1, 2, 3, 4, 5) -> "Weekdays"
        set == setOf(6, 7) -> "Weekends"
        else -> set.joinToString(", ") { DAY_NAMES[it - 1] }
    }
}

fun Trigger.summary(): String = when (this) {
    Trigger.Manual -> "Manual"
    is Trigger.Schedule -> "${formatClock(hour, minute)} · ${describeDays(days)}"
}

fun Condition.summary(): String = when (this) {
    is Condition.BatteryLevel -> "Battery ${op.symbol} $percent%"
    is Condition.Charging -> if (charging) "Device is charging" else "Device is not charging"
    is Condition.Variable -> "$name ${op.symbol} $value"
}

fun Action.label(): String = when (this) {
    is Action.ShowNotification -> "Show notification"
    is Action.SetVariable -> "Set variable"
    is Action.RunAutomation -> "Run automation"
    is Action.WriteLog -> "Write to log"
    is Action.RunScript -> "Run JavaScript"
}

fun Action.summary(): String = when (this) {
    is Action.ShowNotification -> title.ifBlank { "Androx" } + if (message.isNotBlank()) " – $message" else ""
    is Action.SetVariable -> if (mode == VariableMode.SET) "$name = $value" else "$name += $value"
    is Action.RunAutomation -> automationName.ifBlank { automationId.take(8) }
    is Action.WriteLog -> message
    is Action.RunScript -> source.lineSequence().firstOrNull { it.isNotBlank() }?.trim().orEmpty()
}

fun Automation.subtitle(): String {
    val parts = mutableListOf(trigger.summary())
    condition?.let { parts += "if ${it.summary()}" }
    parts += when (actions.size) {
        0 -> "no actions"
        1 -> "1 action"
        else -> "${actions.size} actions"
    }
    return parts.joinToString(" · ")
}
