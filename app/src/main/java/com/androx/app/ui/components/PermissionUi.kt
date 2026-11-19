package com.androx.app.ui.components

import android.Manifest
import android.content.Context
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import com.androx.app.model.Action
import com.androx.app.model.Automation
import com.androx.app.platform.Permissions

/** True if running this automation would try to post a notification. */
fun Automation.mayNotify(): Boolean = actions.any { it is Action.ShowNotification || it is Action.RunScript || it is Action.RunAutomation }

/**
 * Asks for the notification permission only at the moment it matters (the user runs something that posts one),
 * explains why first, and never nags: after one prompt the run simply proceeds and reports honestly if Android blocked it.
 */
@Stable
class NotificationGate internal constructor(
    private val context: Context,
    private val launchRequest: () -> Unit,
) {
    var showRationale by mutableStateOf(false)
    var requestedOnce by mutableStateOf(false)
        private set
    private var pending: (() -> Unit)? = null

    fun ensure(needed: Boolean, proceed: () -> Unit) {
        val promptable = Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
        if (!needed || !promptable || requestedOnce || Permissions.notificationsEnabled(context)) {
            proceed()
            return
        }
        pending = proceed
        showRationale = true
    }

    fun requestNow() {
        requestedOnce = true
        showRationale = false
        launchRequest()
    }

    fun skip() {
        showRationale = false
        requestedOnce = true
        pending?.invoke()
        pending = null
    }

    internal fun onResult() {
        pending?.invoke()
        pending = null
    }
}

@Composable
fun rememberNotificationGate(): NotificationGate {
    val context = LocalContext.current
    val holder = remember { arrayOfNulls<NotificationGate>(1) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        holder[0]?.onResult()
    }
    val gate = remember {
        NotificationGate(context) { launcher.launch(Manifest.permission.POST_NOTIFICATIONS) }.also { holder[0] = it }
    }
    if (gate.showRationale) {
        AlertDialog(
            onDismissRequest = { gate.skip() },
            title = { Text("Allow notifications?") },
            text = {
                Text(
                    "This automation can show a notification. Android needs your permission for that. " +
                        "If you skip it, the automation will still run but the notification will fail and be logged in History."
                )
            },
            confirmButton = { TextButton(onClick = { gate.requestNow() }) { Text("Continue") } },
            dismissButton = { TextButton(onClick = { gate.skip() }) { Text("Not now") } },
        )
    }
    return gate
}
