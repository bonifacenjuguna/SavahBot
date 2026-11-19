package com.androx.app

import com.androx.app.engine.ActionException
import com.androx.app.engine.DeviceBridge
import com.androx.app.engine.ExecutionEngine
import com.androx.app.engine.RhinoScriptRunner
import com.androx.app.engine.VariableStore
import com.androx.app.model.Action
import com.androx.app.model.Automation
import com.androx.app.model.Comparison
import com.androx.app.model.Condition
import com.androx.app.model.ExecutionStatus
import com.androx.app.model.RunSource
import com.androx.app.model.VariableMode
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

private class FakeDevice(var battery: Int = 80, var charging: Boolean = false, var allowNotifications: Boolean = true) : DeviceBridge {
    val notifications = mutableListOf<Pair<String, String>>()
    override fun batteryLevel() = battery
    override fun isCharging() = charging
    override fun showNotification(title: String, message: String) {
        if (!allowNotifications) throw ActionException("Notifications are blocked")
        notifications += title to message
    }
}

private class FakeVars : VariableStore {
    val map = mutableMapOf<String, String>()
    override fun get(name: String) = map[name]
    override fun set(name: String, value: String) { map[name] = value }
    override fun remove(name: String) { map.remove(name) }
}

class EngineTest {
    private val device = FakeDevice()
    private val vars = FakeVars()
    private val all = mutableMapOf<String, Automation>()
    private val engine = ExecutionEngine(device, vars, { all[it] }, RhinoScriptRunner(timeoutMillis = 400))

    private fun auto(id: String, vararg actions: Action, condition: Condition? = null) =
        Automation(id = id, name = "A-$id", condition = condition, actions = actions.toList()).also { all[id] = it }

    private fun run(a: Automation) = runBlocking { engine.execute(a, RunSource.MANUAL) }

    @Test
    fun runsActionsInOrderWithTemplates() {
        val a = auto(
            "1",
            Action.SetVariable("count", "2", VariableMode.SET),
            Action.SetVariable("count", "3", VariableMode.ADD),
            Action.ShowNotification("Count {{count}}", "battery {{battery}}% in {{automation}}"),
        )
        val r = run(a)
        assertEquals(ExecutionStatus.SUCCESS, r.status)
        assertEquals("5", vars.map["count"])
        assertEquals("Count 5" to "battery 80% in A-1", device.notifications.single())
    }

    @Test
    fun conditionFalseSkipsWithoutRunningActions() {
        val a = auto("1", Action.ShowNotification("x", "y"), condition = Condition.BatteryLevel(Comparison.LT, 20))
        val r = run(a)
        assertEquals(ExecutionStatus.SKIPPED, r.status)
        assertTrue(device.notifications.isEmpty())
    }

    @Test
    fun conditionTrueRuns() {
        device.battery = 10
        val a = auto("1", Action.ShowNotification("x", "y"), condition = Condition.BatteryLevel(Comparison.LT, 20))
        assertEquals(ExecutionStatus.SUCCESS, run(a).status)
    }

    @Test
    fun variableConditionComparesNumbersNumerically() {
        vars.map["n"] = "10"
        val a = auto("1", Action.WriteLog("ok"), condition = Condition.Variable("n", Comparison.GT, "9"))
        assertEquals(ExecutionStatus.SUCCESS, run(a).status)
    }

    @Test
    fun blockedNotificationIsReportedAsFailureAndStopsTheRun() {
        device.allowNotifications = false
        val a = auto("1", Action.ShowNotification("x", "y"), Action.SetVariable("after", "1"))
        val r = run(a)
        assertEquals(ExecutionStatus.FAILED, r.status)
        assertEquals("Notifications are blocked", r.message)
        assertTrue(!vars.map.containsKey("after"))
    }

    @Test
    fun addToNonNumberFails() {
        vars.map["v"] = "abc"
        val r = run(auto("1", Action.SetVariable("v", "1", VariableMode.ADD)))
        assertEquals(ExecutionStatus.FAILED, r.status)
    }

    @Test
    fun nestedAutomationRunsAndMissingOneFails() {
        auto("child", Action.SetVariable("child", "yes"))
        val ok = run(auto("parent", Action.RunAutomation("child", "A-child")))
        assertEquals(ExecutionStatus.SUCCESS, ok.status)
        assertEquals("yes", vars.map["child"])
        val bad = run(auto("p2", Action.RunAutomation("gone", "Gone")))
        assertEquals(ExecutionStatus.FAILED, bad.status)
    }

    @Test
    fun recursionIsStopped() {
        auto("a", Action.RunAutomation("b", "b"))
        auto("b", Action.RunAutomation("a", "a"))
        val r = run(all.getValue("a"))
        assertEquals(ExecutionStatus.FAILED, r.status)
        assertTrue(r.message!!.contains("call itself"))
    }

    @Test
    fun scriptCanUseTheApi() {
        val script = """
            const n = Number(androx.getVar("runs") || 0) + 1;
            androx.setVar("runs", n);
            androx.log("battery", androx.battery(), androx.isCharging());
            androx.notify("From script", "run " + n);
        """.trimIndent()
        val r = run(auto("s", Action.RunScript(script)))
        assertEquals(r.message, ExecutionStatus.SUCCESS, r.status)
        assertEquals("1", vars.map["runs"])
        assertEquals("From script" to "run 1", device.notifications.single())
        assertTrue(r.logs.any { it.contains("battery 80 false") })
    }

    @Test
    fun scriptErrorsAreReportedWithLine() {
        val r = run(auto("s", Action.RunScript("let a = 1;\nundefinedFunction();")))
        assertEquals(ExecutionStatus.FAILED, r.status)
        assertTrue(r.message!!, r.message!!.contains("line 2"))
    }

    @Test
    fun scriptSyntaxErrorFails() {
        assertEquals(ExecutionStatus.FAILED, run(auto("s", Action.RunScript("if ("))).status)
    }

    @Test
    fun scriptSeesActionFailures() {
        device.allowNotifications = false
        val r = run(auto("s", Action.RunScript("androx.notify('a','b')")))
        assertEquals(ExecutionStatus.FAILED, r.status)
        assertTrue(r.message!!, r.message!!.contains("blocked"))
    }

    @Test
    fun infiniteScriptIsStopped() {
        val r = run(auto("s", Action.RunScript("while (true) {}")))
        assertEquals(ExecutionStatus.FAILED, r.status)
        assertTrue(r.message!!, r.message!!.contains("stopped"))
    }

    @Test
    fun scriptCannotReachJavaOrAndroidClasses() {
        val probe = "androx.setVar('t', typeof Packages + '|' + typeof java + '|' + typeof androx.getClass);"
        val r = run(auto("s", Action.RunScript(probe)))
        assertEquals(r.message, ExecutionStatus.SUCCESS, r.status)
        assertEquals("undefined|undefined|undefined", vars.map["t"])
    }
}
