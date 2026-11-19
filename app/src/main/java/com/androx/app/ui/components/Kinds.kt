@file:OptIn(ExperimentalMaterial3Api::class)

package com.androx.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Build
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.foundation.clickable
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.graphics.vector.rememberVectorPainter
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import com.androx.app.R
import com.androx.app.model.EditorKind

@Composable
fun kindIcon(kind: EditorKind): Painter = when (kind) {
    EditorKind.BUILDER -> rememberVectorPainter(Icons.Filled.Build)
    EditorKind.SCRIPT -> painterResource(R.drawable.ic_code)
    EditorKind.WORKFLOW -> painterResource(R.drawable.ic_workflow)
}

fun kindLabel(kind: EditorKind): String = when (kind) {
    EditorKind.BUILDER -> "Builder"
    EditorKind.SCRIPT -> "JavaScript"
    EditorKind.WORKFLOW -> "Workflow"
}

@Composable
fun IconBadge(painter: Painter, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .size(40.dp)
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.secondaryContainer),
        contentAlignment = Alignment.Center,
    ) {
        Icon(painter, contentDescription = null, tint = MaterialTheme.colorScheme.onSecondaryContainer, modifier = Modifier.size(22.dp))
    }
}

/** Bottom sheet that lets the user pick one of the three ways to create an automation. */
@Composable
fun NewAutomationSheet(onPick: (EditorKind) -> Unit, onDismiss: () -> Unit) {
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = state) {
        Column(Modifier.padding(bottom = 16.dp)) {
            Text(
                "New automation",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
            )
            Option(EditorKind.BUILDER, "Builder", "Pick a trigger, an optional condition and actions. No code.", onPick)
            Option(EditorKind.SCRIPT, "JavaScript", "Write a script against the Androx API.", onPick)
            Option(EditorKind.WORKFLOW, "Visual workflow", "Place nodes on a canvas and connect them.", onPick)
        }
    }
}

@Composable
private fun Option(kind: EditorKind, title: String, description: String, onPick: (EditorKind) -> Unit) {
    ListItem(
        headlineContent = { Text(title) },
        supportingContent = { Text(description) },
        leadingContent = { IconBadge(kindIcon(kind)) },
        colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
        modifier = Modifier.clickable { onPick(kind) },
    )
}
