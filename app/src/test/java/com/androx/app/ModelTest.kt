package com.androx.app

import com.androx.app.data.JsonFile
import com.androx.app.model.Action
import com.androx.app.model.Automation
import com.androx.app.model.Comparison
import com.androx.app.model.Condition
import com.androx.app.model.EditorKind
import com.androx.app.model.Templates
import com.androx.app.model.Trigger
import com.androx.app.model.VariableMode
import com.androx.app.model.WorkflowCompiler
import com.androx.app.model.describeDays
import kotlinx.serialization.builtins.ListSerializer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.time.ZoneId
import java.time.ZonedDateTime

class ModelTest {
    private val utc = ZoneId.of("UTC")

    @Test
    fun scheduleNextRunToday() {
        val now = ZonedDateTime.of(2026, 11, 19, 7, 0, 0, 0, utc).toInstant().toEpochMilli() // Thursday
        val next = Trigger.Schedule(8, 30).nextRunMillis(now, utc)
        assertEquals(ZonedDateTime.of(2026, 11, 19, 8, 30, 0, 0, utc).toInstant().toEpochMilli(), next)
    }

    @Test
    fun scheduleRollsToTomorrowWhenPassed() {
        val now = ZonedDateTime.of(2026, 11, 19, 9, 0, 0, 0, utc).toInstant().toEpochMilli()
        val next = Trigger.Schedule(8, 30).nextRunMillis(now, utc)
        assertEquals(ZonedDateTime.of(2026, 11, 20, 8, 30, 0, 0, utc).toInstant().toEpochMilli(), next)
    }

    @Test
    fun scheduleHonoursDays() {
        val now = ZonedDateTime.of(2026, 11, 19, 9, 0, 0, 0, utc).toInstant().toEpochMilli() // Thursday
        val monday = Trigger.Schedule(8, 0, listOf(1)).nextRunMillis(now, utc)
        assertEquals(ZonedDateTime.of(2026, 11, 23, 8, 0, 0, 0, utc).toInstant().toEpochMilli(), monday)
        // same weekday, time already passed: next week
        val thursday = Trigger.Schedule(8, 0, listOf(4)).nextRunMillis(now, utc)
        assertEquals(ZonedDateTime.of(2026, 11, 26, 8, 0, 0, 0, utc).toInstant().toEpochMilli(), thursday)
    }

    @Test
    fun describeDaysNames() {
        assertEquals("Every day", describeDays(emptyList()))
        assertEquals("Weekdays", describeDays(listOf(1, 2, 3, 4, 5)))
        assertEquals("Weekends", describeDays(listOf(7, 6)))
        assertEquals("Mon, Wed", describeDays(listOf(3, 1)))
    }

    @Test
    fun templatesAndComparisons() {
        assertEquals("Hi Ann, 5!", Templates.render("Hi {{name}}, {{ n }}!") { if (it == "name") "Ann" else if (it == "n") "5" else null })
        assertEquals("x", Templates.render("x{{missing}}") { null })
        assertEquals("3", Templates.formatNumber(3.0))
        assertEquals("2.5", Templates.formatNumber(2.5))
        assertTrue(Templates.compare("10", "9") > 0) // numeric, not text
        assertTrue(Templates.compare("abc", "abd") < 0)
        assertTrue(Comparison.GTE.test(0))
        assertTrue(!Comparison.LT.test(0))
    }

    @Test
    fun automationRoundTripsThroughJson() {
        val trigger = Trigger.Schedule(7, 15, listOf(1, 3))
        val condition = Condition.Variable("mode", Comparison.NEQ, "off")
        val actions = listOf(
            Action.ShowNotification("T", "M"),
            Action.SetVariable("n", "1", VariableMode.ADD),
            Action.RunAutomation("id-1", "Other"),
            Action.WriteLog("hi"),
            Action.RunScript("androx.log('x')"),
        )
        val a = Automation(
            id = "a1", name = "Test", trigger = trigger, condition = condition, actions = actions,
            editor = EditorKind.WORKFLOW, graph = WorkflowCompiler.fromFlow(trigger, condition, actions), createdAt = 1, updatedAt = 2,
        )
        val serializer = ListSerializer(Automation.serializer())
        val text = JsonFile.json.encodeToString(serializer, listOf(a, a.copy(id = "a2", trigger = Trigger.Manual, condition = null)))
        val back = JsonFile.json.decodeFromString(serializer, text)
        assertEquals(a, back[0])
        assertEquals(Trigger.Manual, back[1].trigger)
    }

    @Test
    fun jsonFileSurvivesCorruptionAndKeepsBackup() {
        val dir = java.nio.file.Files.createTempDirectory("androx").toFile()
        try {
            val f = File(dir, "automations.json")
            f.writeText("{ this is not json")
            val store = JsonFile(f, ListSerializer(Automation.serializer())) { emptyList() }
            assertEquals(emptyList<Automation>(), store.read())
            assertTrue(File(dir, "automations.json.corrupt").exists())
            store.write(listOf(Automation(id = "x", name = "n")))
            assertEquals("x", store.read().single().id)
        } finally {
            dir.deleteRecursively()
        }
    }
}
