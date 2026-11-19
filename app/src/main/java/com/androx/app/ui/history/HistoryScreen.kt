@file:OptIn(ExperimentalMaterial3Api::class)

package com.androx.app.ui.history

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LargeTopAppBar
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.rememberVectorPainter
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.androx.app.R
import com.androx.app.model.ExecutionRecord
import com.androx.app.model.ExecutionStatus
import com.androx.app.model.RunSource
import com.androx.app.ui.MainViewModel
import com.androx.app.ui.components.EmptyState
import com.androx.app.ui.components.formatTimestamp

@Composable
fun HistoryScreen(vm: MainViewModel) {
    val history by vm.history.collectAsStateWithLifecycle()
    var onlyProblems by rememberSaveable { mutableStateOf(false) }
    var confirmClear by remember { mutableStateOf(false) }
    val scroll = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()
    val shown = if (onlyProblems) history.filter { it.status == ExecutionStatus.FAILED } else history

    Scaffold(
        modifier = Modifier.nestedScroll(scroll.nestedScrollConnection),
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        topBar = {
            LargeTopAppBar(
                title = { Text("History") },
                actions = {
                    if (history.isNotEmpty()) {
                        IconButton(onClick = { confirmClear = true }) {
                            Icon(Icons.Filled.Delete, contentDescription = "Clear history")
                        }
                    }
                },
                scrollBehavior = scroll,
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                start = 16.dp, end = 16.dp, top = padding.calculateTopPadding() + 4.dp, bottom = padding.calculateBottomPadding() + 24.dp,
            ),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (history.isNotEmpty()) {
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterChip(selected = !onlyProblems, onClick = { onlyProblems = false }, label = { Text("All runs") })
                        FilterChip(selected = onlyProblems, onClick = { onlyProblems = true }, label = { Text("Failed") })
                    }
                }
            }
            if (shown.isEmpty()) {
                item {
                    EmptyState(
                        icon = painterResource(R.drawable.ic_history),
                        title = if (history.isEmpty()) "No runs yet" else "No failed runs",
                        message = if (history.isEmpty()) "When an automation runs, the result shows up here."
                        else "Everything that ran recently finished without errors.",
                    )
                }
            } else {
                items(shown, key = { it.id }) { record ->
                    HistoryCard(record, Modifier.animateItem())
                }
            }
        }
    }

    if (confirmClear) {
        AlertDialog(
            onDismissRequest = { confirmClear = false },
            title = { Text("Clear history?") },
            text = { Text("All ${history.size} records will be removed. Your automations are not affected.") },
            confirmButton = {
                TextButton(onClick = { vm.clearHistory(); confirmClear = false }) { Text("Clear") }
            },
            dismissButton = { TextButton(onClick = { confirmClear = false }) { Text("Cancel") } },
        )
    }
}

@Composable
fun HistoryCard(record: ExecutionRecord, modifier: Modifier = Modifier) {
    var expanded by rememberSaveable(record.id) { mutableStateOf(false) }
    val scheme = MaterialTheme.colorScheme
    val (container, onContainer, icon) = when (record.status) {
        ExecutionStatus.SUCCESS -> Triple(scheme.secondaryContainer, scheme.onSecondaryContainer, Icons.Filled.Check)
        ExecutionStatus.FAILED -> Triple(scheme.errorContainer, scheme.onErrorContainer, Icons.Filled.Warning)
        ExecutionStatus.SKIPPED -> Triple(scheme.surfaceVariant, scheme.onSurfaceVariant, Icons.Filled.Info)
    }
    val statusText = when (record.status) {
        ExecutionStatus.SUCCESS -> "Succeeded"
        ExecutionStatus.FAILED -> "Failed"
        ExecutionStatus.SKIPPED -> "Skipped"
    }
    val sourceText = if (record.source == RunSource.MANUAL) "Manual" else "Scheduled"

    Card(
        onClick = { expanded = !expanded },
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = scheme.surfaceContainerLow),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                StatusDot(icon, container, onContainer)
                Column(Modifier.weight(1f).padding(start = 12.dp)) {
                    Text(record.automationName, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(
                        "${formatTimestamp(record.startedAt)} · $sourceText · ${record.durationMs} ms",
                        style = MaterialTheme.typography.bodySmall,
                        color = scheme.onSurfaceVariant,
                    )
                }
                Text(statusText, style = MaterialTheme.typography.labelLarge, color = if (record.status == ExecutionStatus.FAILED) scheme.error else scheme.onSurfaceVariant)
            }
            val message = record.message
            if (!message.isNullOrBlank() && !expanded) {
                Text(
                    message,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (record.status == ExecutionStatus.FAILED) scheme.error else scheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
            AnimatedVisibility(visible = expanded) {
                Column(Modifier.padding(top = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (!message.isNullOrBlank()) {
                        Text(
                            message,
                            style = MaterialTheme.typography.bodyMedium,
                            color = if (record.status == ExecutionStatus.FAILED) scheme.error else scheme.onSurface,
                        )
                    }
                    if (record.logs.isNotEmpty()) {
                        Box(
                            Modifier
                                .fillMaxWidth()
                                .clip(MaterialTheme.shapes.small)
                                .background(scheme.surfaceContainerHighest)
                                .padding(12.dp)
                        ) {
                            Text(
                                record.logs.joinToString("\n"),
                                style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
                            )
                        }
                    } else if (message.isNullOrBlank()) {
                        Text("No details recorded.", style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}

@Composable
private fun StatusDot(icon: ImageVector, container: androidx.compose.ui.graphics.Color, content: androidx.compose.ui.graphics.Color) {
    Box(Modifier.size(36.dp).clip(CircleShape).background(container), contentAlignment = Alignment.Center) {
        Icon(rememberVectorPainter(icon), contentDescription = null, tint = content, modifier = Modifier.size(20.dp))
    }
}
