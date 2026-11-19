@file:OptIn(ExperimentalMaterial3Api::class)

package com.androx.app.ui.editor

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.matchParentSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.graphics.vector.rememberVectorPainter
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import com.androx.app.R
import com.androx.app.model.Automation
import com.androx.app.model.NodeElement
import com.androx.app.model.WfNode
import com.androx.app.model.WorkflowCompiler
import com.androx.app.model.label
import com.androx.app.model.summary
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.roundToInt

private val NodeW = 188.dp
private val NodeH = 76.dp
private val PortArea = 40.dp
private val CanvasSize = 1600.dp

/**
 * A small node editor. The chain is Trigger → (Condition) → Actions. Drag nodes to move them; tap the dot under a node
 * and then the dot above another node to connect them. Nodes that are not connected to the trigger are kept but don't run.
 */
@Composable
fun WorkflowTab(vm: EditorViewModel, showMessage: (String) -> Unit) {
    val graph = vm.graph
    val compiled = remember(graph) { WorkflowCompiler.compile(graph) }
    var pan by remember { mutableStateOf(Offset.Zero) }
    var connectFrom by remember { mutableStateOf<String?>(null) }
    var selectedId by remember { mutableStateOf<String?>(null) }
    var addMenu by remember { mutableStateOf(false) }
    val density = LocalDensity.current
    val scheme = MaterialTheme.colorScheme
    val hasCondition = graph.nodes.any { it.element is NodeElement.ConditionNode }
    val lineColor = scheme.primary
    val dimLine = scheme.outline
    val dotColor = scheme.outlineVariant
    val others = vm.otherAutomations

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            AssistChip(
                onClick = { vm.addConditionNode() },
                enabled = !hasCondition,
                label = { Text("Condition") },
                leadingIcon = { Icon(Icons.Filled.Add, contentDescription = null) },
            )
            Box {
                AssistChip(
                    onClick = { addMenu = true },
                    label = { Text("Action") },
                    leadingIcon = { Icon(Icons.Filled.Add, contentDescription = null) },
                )
                DropdownMenu(expanded = addMenu, onDismissRequest = { addMenu = false }) {
                    actionKindLabels.forEachIndexed { index, label ->
                        DropdownMenuItem(text = { Text(label) }, onClick = { addMenu = false; vm.addActionNode(newActionOfKind(index)) })
                    }
                }
            }
            AssistChip(onClick = { vm.tidy(); pan = Offset.Zero }, label = { Text("Tidy") })
        }
        Text(
            if (connectFrom == null) "Drag to move. Tap the dot under a node, then the dot above another one to connect."
            else "Now tap the dot above the node to connect to. Tap the same dot again to cancel.",
            style = MaterialTheme.typography.labelMedium,
            color = scheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp),
        )
        if (compiled.orphanIds.isNotEmpty()) {
            Text(
                "${compiled.orphanIds.size} unconnected node${if (compiled.orphanIds.size == 1) "" else "s"} won't run, but ${if (compiled.orphanIds.size == 1) "is" else "are"} kept.",
                style = MaterialTheme.typography.labelMedium,
                color = scheme.error,
                modifier = Modifier.padding(horizontal = 16.dp),
            )
        }
        Box(
            Modifier
                .padding(top = 8.dp)
                .weight(1f)
                .fillMaxWidth()
                .clipToBounds()
                .background(scheme.surfaceContainerLow)
                .pointerInput(Unit) {
                    detectDragGestures { change, drag ->
                        change.consume()
                        pan += drag
                    }
                },
        ) {
            // Dot grid that moves with the canvas.
            Canvas(Modifier.matchParentSize()) {
                val step = 28.dp.toPx()
                val ox = ((pan.x % step) + step) % step
                val oy = ((pan.y % step) + step) % step
                var x = ox
                while (x < size.width) {
                    var y = oy
                    while (y < size.height) {
                        drawCircle(dotColor, radius = 1.2.dp.toPx(), center = Offset(x, y))
                        y += step
                    }
                    x += step
                }
            }
            Box(Modifier.offset { IntOffset(pan.x.roundToInt(), pan.y.roundToInt()) }.requiredSize(CanvasSize)) {
                Canvas(Modifier.matchParentSize()) {
                    val byId = graph.nodes.associateBy { it.id }
                    val w = NodeW.toPx()
                    val h = NodeH.toPx()
                    graph.edges.forEach { edge ->
                        val a = byId[edge.from] ?: return@forEach
                        val b = byId[edge.to] ?: return@forEach
                        val start = Offset(a.x.dp.toPx() + w / 2, a.y.dp.toPx() + h)
                        val end = Offset(b.x.dp.toPx() + w / 2, b.y.dp.toPx())
                        val dy = max(48.dp.toPx(), abs(end.y - start.y) / 2)
                        val path = Path().apply {
                            moveTo(start.x, start.y)
                            cubicTo(start.x, start.y + dy, end.x, end.y - dy, end.x, end.y)
                        }
                        val live = edge.from in compiled.connectedIds && edge.to in compiled.connectedIds
                        drawPath(path, color = if (live) lineColor else dimLine, style = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round))
                    }
                }
                graph.nodes.forEach { node ->
                    key(node.id) {
                        NodeCard(
                            node = node,
                            live = node.id in compiled.connectedIds,
                            isSource = connectFrom == node.id,
                            connecting = connectFrom != null,
                            onDrag = { dx, dy ->
                                val d = density.density
                                vm.moveNodeBy(
                                    node.id, dx / d, dy / d,
                                    maxX = CanvasSize.value - NodeW.value,
                                    maxY = CanvasSize.value - NodeH.value - 8f,
                                )
                            },
                            onClick = { selectedId = node.id },
                            onOutPort = { connectFrom = if (connectFrom == node.id) null else node.id },
                            onInPort = {
                                val from = connectFrom
                                if (from != null) {
                                    if (from == node.id) {
                                        connectFrom = null
                                    } else {
                                        val error = vm.connect(from, node.id)
                                        if (error != null) showMessage(error) else connectFrom = null
                                    }
                                }
                            },
                        )
                    }
                }
            }
        }
    }

    val id = selectedId
    if (id != null) {
        val node = graph.nodes.firstOrNull { it.id == id }
        if (node == null) {
            selectedId = null
        } else {
            ModalBottomSheet(
                onDismissRequest = { selectedId = null },
                sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
            ) {
                NodeSheet(vm, node, others) { selectedId = null }
            }
        }
    }
}

