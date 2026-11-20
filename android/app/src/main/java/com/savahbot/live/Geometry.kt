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

    // ---- the free-form panel: which edge or corner a touch is on, and what resizing it does ---------------------------------------------------
    const val L = 1
    const val T = 2
    const val R = 4
    const val B = 8

    /** Never throws, unlike coerceIn: if the limits cross, the lower one wins. */
    fun clampI(v: Int, lo: Int, hi: Int): Int = max(lo, min(hi, v))

    /**
     * Which edges a touch at ([x], [y]) is holding in a window of [w] x [h]: a bit mask of [L], [T], [R], [B] (two bits = a corner), 0 = none of them.
     * [edge] is how thick the side bands are (the top one is [topEdge], thinner so it does not eat the header's buttons); [corner] is the square at each corner.
     */
    fun hitMode(x: Float, y: Float, w: Int, h: Int, edge: Int, topEdge: Int, corner: Int): Int {
        var m = 0
        val nearL = x < edge
        val nearR = x > w - edge
        val nearT = y < topEdge
        val nearB = y > h - edge
        if (nearL) m = m or L
        if (nearR) m = m or R
        if (nearT) m = m or T
        if (nearB) m = m or B
        // a bigger square at each corner, so a corner is easy to catch
        if (x < corner && y < corner) m = m or L or T
        if (x > w - corner && y < corner) m = m or R or T
        if (x < corner && y > h - corner) m = m or L or B
        if (x > w - corner && y > h - corner) m = m or R or B
        return m
    }

    /**
     * The new window rectangle (x, y, width, height) when the edges in [mode] are dragged by ([dx], [dy]) from the rectangle ([x], [y], [w], [h]).
     * The window stays at least [minW] x [minH], at most [maxW] x [maxH], and inside the screen. The side that is not being dragged never moves.
     */
    fun resize(mode: Int, x: Int, y: Int, w: Int, h: Int, dx: Int, dy: Int, minW: Int, minH: Int, maxW: Int, maxH: Int, screenW: Int, screenH: Int): IntArray {
        var left = x
        var top = y
        var right = x + w
        var bottom = y + h
        if ((mode and L) != 0) left = clampI(x + dx, max(0, right - maxW), right - minW)
        if ((mode and R) != 0) right = clampI(x + w + dx, left + minW, min(screenW, left + maxW))
        if ((mode and T) != 0) top = clampI(y + dy, max(0, bottom - maxH), bottom - minH)
        if ((mode and B) != 0) bottom = clampI(y + h + dy, top + minH, min(screenH, top + maxH))
        return intArrayOf(left, top, right - left, bottom - top)
    }

    /** The size the expanded window takes: most of the screen, but never silly on a tablet. Returns width, height. */
    fun expandedSize(screenW: Int, screenH: Int, margin: Int, maxW: Int, maxH: Int): IntArray =
        intArrayOf(min(maxW, screenW - 2 * margin), min(maxH, (screenH * 0.72f).toInt() - margin))
}
