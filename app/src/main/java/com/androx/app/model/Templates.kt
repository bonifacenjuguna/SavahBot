package com.androx.app.model

import kotlin.math.abs
import kotlin.math.floor

object Templates {
    private val pattern = Regex("\\{\\{\\s*([A-Za-z0-9_.-]+)\\s*}}")

    /** Replaces {{name}} with the resolved value. Unknown names become an empty string. */
    fun render(text: String, resolve: (String) -> String?): String =
        pattern.replace(text) { match -> resolve(match.groupValues[1]) ?: "" }

    fun formatNumber(value: Double): String =
        if (value == floor(value) && abs(value) < 1e15) value.toLong().toString() else value.toString()

    /** Numeric comparison when both sides are numbers, otherwise plain text ordering. */
    fun compare(left: String, right: String): Int {
        val l = left.trim().toDoubleOrNull()
        val r = right.trim().toDoubleOrNull()
        return if (l != null && r != null) l.compareTo(r) else left.compareTo(right)
    }
}
