package com.savahbot.live

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

// Plain Kotlin, no Android classes: unit-tested on a normal JVM. All numbers are pixels unless stated.

enum class Edge { LEFT, RIGHT, TOP, BOTTOM }

object Geo {
    /** The largest scale at which a window of [baseW] x [baseH] still fits the screen with [margin] spare, kept within [lo]..[hi]. */
    fun maxScale(baseW: Int, baseH: Int, screenW: Int, screenH: Int, margin: Int, lo: Float, hi: Float): Float {
        val fit = min((screenW - 2 * margin).toFloat() / baseW, (screenH - 2 * margin).toFloat() / baseH)
        return max(lo, min(hi, fit))
    }

    fun clampScale(wanted: Float, lo: Float, hiEffective: Float): Float = max(lo, min(hiEffective, wanted))

    /** Proportional resize: the scale that puts the dragged corner under the finger, given the opposite (anchor) corner. */
    fun scaleFromDrag(anchorX: Float, anchorY: Float, fingerX: Float, fingerY: Float, baseW: Int, baseH: Int): Float =
        max(abs(fingerX - anchorX) / baseW, abs(fingerY - anchorY) / baseH)

    /** The screen edge nearest to a point (the centre of the window being tucked). Ties prefer left, right, top, bottom. */
    fun nearestEdge(cx: Float, cy: Float, screenW: Int, screenH: Int): Edge {
        val l = cx
        val r = screenW - cx
        val t = cy
        val b = screenH - cy
        val best = min(min(l, r), min(t, b))
        return when (best) {
            l -> Edge.LEFT
            r -> Edge.RIGHT
            t -> Edge.TOP
            else -> Edge.BOTTOM
        }
    }

    /** If a window has been dragged far enough past an edge ([fraction] of its own size outside the screen), the edge to tuck into; otherwise null. */
    fun overshootEdge(x: Int, y: Int, w: Int, h: Int, screenW: Int, screenH: Int, fraction: Float): Edge? {
        val left = (-x).toFloat() / w
        val right = (x + w - screenW).toFloat() / w
        val top = (-y).toFloat() / h
        val bottom = (y + h - screenH).toFloat() / h
        val best = max(max(left, right), max(top, bottom))
        if (best < fraction) return null
        return when (best) {
            left -> Edge.LEFT
            right -> Edge.RIGHT
            top -> Edge.TOP
            else -> Edge.BOTTOM
        }
    }

    fun clampInto(pos: Int, size: Int, screen: Int): Int = max(0, min(pos, max(0, screen - size)))

    /** Position along an edge as a fraction 0..1 (for left/right edges that is vertical, for top/bottom horizontal). Survives rotation. */
    fun alongFraction(edge: Edge, x: Int, y: Int, w: Int, h: Int, screenW: Int, screenH: Int): Float {
        val vertical = edge == Edge.LEFT || edge == Edge.RIGHT
        val room = if (vertical) screenH - h else screenW - w
        if (room <= 0) return 0f
        val pos = if (vertical) y else x
        return max(0f, min(1f, pos.toFloat() / room))
    }

    fun alongPx(edge: Edge, fraction: Float, w: Int, h: Int, screenW: Int, screenH: Int): Int {
        val vertical = edge == Edge.LEFT || edge == Edge.RIGHT
        val room = if (vertical) screenH - h else screenW - w
        return if (room <= 0) 0 else (max(0f, min(1f, fraction)) * room).toInt()
    }

    /** Where a window sits (top-left) when flush against [edge] at [along], pushed [hidden] pixels off the screen. */
    fun flush(edge: Edge, along: Int, w: Int, h: Int, screenW: Int, screenH: Int, hidden: Int): Pair<Int, Int> = when (edge) {
        Edge.LEFT -> Pair(-hidden, along)
        Edge.RIGHT -> Pair(screenW - w + hidden, along)
        Edge.TOP -> Pair(along, -hidden)
        Edge.BOTTOM -> Pair(along, screenH - h + hidden)
    }
}
