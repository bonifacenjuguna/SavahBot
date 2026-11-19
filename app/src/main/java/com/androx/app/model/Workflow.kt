package com.androx.app.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.util.UUID

@Serializable
sealed interface NodeElement {
    @Serializable
    @SerialName("trigger")
    data class TriggerNode(val trigger: Trigger) : NodeElement

    @Serializable
    @SerialName("condition")
    data class ConditionNode(val condition: Condition) : NodeElement

    @Serializable
    @SerialName("action")
    data class ActionNode(val action: Action) : NodeElement
}

/** [x]/[y] are in dp inside the workflow canvas. */
@Serializable
data class WfNode(val id: String, val x: Float, val y: Float, val element: NodeElement)

@Serializable
data class WfEdge(val from: String, val to: String)

@Serializable
data class WorkflowGraph(val nodes: List<WfNode> = emptyList(), val edges: List<WfEdge> = emptyList())

data class CompiledFlow(
    val trigger: Trigger,
    val condition: Condition?,
    val actions: List<Action>,
    /** Ids of nodes that are part of the executable chain, in order. */
    val connectedIds: List<String>,
    /** Nodes that exist on the canvas but are not reachable from the trigger. They are kept, not executed. */
    val orphanIds: Set<String>,
)

/**
 * Converts between the canonical Trigger → Condition → Actions form and the node graph.
 * The v0.0.0 workflow model is a single linear chain; branching is intentionally impossible to create.
 */
object WorkflowCompiler {
    const val NODE_X = 80f
    const val NODE_Y0 = 40f
    const val NODE_STEP = 116f

    fun newId(): String = "n" + UUID.randomUUID().toString().take(8)

    fun compile(graph: WorkflowGraph): CompiledFlow {
        val triggerNode = graph.nodes.firstOrNull { it.element is NodeElement.TriggerNode }
        val chain = mutableListOf<WfNode>()
        if (triggerNode != null) {
            val visited = mutableSetOf(triggerNode.id)
            var current = triggerNode
            while (true) {
                val edge = graph.edges.firstOrNull { it.from == current.id } ?: break
                val next = graph.nodes.firstOrNull { it.id == edge.to } ?: break
                if (!visited.add(next.id)) break
                chain += next
                current = next
            }
        }
        var condition: Condition? = null
        val actions = mutableListOf<Action>()
        val connected = mutableListOf<String>()
        if (triggerNode != null) connected += triggerNode.id
        for (node in chain) {
            val element = node.element
            if (element is NodeElement.ConditionNode && condition == null && actions.isEmpty()) {
                condition = element.condition
                connected += node.id
            } else if (element is NodeElement.ActionNode) {
                actions += element.action
                connected += node.id
            } else {
                break
            }
        }
        val trigger = (triggerNode?.element as? NodeElement.TriggerNode)?.trigger ?: Trigger.Manual
        val orphans = graph.nodes.map { it.id }.toSet() - connected.toSet()
        return CompiledFlow(trigger, condition, actions, connected, orphans)
    }

    /** Lays the canonical flow out as a vertical chain. */
    fun fromFlow(trigger: Trigger, condition: Condition?, actions: List<Action>): WorkflowGraph {
        val elements = buildList<NodeElement> {
            add(NodeElement.TriggerNode(trigger))
            if (condition != null) add(NodeElement.ConditionNode(condition))
            actions.forEach { add(NodeElement.ActionNode(it)) }
        }
        val nodes = elements.mapIndexed { i, e -> WfNode(newId(), NODE_X, NODE_Y0 + i * NODE_STEP, e) }
        val edges = nodes.zipWithNext { a, b -> WfEdge(a.id, b.id) }
        return WorkflowGraph(nodes, edges)
    }

    /**
     * Makes sure [old] describes the given flow. If it already does, it is returned untouched (layout and
     * unconnected nodes survive). Otherwise the chain is rebuilt from the flow and previously unconnected
     * nodes are carried over, so nothing the user drew is silently discarded.
     */
    fun sync(trigger: Trigger, condition: Condition?, actions: List<Action>, old: WorkflowGraph?): WorkflowGraph {
        if (old != null && old.nodes.any { it.element is NodeElement.TriggerNode }) {
            val c = compile(old)
            if (c.trigger == trigger && c.condition == condition && c.actions == actions) return old
        }
        val fresh = fromFlow(trigger, condition, actions)
        if (old == null) return fresh
        val oldOrphans = compile(old).orphanIds
        val keep = old.nodes.filter { it.id in oldOrphans }
        val keepIds = keep.map { it.id }.toSet()
        val keepEdges = old.edges.filter { it.from in keepIds && it.to in keepIds }
        return WorkflowGraph(fresh.nodes + keep, fresh.edges + keepEdges)
    }

