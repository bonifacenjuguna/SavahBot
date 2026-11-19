@file:OptIn(ExperimentalMaterial3Api::class)

package com.androx.app.ui.editor

import android.text.format.DateFormat
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import com.androx.app.model.Action
import com.androx.app.model.Automation
import com.androx.app.model.Comparison
import com.androx.app.model.Condition
import com.androx.app.model.Trigger
import com.androx.app.model.VariableMode
import com.androx.app.model.describeDays
import com.androx.app.model.formatClock
import com.androx.app.model.label
import com.androx.app.model.summary
import com.androx.app.ui.components.DropdownField
import com.androx.app.ui.theme.CodeTextStyle

private val dayLabels = listOf("M", "T", "W", "T", "F", "S", "S")
private val dayNames = listOf("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

@Composable
fun IntField(label: String, value: Int, range: IntRange, onValue: (Int) -> Unit, modifier: Modifier = Modifier) {
    var text by remember { mutableStateOf(value.toString()) }
    OutlinedTextField(
        value = text,
        onValueChange = { raw ->
            val digits = raw.filter { it.isDigit() }.take(4)
            text = digits
            digits.toIntOrNull()?.let { onValue(it.coerceIn(range)) }
        },
        label = { Text(label) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        modifier = modifier,
    )
}

// ---------------------------------------------------------------- Trigger

@Composable
fun TriggerEditor(trigger: Trigger, onChange: (Trigger) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        DropdownField(
            label = "Trigger",
            options = listOf("Manual", "Schedule"),
            selected = if (trigger is Trigger.Schedule) "Schedule" else "Manual",
            optionText = { it },
            onSelect = { choice ->
                val isSchedule = choice == "Schedule"
                if (isSchedule && trigger !is Trigger.Schedule) onChange(Trigger.Schedule())
                if (!isSchedule && trigger !is Trigger.Manual) onChange(Trigger.Manual)
            },
            modifier = Modifier.fillMaxWidth(),
        )
        when (trigger) {
            Trigger.Manual -> Text(
                "Runs only when you tap Run.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            is Trigger.Schedule -> ScheduleFields(trigger, onChange)
        }
    }
}

@Composable
private fun ScheduleFields(trigger: Trigger.Schedule, onChange: (Trigger) -> Unit) {
    var picking by remember { mutableStateOf(false) }
    OutlinedButton(onClick = { picking = true }, modifier = Modifier.fillMaxWidth()) {
        Text("Time: ${formatClock(trigger.hour, trigger.minute)}")
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        dayLabels.forEachIndexed { index, letter ->
            val day = index + 1
            val selected = trigger.days.isEmpty() || day in trigger.days
            Box(
                Modifier
                    .weight(1f)
                    .heightIn(min = 48.dp)
                    .semantics(mergeDescendants = true) {
                        role = Role.Checkbox
                        this.selected = trigger.days.isNotEmpty() && day in trigger.days
                        contentDescription = dayNames[index]
                    }
                    .clickable {
                        val current = trigger.days.ifEmpty { (1..7).toList() }
                        val next = if (day in current) current - day else current + day
                        // Selecting all seven (or none) both mean "every day".
                        onChange(trigger.copy(days = if (next.size == 7 || next.isEmpty()) emptyList() else next.sorted()))
                    },
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    Modifier
                        .size(36.dp)
                        .clip(CircleShape)
                        .background(
                            if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainerHighest
                        ),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        letter,
                        style = MaterialTheme.typography.labelLarge,
                        color = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
    Text(
        describeDays(trigger.days),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    if (picking) {
        val context = LocalContext.current
        val state = rememberTimePickerState(trigger.hour, trigger.minute, DateFormat.is24HourFormat(context))
        AlertDialog(
            onDismissRequest = { picking = false },
            confirmButton = {
                TextButton(onClick = {
                    picking = false
                    onChange(trigger.copy(hour = state.hour, minute = state.minute))
                }) { Text("OK") }
            },
            dismissButton = { TextButton(onClick = { picking = false }) { Text("Cancel") } },
            text = { TimePicker(state = state) },
        )
    }
}

// ---------------------------------------------------------------- Condition

@Composable
fun ConditionEditor(condition: Condition, onChange: (Condition) -> Unit) {
    val kinds = listOf("Battery level", "Charging state", "Variable")
    val current = when (condition) {
        is Condition.BatteryLevel -> kinds[0]
        is Condition.Charging -> kinds[1]
        is Condition.Variable -> kinds[2]
    }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        DropdownField(
            label = "Check",
            options = kinds,
            selected = current,
            optionText = { it },
            onSelect = { choice ->
                if (choice != current) {
                    onChange(
                        when (choice) {
                            kinds[0] -> Condition.BatteryLevel()
                            kinds[1] -> Condition.Charging()
                            else -> Condition.Variable()
                        }
                    )
                }
            },
            modifier = Modifier.fillMaxWidth(),
        )
        when (condition) {
            is Condition.BatteryLevel -> Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                DropdownField(
                    label = "Is",
                    options = Comparison.values().toList(),
                    selected = condition.op,
                    optionText = { it.symbol },
                    onSelect = { onChange(condition.copy(op = it)) },
                    modifier = Modifier.weight(1f),
                )
                IntField("Percent", condition.percent, 0..100, { onChange(condition.copy(percent = it)) }, Modifier.weight(1f))
            }
            is Condition.Charging -> DropdownField(
                label = "Device is",
                options = listOf(true, false),
                selected = condition.charging,
                optionText = { if (it) "Charging" else "Not charging" },
                onSelect = { onChange(condition.copy(charging = it)) },
                modifier = Modifier.fillMaxWidth(),
            )
            is Condition.Variable -> Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(
                    value = condition.name,
                    onValueChange = { onChange(condition.copy(name = it.trim())) },
                    label = { Text("Variable name") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    DropdownField(
                        label = "Is",
                        options = Comparison.values().toList(),
                        selected = condition.op,
                        optionText = { it.symbol },
                        onSelect = { onChange(condition.copy(op = it)) },
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = condition.value,
                        onValueChange = { onChange(condition.copy(value = it)) },
                        label = { Text("Value") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                }
                Text(
                    "Numbers are compared as numbers; anything else as text. An unset variable counts as empty.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

// ---------------------------------------------------------------- Action

private val actionKinds = listOf("Show notification", "Set variable", "Run automation", "Write to log", "Run JavaScript")

fun Action.kindIndex(): Int = when (this) {
    is Action.ShowNotification -> 0
    is Action.SetVariable -> 1
    is Action.RunAutomation -> 2
    is Action.WriteLog -> 3
    is Action.RunScript -> 4
}

fun newActionOfKind(index: Int): Action = when (index) {
    0 -> Action.ShowNotification("Androx", "")
    1 -> Action.SetVariable()
    2 -> Action.RunAutomation()
    3 -> Action.WriteLog()
    else -> Action.RunScript()
}

val actionKindLabels: List<String> get() = actionKinds

@Composable
fun ActionEditor(
    action: Action,
    others: List<Automation>,
    onChange: (Action) -> Unit,
    onOpenScript: (() -> Unit)? = null,
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        DropdownField(
            label = "Action",
            options = actionKinds,
            selected = actionKinds[action.kindIndex()],
            optionText = { it },
            onSelect = { choice ->
                val index = actionKinds.indexOf(choice)
                if (index != action.kindIndex()) onChange(newActionOfKind(index))
            },
            modifier = Modifier.fillMaxWidth(),
        )
        when (action) {
            is Action.ShowNotification -> {
                OutlinedTextField(
                    value = action.title,
                    onValueChange = { onChange(action.copy(title = it)) },
                    label = { Text("Title") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = action.message,
                    onValueChange = { onChange(action.copy(message = it)) },
                    label = { Text("Message") },
                    supportingText = { Text("Insert values with {{battery}}, {{time}}, {{date}} or {{variableName}}.") },
                    minLines = 2,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            is Action.SetVariable -> {
                OutlinedTextField(
                    value = action.name,
                    onValueChange = { onChange(action.copy(name = it.trim())) },
                    label = { Text("Variable name") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                DropdownField(
                    label = "Operation",
                    options = VariableMode.values().toList(),
                    selected = action.mode,
                    optionText = { if (it == VariableMode.SET) "Set to" else "Add (number)" },
                    onSelect = { onChange(action.copy(mode = it)) },
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = action.value,
                    onValueChange = { onChange(action.copy(value = it)) },
                    label = { Text("Value") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            is Action.RunAutomation -> {
                if (others.isEmpty()) {
                    Text(
                        "Save another automation first, then pick it here.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    DropdownField(
                        label = "Automation",
                        options = others,
                        selected = others.firstOrNull { it.id == action.automationId },
                        placeholder = if (action.automationId.isBlank()) "Choose…" else action.automationName,
                        optionText = { it.name },
                        onSelect = { onChange(Action.RunAutomation(it.id, it.name)) },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Text(
                        "Runs its condition and actions right away, even if it is turned off.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            is Action.WriteLog -> OutlinedTextField(
                value = action.message,
                onValueChange = { onChange(action.copy(message = it)) },
                label = { Text("Log message") },
                supportingText = { Text("Appears in this run's details in History.") },
                modifier = Modifier.fillMaxWidth(),
            )
            is Action.RunScript -> {
                if (onOpenScript != null) {
                    Text(
                        action.summary().ifBlank { "(empty script)" },
                        style = CodeTextStyle,
                        maxLines = 2,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    OutlinedButton(onClick = onOpenScript) { Text("Open in Script editor") }
                } else {
                    OutlinedTextField(
                        value = action.source,
                        onValueChange = { onChange(action.copy(source = it)) },
                        label = { Text("Script") },
                        textStyle = CodeTextStyle,
                        minLines = 6,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }
    }
}