@Composable
private fun NodeSheet(vm: EditorViewModel, node: WfNode, others: List<Automation>, onDone: () -> Unit) {
    val hasOutgoing = vm.graph.edges.any { it.from == node.id }
    Column(
        Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 24.dp).padding(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        when (val element = node.element) {
            is NodeElement.TriggerNode -> {
                Text("Trigger", style = MaterialTheme.typography.titleLarge)
                TriggerEditor(element.trigger) { vm.updateNode(node.id, NodeElement.TriggerNode(it)) }
            }
            is NodeElement.ConditionNode -> {
                Text("Condition", style = MaterialTheme.typography.titleLarge)
                ConditionEditor(element.condition) { vm.updateNode(node.id, NodeElement.ConditionNode(it)) }
            }
            is NodeElement.ActionNode -> {
                Text("Action", style = MaterialTheme.typography.titleLarge)
                ActionEditor(element.action, others, { vm.updateNode(node.id, NodeElement.ActionNode(it)) })
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (hasOutgoing) {
                TextButton(onClick = { vm.disconnectOutgoing(node.id) }) { Text("Disconnect next") }
            }
            if (node.element !is NodeElement.TriggerNode) {
                TextButton(onClick = { vm.deleteNode(node.id); onDone() }) { Text("Delete node") }
            }
        }
        Button(onClick = onDone, modifier = Modifier.fillMaxWidth()) { Text("Done") }
    }
}

@Composable
private fun NodeCard(
    node: WfNode,
    live: Boolean,
    isSource: Boolean,
    connecting: Boolean,
    onDrag: (Float, Float) -> Unit,
    onClick: () -> Unit,
    onOutPort: () -> Unit,
    onInPort: () -> Unit,
) {
    val scheme = MaterialTheme.colorScheme
    val element = node.element
    val title: String
    val subtitle: String
    val icon: Painter
    val container = when (element) {
        is NodeElement.TriggerNode -> scheme.primaryContainer
        is NodeElement.ConditionNode -> scheme.secondaryContainer
        is NodeElement.ActionNode -> scheme.surfaceContainerHigh
    }
    when (element) {
        is NodeElement.TriggerNode -> {
            title = "Trigger"; subtitle = element.trigger.summary(); icon = painterResource(R.drawable.ic_bolt)
        }
        is NodeElement.ConditionNode -> {
            title = "Condition"; subtitle = element.condition.summary(); icon = rememberVectorPainter(Icons.Filled.CheckCircle)
        }
        is NodeElement.ActionNode -> {
            title = element.action.label(); subtitle = element.action.summary(); icon = rememberVectorPainter(Icons.Filled.PlayArrow)
        }
    }
    val isTrigger = element is NodeElement.TriggerNode

    // The outer box is taller than the card so the connection dots (half outside the card) stay inside its bounds and tappable.
    Box(
        Modifier
            .offset { IntOffset(node.x.dp.roundToPx(), (node.y.dp - PortArea / 2).roundToPx()) }
            .size(NodeW, NodeH + PortArea)
            .alpha(if (live) 1f else 0.6f),
    ) {
        Card(
            onClick = onClick,
            modifier = Modifier
                .align(Alignment.Center)
                .size(NodeW, NodeH)
                .pointerInput(node.id) {
                    detectDragGestures { change, drag ->
                        change.consume()
                        onDrag(drag.x, drag.y)
                    }
                },
            colors = CardDefaults.cardColors(containerColor = container),
            border = if (isSource) BorderStroke(2.dp, scheme.primary) else null,
        ) {
            Row(Modifier.fillMaxSize().padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(icon, contentDescription = null, modifier = Modifier.size(22.dp))
                Column(Modifier.padding(start = 10.dp)) {
                    Text(title, style = MaterialTheme.typography.labelLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(
                        if (live) subtitle.ifBlank { "—" } else "Not connected",
                        style = MaterialTheme.typography.bodySmall,
                        color = scheme.onSurfaceVariant,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
        if (!isTrigger) {
            Port(
                Modifier.align(Alignment.TopCenter),
                filled = connecting && !isSource,
                description = "Connect into ${title}",
                onClick = onInPort,
            )
        }
        Port(
            Modifier.align(Alignment.BottomCenter),
            filled = isSource,
            description = "Connect from ${title}",
            onClick = onOutPort,
        )
    }
}

@Composable
private fun Port(modifier: Modifier, filled: Boolean, description: String, onClick: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Box(
        modifier
            .size(PortArea)
            .clickable(onClickLabel = description, role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            Modifier
                .size(16.dp)
                .clip(CircleShape)
                .background(if (filled) scheme.primary else scheme.surface)
                .border(2.dp, scheme.primary, CircleShape)
        )
    }
}