    /** Returns a user-facing reason why the connection is not allowed, or null if it is. */
    fun validateConnection(graph: WorkflowGraph, from: String, to: String): String? {
        val a = graph.nodes.firstOrNull { it.id == from } ?: return "Unknown node."
        val b = graph.nodes.firstOrNull { it.id == to } ?: return "Unknown node."
        if (from == to) return "A node can't connect to itself."
        if (b.element is NodeElement.TriggerNode) return "Nothing can connect into the trigger."
        if (b.element is NodeElement.ConditionNode && a.element !is NodeElement.TriggerNode) {
            return "A condition has to follow the trigger directly."
        }
        if (reaches(graph, to, from)) return "That would create a loop."
        return null
    }

    private fun reaches(graph: WorkflowGraph, start: String, target: String): Boolean {
        val seen = mutableSetOf<String>()
        val stack = ArrayDeque<String>()
        stack.add(start)
        while (stack.isNotEmpty()) {
            val n = stack.removeLast()
            if (n == target) return true
            if (!seen.add(n)) continue
            graph.edges.filter { it.from == n }.forEach { stack.add(it.to) }
        }
        return false
    }

    /** Adds the edge, replacing any existing outgoing edge of [from] and incoming edge of [to]. */
    fun connect(graph: WorkflowGraph, from: String, to: String): WorkflowGraph {
        val kept = graph.edges.filter { it.from != from && it.to != to }
        return graph.copy(edges = kept + WfEdge(from, to))
    }

    fun disconnectOutgoing(graph: WorkflowGraph, from: String): WorkflowGraph =
        graph.copy(edges = graph.edges.filter { it.from != from })

    fun moveNode(graph: WorkflowGraph, id: String, x: Float, y: Float): WorkflowGraph =
        graph.copy(nodes = graph.nodes.map { if (it.id == id) it.copy(x = x, y = y) else it })

    fun updateNode(graph: WorkflowGraph, id: String, element: NodeElement): WorkflowGraph =
        graph.copy(nodes = graph.nodes.map { if (it.id == id) it.copy(element = element) else it })

    /** Removes a node; if it sat in the middle of a chain its neighbours are reconnected when allowed. */
    fun removeNode(graph: WorkflowGraph, id: String): WorkflowGraph {
        val incoming = graph.edges.firstOrNull { it.to == id }
        val outgoing = graph.edges.firstOrNull { it.from == id }
        var next = graph.copy(
            nodes = graph.nodes.filter { it.id != id },
            edges = graph.edges.filter { it.from != id && it.to != id },
        )
        if (incoming != null && outgoing != null && validateConnection(next, incoming.from, outgoing.to) == null) {
            next = connect(next, incoming.from, outgoing.to)
        }
        return next
    }

    /** Adds a node under everything else. Returns the new graph and the new node id. */
    fun addNode(graph: WorkflowGraph, element: NodeElement): Pair<WorkflowGraph, String> {
        val y = (graph.nodes.maxOfOrNull { it.y } ?: (NODE_Y0 - NODE_STEP)) + NODE_STEP
        val node = WfNode(newId(), NODE_X, y, element)
        return graph.copy(nodes = graph.nodes + node) to node.id
    }

    /** The last node of the executable chain, if there is a trigger. */
    fun chainEnd(graph: WorkflowGraph): String? = compile(graph).connectedIds.lastOrNull()

    /** Re-arranges the chain vertically and stacks unconnected nodes underneath. */
    fun tidy(graph: WorkflowGraph): WorkflowGraph {
        val c = compile(graph)
        val order = c.connectedIds + graph.nodes.map { it.id }.filter { it in c.orphanIds }
        val pos = order.withIndex().associate { (i, id) -> id to (NODE_Y0 + i * NODE_STEP) }
        return graph.copy(nodes = graph.nodes.map { it.copy(x = NODE_X, y = pos[it.id] ?: it.y) })
    }
}
