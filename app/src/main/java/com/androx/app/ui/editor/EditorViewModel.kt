package com.androx.app.ui.editor

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.androx.app.AppContainer
import com.androx.app.model.Action
import com.androx.app.model.Automation
import com.androx.app.model.Condition
import com.androx.app.model.EditorKind
import com.androx.app.model.NodeElement
import com.androx.app.model.Trigger
import com.androx.app.model.WorkflowCompiler
import com.androx.app.model.WorkflowGraph
import com.androx.app.ui.describeRun
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import java.util.UUID

/**
 * Holds one automation being edited. The Builder, Script and Workflow tabs are three views of this same state:
 * trigger, condition and actions are canonical; [graph] only stores canvas layout and unconnected nodes.
 */
class EditorViewModel(
    private val container: AppContainer,
    private val automationId: String?,
    startKind: EditorKind,
) : ViewModel() {

    private val id: String = automationId ?: UUID.randomUUID().toString()
    private var createdAt: Long = System.currentTimeMillis()

    var loading by mutableStateOf(automationId != null)
        private set
    var notFound by mutableStateOf(false)
        private set
    val isNew: Boolean = automationId == null

    var name by mutableStateOf("")
        private set
    var enabled by mutableStateOf(true)
        private set
    var trigger: Trigger by mutableStateOf(Trigger.Manual)
        private set
    var condition: Condition? by mutableStateOf(null)
        private set
    var actions: List<Action> by mutableStateOf(emptyList())
        private set
    var graph: WorkflowGraph by mutableStateOf(WorkflowGraph())
        private set
    var tab: EditorKind by mutableStateOf(startKind)
        private set
    var dirty by mutableStateOf(false)
        private set
    var busy by mutableStateOf(false)
        private set

    private val _messages = Channel<String>(Channel.BUFFERED)
    val messages = _messages.receiveAsFlow()

    /** Other automations this one may call. */
    val otherAutomations: List<Automation>
        get() = container.automations.state.value.filter { it.id != id }

    init {
        if (automationId == null) {
            actions = when (startKind) {
                EditorKind.SCRIPT -> listOf(Action.RunScript())
                else -> listOf(Action.ShowNotification("Androx", "Hello from Androx"))
            }
            if (startKind == EditorKind.WORKFLOW) graph = syncedGraph()
        } else {
            viewModelScope.launch {
                container.automations.awaitLoaded()
                val a = container.automations.get(automationId)
                if (a == null) {
                    notFound = true
                } else {
                    name = a.name
                    enabled = a.enabled
                    trigger = a.trigger
                    condition = a.condition
                    actions = a.actions
                    createdAt = a.createdAt
                    graph = WorkflowCompiler.sync(a.trigger, a.condition, a.actions, a.graph)
                    // Open on the tab the automation was last edited with, but never on a tab it doesn't suit.
                    tab = a.editor
                }
                loading = false
            }
        }
    }

    private fun syncedGraph(): WorkflowGraph = WorkflowCompiler.sync(trigger, condition, actions, graph.takeIf { it.nodes.isNotEmpty() })

    private fun touch() { dirty = true }

    fun changeName(value: String) { name = value; touch() }
    fun changeEnabled(value: Boolean) { enabled = value; touch() }
    fun changeTrigger(value: Trigger) { trigger = value; touch() }
    fun changeCondition(value: Condition?) { condition = value; touch() }
    fun addAction(action: Action) { actions = actions + action; touch() }
    fun updateAction(index: Int, action: Action) {
        actions = actions.mapIndexed { i, a -> if (i == index) action else a }
        touch()
    }
    fun removeAction(index: Int) { actions = actions.filterIndexed { i, _ -> i != index }; touch() }
    fun moveAction(index: Int, delta: Int) {
        val to = index + delta
        if (to !in actions.indices) return
        val list = actions.toMutableList()
        list.add(to, list.removeAt(index))
        actions = list
        touch()
    }

    /** Index of the script action the Script tab edits (the first one), or -1. */
    val scriptIndex: Int get() = actions.indexOfFirst { it is Action.RunScript }

    fun setScript(source: String) {
        val i = scriptIndex
        if (i >= 0) updateAction(i, Action.RunScript(source))
    }

    fun selectTab(kind: EditorKind) {
        if (kind == tab) return
        if (kind == EditorKind.WORKFLOW) graph = syncedGraph()
        tab = kind
    }

    // ---- Workflow operations (each keeps trigger/condition/actions in step with the graph) ----

    private fun applyGraph(next: WorkflowGraph, markDirty: Boolean = true) {
        graph = next
        val flow = WorkflowCompiler.compile(next)
        trigger = flow.trigger
        condition = flow.condition
        actions = flow.actions
        if (markDirty) touch()
    }

    /** Drags a node by a delta (dp), keeping it inside the canvas. Always reads the latest position. */
    fun moveNodeBy(nodeId: String, dx: Float, dy: Float, maxX: Float, maxY: Float) {
        val node = graph.nodes.firstOrNull { it.id == nodeId } ?: return
        applyGraph(WorkflowCompiler.moveNode(graph, nodeId, (node.x + dx).coerceIn(0f, maxX), (node.y + dy).coerceIn(0f, maxY)))
    }

    fun updateNode(nodeId: String, element: NodeElement) = applyGraph(WorkflowCompiler.updateNode(graph, nodeId, element))

    /** Returns an error message to show, or null on success. */
    fun connect(from: String, to: String): String? {
        val error = WorkflowCompiler.validateConnection(graph, from, to)
        if (error != null) return error
        applyGraph(WorkflowCompiler.connect(graph, from, to))
        return null
    }

    fun disconnectOutgoing(nodeId: String) = applyGraph(WorkflowCompiler.disconnectOutgoing(graph, nodeId))

    fun deleteNode(nodeId: String) = applyGraph(WorkflowCompiler.removeNode(graph, nodeId))

    fun tidy() = applyGraph(WorkflowCompiler.tidy(graph))

    fun addConditionNode() {
        if (graph.nodes.any { it.element is NodeElement.ConditionNode }) return
        val triggerNode = graph.nodes.firstOrNull { it.element is NodeElement.TriggerNode } ?: return
        val (withNode, newId) = WorkflowCompiler.addNode(graph, NodeElement.ConditionNode(Condition.BatteryLevel()))
        var next = withNode
        val oldNext = graph.edges.firstOrNull { it.from == triggerNode.id }?.to
        next = WorkflowCompiler.connect(next, triggerNode.id, newId)
        if (oldNext != null && WorkflowCompiler.validateConnection(next, newId, oldNext) == null) {
            next = WorkflowCompiler.connect(next, newId, oldNext)
        }
        applyGraph(WorkflowCompiler.tidy(next))
    }

    fun addActionNode(action: Action) {
        val end = WorkflowCompiler.chainEnd(graph)
        val (withNode, newId) = WorkflowCompiler.addNode(graph, NodeElement.ActionNode(action))
        var next = withNode
        if (end != null && WorkflowCompiler.validateConnection(next, end, newId) == null &&
            next.edges.none { it.from == end }
        ) {
            next = WorkflowCompiler.connect(next, end, newId)
        }
        applyGraph(next)
    }

    // ---- Saving and running ----

    fun validate(): String? {
        if (name.isBlank()) return "Give your automation a name."
        if (actions.isEmpty()) return "Add at least one action."
        actions.forEachIndexed { i, a ->
            val n = i + 1
            when (a) {
                is Action.RunScript -> if (a.source.isBlank()) return "Action $n: the script is empty."
                is Action.SetVariable -> if (a.name.isBlank()) return "Action $n: choose a variable name."
                is Action.RunAutomation -> {
                    if (a.automationId.isBlank()) return "Action $n: choose which automation to run."
                    if (a.automationId == id) return "Action $n: an automation can't run itself."
                }
                is Action.ShowNotification, is Action.WriteLog -> Unit
            }
        }
        val c = condition
        if (c is Condition.Variable && c.name.isBlank()) return "Condition: choose a variable name."
        return null
    }

    private fun build(): Automation {
        val now = System.currentTimeMillis()
        return Automation(
            id = id,
            name = name.trim(),
            enabled = enabled,
            trigger = trigger,
            condition = condition,
            actions = actions,
            editor = tab,
            graph = syncedGraph(),
            createdAt = createdAt,
            updatedAt = now,
        )
    }

    /** Saves and calls [onSaved] on success. Validation problems are sent to the snackbar. */
    fun save(onSaved: () -> Unit) {
        val problem = validate()
        if (problem != null) {
            viewModelScope.launch { _messages.send(problem) }
            return
        }
        val automation = build()
        busy = true
        container.scope.launch {
            container.automations.upsert(automation)
            busy = false
            dirty = false
            onSaved()
        }
    }

    /** Saves, then runs once. The result is reported in the snackbar and recorded in History. */
    fun saveAndRun() {
        val problem = validate()
        if (problem != null) {
            viewModelScope.launch { _messages.send(problem) }
            return
        }
        val automation = build()
        busy = true
        container.scope.launch {
            container.automations.upsert(automation)
            dirty = false
            val record = container.runner.runManually(automation.id)
            busy = false
            _messages.send(describeRun(record, automation.name))
        }
    }

    /** True if running this automation would try to show a notification. */
    fun needsNotifications(): Boolean = actions.any { it is Action.ShowNotification || it is Action.RunScript || it is Action.RunAutomation }
}
