package com.androx.app.samples

import com.androx.app.model.Action
import com.androx.app.model.Automation
import com.androx.app.model.Comparison
import com.androx.app.model.Condition
import com.androx.app.model.EditorKind
import com.androx.app.model.Trigger
import com.androx.app.model.WorkflowCompiler
import java.util.UUID

/** One starter automation per editor, so every part of the app can be tried straight away. */
object Samples {
    fun create(now: Long): List<Automation> {
        val workflowTrigger = Trigger.Manual
        val workflowCondition = Condition.BatteryLevel(Comparison.LT, 30)
        val workflowActions = listOf<Action>(
            Action.ShowNotification("Battery is {{battery}}%", "Time to plug in. Sent by a visual workflow at {{time}}.")
        )
        return listOf(
            Automation(
                id = UUID.randomUUID().toString(),
                name = "Hello, Androx",
                trigger = Trigger.Manual,
                actions = listOf(
                    Action.SetVariable("greetings", "1", com.androx.app.model.VariableMode.ADD),
                    Action.ShowNotification("Hello from Androx", "Built with the Builder. Greeting number {{greetings}}."),
                ),
                editor = EditorKind.BUILDER,
                createdAt = now,
                updatedAt = now,
            ),
            Automation(
                id = UUID.randomUUID().toString(),
                name = "Run counter (JavaScript)",
                trigger = Trigger.Manual,
                actions = listOf(Action.RunScript()),
                editor = EditorKind.SCRIPT,
                createdAt = now,
                updatedAt = now,
            ),
            Automation(
                id = UUID.randomUUID().toString(),
                name = "Low battery notice (workflow)",
                trigger = workflowTrigger,
                condition = workflowCondition,
                actions = workflowActions,
                editor = EditorKind.WORKFLOW,
                graph = WorkflowCompiler.fromFlow(workflowTrigger, workflowCondition, workflowActions),
                createdAt = now,
                updatedAt = now,
            ),
        )
    }
}
