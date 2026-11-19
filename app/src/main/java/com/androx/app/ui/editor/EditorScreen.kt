@file:OptIn(ExperimentalMaterial3Api::class)

package com.androx.app.ui.editor

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import com.androx.app.R
import com.androx.app.model.EditorKind
import com.androx.app.ui.components.EmptyState
import com.androx.app.ui.components.kindIcon
import com.androx.app.ui.components.kindLabel
import com.androx.app.ui.components.rememberNotificationGate
import kotlinx.coroutines.launch

@Composable
fun EditorScreen(vm: EditorViewModel, onClose: () -> Unit) {
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val gate = rememberNotificationGate()
    var confirmDiscard by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { vm.messages.collect { snackbar.showSnackbar(it) } }
    BackHandler(enabled = vm.dirty) { confirmDiscard = true }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text(if (vm.isNew) "New automation" else "Edit automation") },
                navigationIcon = {
                    IconButton(onClick = { if (vm.dirty) confirmDiscard = true else onClose() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(
                        enabled = !vm.busy && !vm.loading && !vm.notFound,
                        onClick = { gate.ensure(vm.needsNotifications()) { vm.saveAndRun() } },
                    ) { Icon(Icons.Filled.PlayArrow, contentDescription = "Save and run now") }
                    TextButton(
                        enabled = !vm.busy && !vm.loading && !vm.notFound,
                        onClick = { vm.save { scope.launch { onClose() } } },
                    ) { Text("Save") }
                },
            )
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding).imePadding()) {
            when {
                vm.loading -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                vm.notFound -> EmptyState(
                    icon = painterResource(R.drawable.ic_bolt),
                    title = "This automation no longer exists",
                    message = "It may have been deleted.",
                    modifier = Modifier.align(Alignment.Center),
                ) { Button(onClick = onClose) { Text("Close") } }
                else -> Column(Modifier.fillMaxSize()) {
                    Row(
                        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        OutlinedTextField(
                            value = vm.name,
                            onValueChange = { vm.changeName(it) },
                            label = { Text("Name") },
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        Column(Modifier.padding(start = 12.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                            Switch(checked = vm.enabled, onCheckedChange = { vm.changeEnabled(it) })
                            Text(
                                if (vm.enabled) "On" else "Off",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    TabRow(selectedTabIndex = vm.tab.ordinal) {
                        EditorKind.values().forEach { kind ->
                            Tab(
                                selected = vm.tab == kind,
                                onClick = { vm.selectTab(kind) },
                                text = { Text(kindLabel(kind)) },
                                icon = { Icon(kindIcon(kind), contentDescription = null) },
                            )
                        }
                    }
                    AnimatedContent(
                        targetState = vm.tab,
                        modifier = Modifier.weight(1f),
                        transitionSpec = { fadeIn(tween(180)) togetherWith fadeOut(tween(120)) },
                        label = "editor-tab",
                    ) { kind ->
                        when (kind) {
                            EditorKind.BUILDER -> BuilderTab(vm, onOpenScript = { vm.selectTab(EditorKind.SCRIPT) })
                            EditorKind.SCRIPT -> ScriptTab(vm)
                            EditorKind.WORKFLOW -> WorkflowTab(vm) { message -> scope.launch { snackbar.showSnackbar(message) } }
                        }
                    }
                }
            }
        }
    }

    if (confirmDiscard) {
        AlertDialog(
            onDismissRequest = { confirmDiscard = false },
            title = { Text("Discard changes?") },
            text = { Text("Your edits to this automation haven't been saved.") },
            confirmButton = { TextButton(onClick = { confirmDiscard = false; onClose() }) { Text("Discard") } },
            dismissButton = { TextButton(onClick = { confirmDiscard = false }) { Text("Keep editing") } },
        )
    }
}
