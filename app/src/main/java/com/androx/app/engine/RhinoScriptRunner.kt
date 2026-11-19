package com.androx.app.engine

import org.mozilla.javascript.BaseFunction
import org.mozilla.javascript.ClassShutter
import org.mozilla.javascript.Context
import org.mozilla.javascript.ContextFactory
import org.mozilla.javascript.RhinoException
import org.mozilla.javascript.Scriptable
import org.mozilla.javascript.ScriptableObject
import org.mozilla.javascript.Undefined
import org.mozilla.javascript.WrappedException

/** The controlled surface a script can touch. Nothing else from the app or Android is reachable. */
interface ScriptHost {
    fun log(message: String)
    fun notify(title: String, message: String)
    fun getVar(name: String): String?
    fun setVar(name: String, value: String)
    fun deleteVar(name: String)
    fun batteryLevel(): Int
    fun isCharging(): Boolean
    fun nowMillis(): Long
}

sealed interface ScriptResult {
    data object Success : ScriptResult
    data class Failure(val message: String) : ScriptResult
}

interface ScriptRunner {
    /** Blocking. Call from a background dispatcher. */
    fun run(source: String, host: ScriptHost): ScriptResult
}

/** Documentation for the API, shown in the script editor. Keep in sync with [RhinoScriptRunner.installApi]. */
object ScriptApiDocs {
    data class Entry(val signature: String, val description: String)

    val entries = listOf(
        Entry("androx.log(...values)", "Adds a line to this run's log (also available as console.log)."),
        Entry("androx.notify(title, message)", "Shows an Android notification. Fails the run if notifications are blocked."),
        Entry("androx.getVar(name)", "Returns a variable as a string, or null if it isn't set."),
        Entry("androx.setVar(name, value)", "Stores a variable (converted to text). Visible to every automation."),
        Entry("androx.deleteVar(name)", "Removes a variable."),
        Entry("androx.battery()", "Battery level, 0–100."),
        Entry("androx.isCharging()", "true while the device is charging."),
        Entry("androx.now()", "Current time in milliseconds since 1970."),
    )
}

private class ScriptTimeoutError : Error("Script timed out")

private class DeadlineFactory(private val deadlineNanos: Long) : ContextFactory() {
    @Volatile
    var timedOut = false

    override fun makeContext(): Context {
        val cx = super.makeContext()
        cx.optimizationLevel = -1 // interpreted mode: required on Android (no bytecode generation)
        cx.languageVersion = Context.VERSION_ES6
        cx.instructionObserverThreshold = 10_000
        return cx
    }

    override fun observeInstructionCount(cx: Context, instructionCount: Int) {
        if (System.nanoTime() > deadlineNanos) {
            timedOut = true
            throw ScriptTimeoutError()
        }
    }
}

private class HostFunction(
    private val functionName: String,
    private val body: (Array<out Any?>) -> Any?,
) : BaseFunction() {
    override fun getFunctionName(): String = functionName

    override fun call(cx: Context, scope: Scriptable, thisObj: Scriptable?, args: Array<out Any?>): Any? = body(args)
}

/**
 * Executes user JavaScript with Mozilla Rhino in interpreted mode.
 * Sandbox: safe standard objects only (no Packages/java access), a ClassShutter that hides every Java class,
 * and an instruction-count deadline so `while (true) {}` can't hang the app.
 */
class RhinoScriptRunner(private val timeoutMillis: Long = 5_000) : ScriptRunner {

    override fun run(source: String, host: ScriptHost): ScriptResult {
        val factory = DeadlineFactory(System.nanoTime() + timeoutMillis * 1_000_000L)
        val cx = factory.enterContext()
        try {
            cx.setClassShutter(ClassShutter { false })
            val scope = cx.initSafeStandardObjects()
            installApi(cx, scope, host)
            cx.evaluateString(scope, source, "script", 1, null)
            return ScriptResult.Success
        } catch (t: Throwable) {
            return ScriptResult.Failure(describe(t, factory))
        } finally {
            Context.exit()
        }
    }

    private fun describe(t: Throwable, factory: DeadlineFactory): String = when {
        factory.timedOut -> "Script stopped: it ran for more than ${timeoutMillis / 1000.0} seconds."
        t is WrappedException -> {
            val inner = t.wrappedException
            (inner?.message ?: inner?.javaClass?.simpleName ?: "Script failed") + lineSuffix(t)
        }
        t is RhinoException -> "${t.details()}${lineSuffix(t)}"
        else -> t.message ?: t.javaClass.simpleName
    }

    private fun lineSuffix(e: RhinoException): String = if (e.lineNumber() > 0) " (line ${e.lineNumber()})" else ""

    private fun installApi(cx: Context, scope: Scriptable, host: ScriptHost) {
        val androx = cx.newObject(scope)
        val console = cx.newObject(scope)

        fun define(target: Scriptable, name: String, body: (Array<out Any?>) -> Any?) {
            val fn = HostFunction(name, body)
            fn.parentScope = scope
            fn.prototype = ScriptableObject.getFunctionPrototype(scope)
            ScriptableObject.putProperty(target, name, fn)
        }

        fun text(args: Array<out Any?>, i: Int): String = if (i < args.size) Context.toString(args[i]) else ""

        val logFn: (Array<out Any?>) -> Any? = { args ->
            host.log(args.joinToString(" ") { Context.toString(it) })
            Undefined.instance
        }
        define(androx, "log", logFn)
        define(console, "log", logFn)
        define(androx, "notify") { args ->
            host.notify(text(args, 0), text(args, 1))
            Undefined.instance
        }
        define(androx, "getVar") { args -> host.getVar(text(args, 0)) }
        define(androx, "setVar") { args ->
            val name = text(args, 0).trim()
            if (name.isEmpty()) throw ActionException("setVar needs a variable name.")
            host.setVar(name, text(args, 1))
            Undefined.instance
        }
        define(androx, "deleteVar") { args ->
            host.deleteVar(text(args, 0))
            Undefined.instance
        }
        define(androx, "battery") { host.batteryLevel().toDouble() }
        define(androx, "isCharging") { host.isCharging() }
        define(androx, "now") { host.nowMillis().toDouble() }
        ScriptableObject.putProperty(androx, "version", "0.0.0")

        ScriptableObject.putProperty(scope, "androx", androx)
        ScriptableObject.putProperty(scope, "console", console)
    }
}
