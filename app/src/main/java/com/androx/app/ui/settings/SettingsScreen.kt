@file:OptIn(ExperimentalMaterial3Api::class)

package com.androx.app.ui.settings

import android.os.Build
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LargeTopAppBar
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Switch
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.androx.app.data.ThemeMode
import com.androx.app.platform.Permissions
import com.androx.app.ui.MainViewModel
import com.androx.app.ui.components.SectionHeader
import com.androx.app.ui.components.rememberNotificationGate

private val transparent = ListItemDefaults.colors(containerColor = Color.Transparent)

@Composable
fun SettingsScreen(vm: MainViewModel) {
    val settings by vm.settings.collectAsStateWithLifecycle()
    val variables by vm.variables.collectAsStateWithLifecycle()
    val history by vm.history.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val gate = rememberNotificationGate()
    var status by remember { mutableStateOf(Permissions.status(context)) }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { status = Permissions.status(context) }
    var showVariables by remember { mutableStateOf(false) }
    var showLimit by remember { mutableStateOf(false) }
    var confirmClear by remember { mutableStateOf(false) }
    val scroll = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()

    Scaffold(
        modifier = Modifier.nestedScroll(scroll.nestedScrollConnection),
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        topBar = { LargeTopAppBar(title = { Text("Settings") }, scrollBehavior = scroll) },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(top = padding.calculateTopPadding(), bottom = padding.calculateBottomPadding() + 24.dp),
        ) {
            item { Header("Appearance") }
            item {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                    Text("Theme", style = MaterialTheme.typography.bodyLarge)
                    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(top = 8.dp)) {
                        val modes = listOf(ThemeMode.SYSTEM to "System", ThemeMode.LIGHT to "Light", ThemeMode.DARK to "Dark")
                        modes.forEachIndexed { index, (mode, label) ->
                            SegmentedButton(
                                selected = settings.themeMode == mode,
                                onClick = { vm.updateSettings { it.copy(themeMode = mode) } },
                                shape = SegmentedButtonDefaults.itemShape(index, modes.size),
                            ) { Text(label) }
                        }
                    }
                }
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                item {
                    ListItem(
                        headlineContent = { Text("Dynamic colour") },
                        supportingContent = { Text("Use colours from your wallpaper instead of the Androx monochrome palette.") },
                        trailingContent = {
                            Switch(checked = settings.dynamicColor, onCheckedChange = { c -> vm.updateSettings { it.copy(dynamicColor = c) } })
                        },
                        colors = transparent,
                    )
                }
            }
            item {
                ListItem(
                    headlineContent = { Text("Pure black dark theme") },
                    supportingContent = { Text("True black backgrounds in dark mode.") },
                    trailingContent = {
                        Switch(checked = settings.pureBlack, onCheckedChange = { c -> vm.updateSettings { it.copy(pureBlack = c) } })
                    },
                    colors = transparent,
                )
            }

            item { Header("History and data") }
            item {
                ListItem(
                    headlineContent = { Text("Keep last runs") },
                    supportingContent = { Text("${settings.historyLimit} records") },
                    colors = transparent,
                    modifier = Modifier.clickable { showLimit = true },
                )
            }
            item {
                ListItem(
                    headlineContent = { Text("Variables") },
                    supportingContent = { Text(if (variables.isEmpty()) "None stored yet" else "${variables.size} stored · shared by all automations") },
                    colors = transparent,
                    modifier = Modifier.clickable { showVariables = true },
                )
            }
            item {
                ListItem(
                    headlineContent = { Text("Clear history") },
                    supportingContent = { Text("${history.size} records") },
                    colors = transparent,
                    modifier = Modifier.clickable(enabled = history.isNotEmpty()) { confirmClear = true },
                )
            }

            item { Header("Permissions") }
            item {
                PermissionRow(
                    title = "Notifications",
                    why = "Needed by the “Show notification” action and by scripts that call androx.notify().",
                    granted = status.notificationsAllowed,
                    action = if (status.notificationsNeedRuntimePrompt && !gate.requestedOnce) "Allow" else "Open settings",
                    onAction = {
                        if (status.notificationsNeedRuntimePrompt && !gate.requestedOnce) gate.requestNow()
                        else Permissions.openNotificationSettings(context)
                    },
                )
            }
            item {
                PermissionRow(
                    title = "Exact alarms",
                    why = if (status.exactAlarmsApply) "Lets scheduled automations run at the exact minute. Without it Android may delay them by several minutes."
                    else "Not restricted on this version of Android.",
                    granted = status.exactAlarmsAllowed,
                    action = if (status.exactAlarmsApply) "Open settings" else null,
                    onAction = { Permissions.openExactAlarmSettings(context) },
                )
            }
            item {
                PermissionRow(
                    title = "Battery optimisation",
                    why = "Scheduled runs can be postponed while the phone is idle. Choosing “Unrestricted” for Androx reduces that, but Android still decides.",
                    granted = status.batteryUnrestricted,
                    grantedLabel = "Unrestricted",
                    deniedLabel = "Optimised",
                    action = "Open settings",
                    onAction = { Permissions.openBatterySettings(context) },
                )
            }

            item { Header("About") }
            item {
                ListItem(
                    headlineContent = { Text("Androx") },
                    supportingContent = {
                        Text("Version 0.0.0\nJavaScript runs in an embedded Rhino interpreter that can only reach the androx API.")
                    },
                    colors = transparent,
                )
            }
        }
    }

    if (showLimit) {
        AlertDialog(
            onDismissRequest = { showLimit = false },
            title = { Text("Keep last runs") },
            text = {
                Column {
                    listOf(50, 100, 250, 500).forEach { n ->
                        Row(
                            Modifier.fillMaxWidth().clickable { vm.setHistoryLimit(n); showLimit = false }.heightIn(min = 48.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(selected = settings.historyLimit == n, onClick = null)
                            Text("$n records", modifier = Modifier.padding(start = 12.dp))
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { showLimit = false }) { Text("Close") } },
        )
    }

    if (showVariables) {
        AlertDialog(
            onDismissRequest = { showVariables = false },
            title = { Text("Variables") },
            text = {
                if (variables.isEmpty()) {
                    Text("No variables yet. Actions and scripts create them with “Set variable” or androx.setVar().")
                } else {
                    LazyColumn(Modifier.heightIn(max = 360.dp)) {
                        items(variables.entries.toList(), key = { it.key }) { (name, value) ->
                            ListItem(
                                headlineContent = { Text(name) },
                                supportingContent = { Text(value.ifEmpty { "(empty)" }, fontFamily = FontFamily.Monospace) },
                                trailingContent = {
                                    IconButton(onClick = { vm.deleteVariable(name) }) {
                                        Icon(Icons.Filled.Close, contentDescription = "Delete $name")
                                    }
                                },
                                colors = transparent,
                            )
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { showVariables = false }) { Text("Close") } },
            dismissButton = {
                if (variables.isNotEmpty()) TextButton(onClick = { vm.clearVariables() }) { Text("Clear all") }
            },
        )
    }

    if (confirmClear) {
        AlertDialog(
            onDismissRequest = { confirmClear = false },
            title = { Text("Clear history?") },
            text = { Text("All ${history.size} records will be removed.") },
            confirmButton = { TextButton(onClick = { vm.clearHistory(); confirmClear = false }) { Text("Clear") } },
            dismissButton = { TextButton(onClick = { confirmClear = false }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun Header(text: String) {
    Column {
        HorizontalDivider(Modifier.padding(top = 8.dp))
        SectionHeader(text, Modifier.padding(start = 12.dp, top = 12.dp, bottom = 4.dp))
    }
}

@Composable
private fun PermissionRow(
    title: String,
    why: String,
    granted: Boolean,
    action: String?,
    onAction: () -> Unit,
    grantedLabel: String = "Allowed",
    deniedLabel: String = "Not allowed",
) {
    ListItem(
        headlineContent = { Text(title) },
        supportingContent = {
            Column {
                Text(why)
                Text(
                    if (granted) grantedLabel else deniedLabel,
                    style = MaterialTheme.typography.labelLarge,
                    color = if (granted) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
        },
        trailingContent = {
            if (action != null && (!granted || action == "Open settings")) TextButton(onClick = onAction) { Text(action) }
        },
        colors = transparent,
    )
}
