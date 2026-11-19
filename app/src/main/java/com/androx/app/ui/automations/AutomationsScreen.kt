@file:OptIn(ExperimentalMaterial3Api::class)

package com.androx.app.ui.automations

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LargeTopAppBar
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.androx.app.R
import com.androx.app.model.Automation
import com.androx.app.model.EditorKind
import com.androx.app.model.subtitle
import com.androx.app.ui.MainViewModel
import com.androx.app.ui.components.EmptyState
import com.androx.app.ui.components.IconBadge
import com.androx.app.ui.components.NewAutomationSheet
import com.androx.app.ui.components.kindIcon
import com.androx.app.ui.components.kindLabel
import com.androx.app.ui.components.mayNotify
import com.androx.app.ui.components.rememberNotificationGate

private enum class Filter(val label: String) { ALL("All"), ON("On"), OFF("Off") }

@Composable
fun AutomationsScreen(vm: MainViewModel, onCreate: (EditorKind) -> Unit, onEdit: (Automation) -> Unit) {
    val automations by vm.automations.collectAsStateWithLifecycle()
    var filter by rememberSaveable { mutableStateOf(Filter.ALL) }
    var showSheet by remember { mutableStateOf(false) }
    var toDelete by remember { mutableStateOf<Automation?>(null) }
    val gate = rememberNotificationGate()
    val scroll = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()

    val shown = when (filter) {
        Filter.ALL -> automations
        Filter.ON -> automations.filter { it.enabled }
        Filter.OFF -> automations.filter { !it.enabled }
    }

    Scaffold(
        modifier = Modifier.nestedScroll(scroll.nestedScrollConnection),
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        topBar = { LargeTopAppBar(title = { Text("Automations") }, scrollBehavior = scroll) },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { showSheet = true },
                icon = { Icon(Icons.Filled.Add, contentDescription = null) },
                text = { Text("New") },
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                start = 16.dp, end = 16.dp, top = padding.calculateTopPadding() + 4.dp, bottom = padding.calculateBottomPadding() + 96.dp,
            ),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (automations.isNotEmpty()) {
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Filter.values().forEach { f ->
                            FilterChip(selected = filter == f, onClick = { filter = f }, label = { Text(f.label) })
                        }
                    }
                }
            }
            if (shown.isEmpty()) {
                item {
                    EmptyState(
                        icon = painterResource(R.drawable.ic_bolt),
                        title = if (automations.isEmpty()) "Nothing automated yet" else "No automations in this filter",
                        message = if (automations.isEmpty()) "Tap New to build your first one."
                        else "Switch the filter to see the others.",
                    )
                }
            } else {
                items(shown, key = { it.id }) { automation ->
                    AutomationCard(
                        automation = automation,
                        onEdit = { onEdit(automation) },
                        onToggle = { vm.setEnabled(automation.id, it) },
                        onRun = { gate.ensure(automation.mayNotify()) { vm.run(automation) } },
                        onDuplicate = { vm.duplicate(automation) },
                        onDelete = { toDelete = automation },
                        modifier = Modifier.animateItem(),
                    )
                }
            }
        }
    }

    if (showSheet) {
        NewAutomationSheet(onPick = { showSheet = false; onCreate(it) }, onDismiss = { showSheet = false })
    }
    toDelete?.let { target ->
        AlertDialog(
            onDismissRequest = { toDelete = null },
            title = { Text("Delete “${target.name}”?") },
            text = { Text("This removes the automation and its schedule. Past runs stay in History.") },
            confirmButton = { TextButton(onClick = { vm.delete(target); toDelete = null }) { Text("Delete") } },
            dismissButton = { TextButton(onClick = { toDelete = null }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun AutomationCard(
    automation: Automation,
    onEdit: () -> Unit,
    onToggle: (Boolean) -> Unit,
    onRun: () -> Unit,
    onDuplicate: () -> Unit,
    onDelete: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var menu by remember { mutableStateOf(false) }
    Card(
        onClick = onEdit,
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
    ) {
        Column(Modifier.padding(start = 16.dp, end = 8.dp, top = 16.dp, bottom = 8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconBadge(kindIcon(automation.editor))
                Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
                    Text(automation.name, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(
                        automation.subtitle(),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Switch(
                    checked = automation.enabled,
                    onCheckedChange = onToggle,
                    modifier = Modifier
                        .padding(end = 8.dp)
                        .semantics { contentDescription = if (automation.enabled) "Disable ${automation.name}" else "Enable ${automation.name}" },
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    kindLabel(automation.editor) + if (automation.enabled) "" else " · Off",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f).padding(start = 52.dp),
                )
                FilledTonalButton(onClick = onRun) {
                    Icon(Icons.Filled.PlayArrow, contentDescription = null)
                    Text("Run")
                }
                IconButton(onClick = { menu = true }) {
                    Icon(Icons.Filled.MoreVert, contentDescription = "More options for ${automation.name}")
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        DropdownMenuItem(text = { Text("Edit") }, onClick = { menu = false; onEdit() })
                        DropdownMenuItem(text = { Text("Duplicate") }, onClick = { menu = false; onDuplicate() })
                        DropdownMenuItem(text = { Text("Delete") }, onClick = { menu = false; onDelete() })
                    }
                }
            }
        }
    }
}
