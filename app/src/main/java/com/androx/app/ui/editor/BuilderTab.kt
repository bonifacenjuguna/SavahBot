@file:OptIn(ExperimentalMaterial3Api::class)

package com.androx.app.ui.editor

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.androx.app.model.Condition
import com.androx.app.model.WorkflowCompiler
import com.androx.app.model.label

@Composable
private fun SectionCard(
    title: String,
    modifier: Modifier = Modifier,
    trailing: @Composable () -> Unit = {},
    content: @Composable () -> Unit,
) {
    Card(modifier = modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                trailing()
            }
            content()
        }
    }
}

/** Trigger → optional condition → actions, with no code. */
@Composable
fun BuilderTab(vm: EditorViewModel, onOpenScript: () -> Unit) {
    val orphans = remember(vm.graph) { WorkflowCompiler.compile(vm.graph).orphanIds.size }
    var addMenu by remember { mutableStateOf(false) }
    val others = vm.otherAutomations

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 48.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            SectionCard("When") {
                TriggerEditor(vm.trigger) { vm.changeTrigger(it) }
            }
        }
        item {
            val condition = vm.condition
            SectionCard(
                title = "Only if",
                trailing = {
                    Switch(
                        checked = condition != null,
                        onCheckedChange = { on -> vm.changeCondition(if (on) Condition.BatteryLevel() else null) },
                    )
                },
            ) {
                if (condition == null) {
                    Text(
                        "No condition: the actions always run.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    ConditionEditor(condition) { vm.changeCondition(it) }
                }
            }
        }
        itemsIndexed(vm.actions) { index, action ->
            SectionCard(
                title = "Then · ${action.label()}",
                trailing = {
                    IconButton(onClick = { vm.moveAction(index, -1) }, enabled = index > 0) {
                        Icon(Icons.Filled.KeyboardArrowUp, contentDescription = "Move up")
                    }
                    IconButton(onClick = { vm.moveAction(index, 1) }, enabled = index < vm.actions.lastIndex) {
                        Icon(Icons.Filled.KeyboardArrowDown, contentDescription = "Move down")
                    }
                    IconButton(onClick = { vm.removeAction(index) }) {
                        Icon(Icons.Filled.Delete, contentDescription = "Remove action")
                    }
                },
            ) {
                ActionEditor(
                    action = action,
                    others = others,
                    onChange = { vm.updateAction(index, it) },
                    onOpenScript = { onOpenScript() },
                )
            }
        }
        item {
            Box {
                OutlinedButton(onClick = { addMenu = true }) {
                    Icon(Icons.Filled.Add, contentDescription = null)
                    Text("Add action", modifier = Modifier.padding(start = 8.dp))
                }
                DropdownMenu(expanded = addMenu, onDismissRequest = { addMenu = false }) {
                    actionKindLabels.forEachIndexed { index, label ->
                        DropdownMenuItem(
                            text = { Text(label) },
                            onClick = { addMenu = false; vm.addAction(newActionOfKind(index)) },
                        )
                    }
                }
            }
        }
        if (orphans > 0) {
            item {
                Text(
                    "The Workflow tab also holds $orphans unconnected node${if (orphans == 1) "" else "s"}. They don't run, and they are kept.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}
