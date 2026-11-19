package com.androx.app

import com.androx.app.model.Action
import com.androx.app.model.Condition
import com.androx.app.model.NodeElement
import com.androx.app.model.Trigger
import com.androx.app.model.WfEdge
import com.androx.app.model.WfNode
import com.androx.app.model.WorkflowCompiler
import com.androx.app.model.WorkflowGraph
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkflowTest {
    private val a1 = Action.WriteLog("one")
    private val a2 = Action.WriteLog("two")
    private val cond = Condition.BatteryLevel()

    @Test
    fun flowToGraphAndBack() {
        val g = WorkflowCompiler.fromFlow(Trigger.Manual, cond, listOf(a1, a2))
        val c = WorkflowCompiler.compile(g)
        assertEquals(Trigger.Manual, c.trigger)
        assertEquals(cond, c.condition)
        assertEquals(listOf(a1, a2), c.actions)
        assertTrue(c.orphanIds.isEmpty())
    }

    @Test
    fun disconnectedNodesAreKeptButNotCompiled() {
        val g = WorkflowCompiler.fromFlow(Trigger.Manual, null, listOf(a1, a2))
        val firstAction = g.nodes[1]
        val cut = WorkflowCompiler.disconnectOutgoing(g, firstAction.id)
        val c = WorkflowCompiler.compile(cut)
        assertEquals(listOf(a1), c.actions)
        assertEquals(setOf(g.nodes[2].id), c.orphanIds)
        assertEquals(3, cut.nodes.size) // nothing deleted
    }

    @Test
    fun syncKeepsGraphWhenNothingChanged() {
        val g = WorkflowCompiler.fromFlow(Trigger.Manual, null, listOf(a1, a2))
        val cut = WorkflowCompiler.disconnectOutgoing(g, g.nodes[1].id)
        val c = WorkflowCompiler.compile(cut)
        val same = WorkflowCompiler.sync(c.trigger, c.condition, c.actions, cut)
        assertEquals(cut, same)
    }

    @Test
    fun syncRebuildsChainButCarriesOrphans() {
        val g = WorkflowCompiler.fromFlow(Trigger.Manual, null, listOf(a1, a2))
        val cut = WorkflowCompiler.disconnectOutgoing(g, g.nodes[1].id)
        val orphanId = g.nodes[2].id
        // the Builder then adds a third action
        val rebuilt = WorkflowCompiler.sync(Trigger.Manual, null, listOf(a1, Action.WriteLog("three")), cut)
        assertTrue(rebuilt.nodes.any { it.id == orphanId })
        val c = WorkflowCompiler.compile(rebuilt)
        assertEquals(listOf(a1, Action.WriteLog("three")), c.actions)
        assertEquals(setOf(orphanId), c.orphanIds)
    }

    @Test
    fun connectionRules() {
        val g = WorkflowCompiler.fromFlow(Trigger.Manual, cond, listOf(a1, a2))
        val (t, c, x, y) = g.nodes
        assertNotNull(WorkflowCompiler.validateConnection(g, t.id, t.id))
        assertNotNull(WorkflowCompiler.validateConnection(g, x.id, t.id)) // into trigger
        assertNotNull(WorkflowCompiler.validateConnection(g, x.id, c.id)) // condition must follow trigger
        assertNotNull(WorkflowCompiler.validateConnection(g, y.id, x.id)) // loop
        assertNull(WorkflowCompiler.validateConnection(g, t.id, x.id))
    }

    @Test
    fun removingMiddleNodeHealsTheChain() {
        val g = WorkflowCompiler.fromFlow(Trigger.Manual, null, listOf(a1, a2, Action.WriteLog("three")))
        val removed = WorkflowCompiler.removeNode(g, g.nodes[2].id)
        assertEquals(listOf(a1, Action.WriteLog("three")), WorkflowCompiler.compile(removed).actions)
    }

    @Test
    fun noTriggerNodeMeansNothingRuns() {
        val g = WorkflowGraph(listOf(WfNode("a", 0f, 0f, NodeElement.ActionNode(a1))), emptyList())
        val c = WorkflowCompiler.compile(g)
        assertTrue(c.actions.isEmpty())
        assertEquals(setOf("a"), c.orphanIds)
    }

    @Test
    fun cyclesInStoredDataDoNotHang() {
        val t = WfNode("t", 0f, 0f, NodeElement.TriggerNode(Trigger.Manual))
        val x = WfNode("x", 0f, 0f, NodeElement.ActionNode(a1))
        val g = WorkflowGraph(listOf(t, x), listOf(WfEdge("t", "x"), WfEdge("x", "t")))
        assertEquals(listOf(a1), WorkflowCompiler.compile(g).actions)
    }
}
