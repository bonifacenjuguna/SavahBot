@file:OptIn(ExperimentalMaterial3Api::class)

package com.androx.app.ui.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.androx.app.R
import com.androx.app.model.EditorKind
import com.androx.app.model.Trigger
import com.androx.app.ui.MainViewModel
import com.androx.app.ui.components.AndroxMark
import com.androx.app.ui.components.NewAutomationSheet
import com.androx.app.ui.components.SectionHeader
import com.androx.app.ui.components.formatTimestamp
import com.androx.app.ui.history.HistoryCard

@Composable
fun HomeScreen(vm: MainViewModel, onCreate: (EditorKind) -> Unit, onOpenHistory: () -> Unit) {
    val automations by vm.automations.collectAsStateWithLifecycle()
    val history by vm.history.collectAsStateWithLifecycle()
    var showSheet by remember { mutableStateOf(false) }
    val scroll = TopAppBarDefaults.pinnedScrollBehavior()

    val enabled = automations.count { it.enabled }
    val now = System.currentTimeMillis()
    val next = automations
        .filter { it.enabled && it.trigger is Trigger.Schedule }
        .map { it to (it.trigger as Trigger.Schedule).nextRunMillis(now) }
        .minByOrNull { it.second }

    Scaffold(
        modifier = Modifier.nestedScroll(scroll.nestedScrollConnection),
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        topBar = {
            CenterAlignedTopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        AndroxMark(Modifier.width(30.dp).height(15.dp))
                        Spacer(Modifier.width(10.dp))
                        Text("Androx", style = MaterialTheme.typography.titleLarge)
                    }
                },
                scrollBehavior = scroll,
            )
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { showSheet = true },
                icon = { Icon(Icons.Filled.Add, contentDescription = null) },
                text = { Text("New automation") },
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                start = 16.dp, end = 16.dp, top = padding.calculateTopPadding() + 8.dp, bottom = padding.calculateBottomPadding() + 96.dp,
            ),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerHigh)) {
                    Column(Modifier.fillMaxWidth().padding(20.dp)) {
                        AndroxMark(Modifier.width(56.dp).height(27.dp))
                        Spacer(Modifier.height(16.dp))
                        Text("Automate your phone", style = MaterialTheme.typography.headlineMedium)
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "Triggers, conditions and actions that run on this device. Nothing leaves it.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Stat("Total", automations.size, Modifier.weight(1f))
                    Stat("Enabled", enabled, Modifier.weight(1f))
                    Stat("Disabled", automations.size - enabled, Modifier.weight(1f))
                }
            }
            if (automations.isEmpty()) {
                item {
                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow)) {
                        Column(Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("No automations yet", style = MaterialTheme.typography.titleMedium)
                            Text(
                                "Create one with the Builder, JavaScript or the visual workflow editor, or start from three ready-made samples.",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 4.dp)) {
                                Button(onClick = { showSheet = true }) { Text("Create") }
                                OutlinedButton(onClick = { vm.addSamples() }) { Text("Add samples") }
                            }
                        }
                    }
                }
            }
            if (next != null) {
                item {
                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow)) {
                        Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(painterResource(R.drawable.ic_schedule), contentDescription = null)
                            Column(Modifier.padding(start = 16.dp)) {
                                Text("Next scheduled run", style = MaterialTheme.typography.labelLarge)
                                Text(
                                    "${next.first.name} · ${formatTimestamp(next.second)}",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            }
            item {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                    SectionHeader("Recent activity")
                    if (history.isNotEmpty()) TextButton(onClick = onOpenHistory) { Text("See all") }
                }
            }
            if (history.isEmpty()) {
                item {
                    Text(
                        "Runs will appear here.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 4.dp),
                    )
                }
            } else {
                history.take(3).forEach { record ->
                    item(key = record.id) { HistoryCard(record) }
                }
            }
        }
    }

    if (showSheet) {
        NewAutomationSheet(
            onPick = { showSheet = false; onCreate(it) },
            onDismiss = { showSheet = false },
        )
    }
}

@Composable
private fun Stat(label: String, value: Int, modifier: Modifier = Modifier) {
    Card(modifier = modifier, colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow)) {
        Column(Modifier.padding(16.dp)) {
            Text(value.toString(), style = MaterialTheme.typography.headlineMedium)
            Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
