package com.savahbot.live

import android.content.Context
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.text.TextUtils
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.animation.AccelerateInterpolator
import android.view.animation.OvershootInterpolator
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import kotlin.math.abs
import kotlin.math.min

/**
 * The panel's other form: a small rounded tab on a screen edge showing the live light, viewers and likes.
 * It is only content (no window of its own, so showing and hiding it can never fail): [Overlay] owns the one window and sizes it to [measure].
 * Two strips are built once (one upright for the left and right edges, one flat for the top and bottom) and only their visibility changes,
 * so nothing is ever added to or removed from the view tree while a finger is on it.
 * When chat arrives it can show a small card beside the tab; the card has its own size and opacity, separate from the panel's.
 */
class TabView(private val ctx: Context, private val host: Host) {
    interface Host {
        fun touched()
        fun dragStart()
        fun dragBy(dx: Int, dy: Int)
        fun dragEnd()
        fun tapped()
        fun released()
    }

    class Size(val winW: Int, val winH: Int, val boxW: Int, val boxH: Int)

    private companion object {
        const val AMBER = 0xFFF5B301.toInt()
    }

    private fun dp(v: Int): Int = dpOf(ctx, v)

    private var theme: Theme = Themes.presets[0]
    private var fontSp = 14f
    private var popScale = 100
    private var popOpacity = 95
    private var edge = Edge.RIGHT
    private var dotKind = 2
    private var viewersText = ""
    private var likesText = ""

    val view = FrameLayout(ctx)
    private val upright = Strip(true)
    private val flat = Strip(false)
    private val card = LinearLayout(ctx)
    private val line1 = TextView(ctx)
    private val line2 = TextView(ctx)

    val cardShowing: Boolean get() = card.visibility == View.VISIBLE

    init {
        card.orientation = LinearLayout.VERTICAL
        card.setPadding(dp(12), dp(8), dp(12), dp(8))
        card.visibility = View.GONE
        for (t in listOf(line1, line2)) {
            t.maxLines = 2
            t.ellipsize = TextUtils.TruncateAt.END
            t.setPadding(0, dp(2), 0, dp(2))
            t.visibility = View.GONE
            card.addView(t)
        }
        view.addView(upright.box, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT))
        view.addView(flat.box, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT))
        view.addView(card, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT))
        view.setOnTouchListener(TabTouch())
        view.contentDescription = "SavahLive. Tap to open."
        paint()
        setEdge(Edge.RIGHT)
    }

    // ---- the strips ----------------------------------------------------------------------------------------------------------------------
    private inner class Strip(val vertical: Boolean) {
        val box = LinearLayout(ctx)
        val dot = iconView(ctx, R.drawable.ic_dot, theme.muted, 12)
        val user = iconView(ctx, R.drawable.ic_user, theme.muted, 15)
        val heart = iconView(ctx, R.drawable.ic_heart, theme.heart, 14)
        val viewers = TextView(ctx)
        val likes = TextView(ctx)
        val note = TextView(ctx)            // shown instead of the numbers when the connection is down

        init {
            for (t in listOf(viewers, likes)) {
                t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
                t.setTypeface(Typeface.DEFAULT_BOLD)
                t.setSingleLine(true)
                t.gravity = Gravity.CENTER
            }
            note.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
            note.setTypeface(Typeface.DEFAULT_BOLD)
            note.setSingleLine(true)
            note.gravity = Gravity.CENTER
            note.setTextColor(AMBER)
            note.visibility = View.GONE
            if (vertical) {
                box.orientation = LinearLayout.VERTICAL
                box.gravity = Gravity.CENTER_HORIZONTAL
                box.setPadding(dp(8), dp(12), dp(8), dp(12))
                box.minimumWidth = dp(48)
                put(user, 0, 0)
                put(viewers, 2, 0)
                put(heart, 10, 0)
                put(likes, 2, 0)
                put(note, 0, 0)
            } else {
                box.orientation = LinearLayout.HORIZONTAL
                box.gravity = Gravity.CENTER_VERTICAL
                box.setPadding(dp(12), dp(7), dp(12), dp(7))
                put(user, 0, 0)
                put(viewers, 0, 4)
                put(heart, 0, 10)
                put(likes, 0, 4)
                put(note, 0, 0)
            }
        }

        private fun put(v: View, top: Int, left: Int) {
            val lp = (v.layoutParams as? LinearLayout.LayoutParams) ?: LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT)
            lp.topMargin = dp(top)
            lp.leftMargin = dp(left)
            box.addView(v, lp)
        }

        fun paint() {
            val top = Themes.mix(theme.bg, theme.text, 0.07f)
            val g = GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, intArrayOf(Themes.withAlpha(top, 96), Themes.withAlpha(theme.bg, 96)))
            g.setCornerRadius(dp(18).toFloat())
            g.setStroke(dp(1), Themes.withAlpha(theme.text, 34))
            box.background = g
            viewers.setTextColor(theme.text)
            likes.setTextColor(theme.text)
            user.setColorFilter(theme.muted)
            heart.setColorFilter(theme.heart)
            dot.setColorFilter(dotColor())
        }

        fun showNote(text: String) {
            val on = text.isNotEmpty()
            note.text = text
            note.visibility = if (on) View.VISIBLE else View.GONE
            val numbers = if (on) View.GONE else View.VISIBLE
            user.visibility = numbers
            viewers.visibility = numbers
            heart.visibility = numbers
            likes.visibility = numbers
        }

        fun set(v: String, l: String) {
            viewers.text = v
            likes.text = l
            dot.setColorFilter(dotColor())
        }
    }

    private fun dotColor(): Int = when (dotKind) {
        0 -> theme.accent
        1 -> AMBER
        else -> theme.muted
    }

    private val isVertical: Boolean get() = edge == Edge.LEFT || edge == Edge.RIGHT
    private val active: Strip get() = if (isVertical) upright else flat

    // ---- look and numbers -----------------------------------------------------------------------------------------------------------------
    fun setLook(t: Theme, baseFontSp: Float, popScalePct: Int, popOpacityPct: Int) {
        theme = t
        fontSp = baseFontSp
        popScale = popScalePct
        popOpacity = popOpacityPct
        paint()
    }

    /** Returns true when what is shown changed, so the controller knows the tab may need a new size. */
    fun setHeader(viewers: String, likes: String, dot: Int): Boolean {
        val changed = viewers != viewersText || likes != likesText || dot != dotKind
        viewersText = viewers
        likesText = likes
        dotKind = dot
        upright.set(viewers, likes)
        flat.set(viewers, likes)
        return changed
    }

    private var bannerText = ""

    /** Plain words for a bad connection, in place of the numbers. Returns true when the tab's size may have changed. */
    fun setBanner(text: String): Boolean {
        if (text == bannerText) return false
        bannerText = text
        upright.showNote(text)
        flat.showNote(text)
        return true
    }

    /** A milestone: the tab shrinks a little and springs back (it never grows past its own window, which would clip). Only its own scale changes. */
    fun pulse() {
        val b = active.box
        b.animate().cancel()
        b.pivotX = b.width / 2f
        b.pivotY = b.height / 2f
        b.scaleX = 0.78f
        b.scaleY = 0.78f
        b.animate().scaleX(1f).scaleY(1f).setDuration(420).setInterpolator(OvershootInterpolator(1.6f)).start()
    }

    private fun paint() {
        upright.paint()
        flat.paint()
        val g = GradientDrawable()
        g.setColor(Themes.withAlpha(theme.surface, popOpacity))
        g.setCornerRadius(dp(16).toFloat())
        g.setStroke(dp(1), Themes.withAlpha(theme.text, 34))
        card.background = g
        val sp = min(fontSp, 15f) * popScale / 100f
        val maxW = min((dp(210) * popScale / 100f).toInt(), (ctx.resources.displayMetrics.widthPixels * 0.7f).toInt())
        for (t in listOf(line1, line2)) {
            t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
            t.setTextColor(theme.text)
            t.maxWidth = maxW
            val line = t.tag as? Line
            if (line != null) t.text = ChatStyle.render(theme, line)
        }
        card.setPadding(dp(12 * popScale / 100), dp(8 * popScale / 100), dp(12 * popScale / 100), dp(8 * popScale / 100))
    }

    // ---- arranging for an edge -----------------------------------------------------------------------------------------------------------
    /** Puts the strip and the card in the right order and corner for [e]. Only changes visibility and layout rules, never the view tree. */
    fun setEdge(e: Edge) {
        edge = e
        upright.box.visibility = if (isVertical) View.VISIBLE else View.GONE
        flat.box.visibility = if (isVertical) View.GONE else View.VISIBLE
        arrange()
    }

    /** Layout is done in [place], from screen positions, so the strip and the card never depend on each other's size. */
    private fun arrange() {}

    /**
     * Positions the strip at the screen spot ([bx], [by]) and the card (if showing) beside it on the inner side, then returns the window
     * that holds both as [x, y, w, h]. The strip's screen position never depends on the card, so a long message only makes the card grow.
     */
    fun place(sw: Int, sh: Int, bx: Int, by: Int): IntArray {
        val s = active.box
        s.measure(View.MeasureSpec.makeMeasureSpec(sw, View.MeasureSpec.AT_MOST), View.MeasureSpec.makeMeasureSpec(sh, View.MeasureSpec.AT_MOST))
        val bw = s.measuredWidth
        val bh = s.measuredHeight
        var wx = bx
        var wy = by
        var wr = bx + bw
        var wb = by + bh
        var cx = 0
        var cy = 0
        var cw = 0
        var ch = 0
        if (cardShowing) {
            card.measure(View.MeasureSpec.makeMeasureSpec(sw, View.MeasureSpec.AT_MOST), View.MeasureSpec.makeMeasureSpec(sh, View.MeasureSpec.AT_MOST))
            cw = card.measuredWidth
            ch = card.measuredHeight
            val gap = dp(6)
            when (edge) {
                Edge.RIGHT -> { cx = bx - gap - cw; cy = Geo.clampI(by + bh / 2 - ch / 2, 0, sh - ch) }
                Edge.LEFT -> { cx = bx + bw + gap; cy = Geo.clampI(by + bh / 2 - ch / 2, 0, sh - ch) }
                Edge.TOP -> { cy = by + bh + gap; cx = Geo.clampI(bx + bw / 2 - cw / 2, 0, sw - cw) }
                Edge.BOTTOM -> { cy = by - gap - ch; cx = Geo.clampI(bx + bw / 2 - cw / 2, 0, sw - cw) }
            }
            wx = minOf(wx, cx)
            wy = minOf(wy, cy)
            wr = maxOf(wr, cx + cw)
            wb = maxOf(wb, cy + ch)
        }
        val sl = FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT)
        sl.gravity = Gravity.TOP or Gravity.LEFT
        sl.leftMargin = bx - wx
        sl.topMargin = by - wy
        s.layoutParams = sl
        if (cardShowing) {
            val cl = FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT)
            cl.gravity = Gravity.TOP or Gravity.LEFT
            cl.leftMargin = cx - wx
            cl.topMargin = cy - wy
            card.layoutParams = cl
        }
        return intArrayOf(wx, wy, wr - wx, wb - wy)
    }

    /** The size the window needs now: the strip, plus the card if one is showing. */
    fun measure(sw: Int, sh: Int): Size {
        arrange()
        val s = active.box
        s.measure(View.MeasureSpec.makeMeasureSpec(sw, View.MeasureSpec.AT_MOST), View.MeasureSpec.makeMeasureSpec(sh, View.MeasureSpec.AT_MOST))
        val bw = s.measuredWidth
        val bh = s.measuredHeight
        var w = bw
        var h = bh
        if (cardShowing) {
            card.measure(View.MeasureSpec.makeMeasureSpec(sw, View.MeasureSpec.AT_MOST), View.MeasureSpec.makeMeasureSpec(sh, View.MeasureSpec.AT_MOST))
            if (isVertical) {
                w = bw + dp(6) + card.measuredWidth
                h = maxOf(bh, card.measuredHeight)
            } else {
                w = maxOf(bw, card.measuredWidth)
                h = bh + dp(6) + card.measuredHeight
            }
        }
        return Size(w, h, bw, bh)
    }

    // ---- the pop-out card ------------------------------------------------------------------------------------------------------------------
    /** Shows the newest line or two beside the tab. */
    fun pop(lines: List<Line>) {
        if (lines.isEmpty()) return
        val newest = if (lines.size > 2) lines.subList(lines.size - 2, lines.size) else lines
        val views = listOf(line1, line2)
        val start = 2 - newest.size
        for (i in 0 until 2) {
            val t = views[i]
            if (i < start) {
                t.tag = null
                t.visibility = View.GONE
            } else {
                val line = newest[i - start]
                t.tag = line
                t.text = ChatStyle.render(theme, line)
                t.visibility = View.VISIBLE
            }
        }
        card.visibility = View.VISIBLE
        arrange()
    }

    private var cardToken = 0

    /** Springs the card out of the tab: it grows from the strip's side, slides outward and fades in, with a small overshoot. Call after the window was sized for it. */
    fun animateIn() {
        if (!cardShowing) return
        cardToken++
        card.animate().cancel()
        val w = card.measuredWidth.toFloat()
        val h = card.measuredHeight.toFloat()
        val d = dp(28).toFloat()
        var tx = 0f
        var ty = 0f
        when (edge) {
            Edge.RIGHT -> { card.pivotX = w; card.pivotY = h / 2f; tx = d }
            Edge.LEFT -> { card.pivotX = 0f; card.pivotY = h / 2f; tx = -d }
            Edge.TOP -> { card.pivotX = w / 2f; card.pivotY = 0f; ty = -d }
            Edge.BOTTOM -> { card.pivotX = w / 2f; card.pivotY = h; ty = d }
        }
        card.alpha = 0f
        card.scaleX = 0.5f
        card.scaleY = 0.5f
        card.translationX = tx
        card.translationY = ty
        card.animate().alpha(1f).scaleX(1f).scaleY(1f).translationX(0f).translationY(0f)
            .setDuration(320).setInterpolator(OvershootInterpolator(1.1f)).start()
    }

    /** Tucks the card back into the tab, then runs [done] (which removes it from the window's size). Cancelled cleanly if anything else touches the card first. */
    fun animateOut(done: () -> Unit) {
        if (!cardShowing) { done(); return }
        val token = ++cardToken
        val d = dp(16).toFloat()
        val tx = when (edge) { Edge.RIGHT -> d; Edge.LEFT -> -d; else -> 0f }
        val ty = when (edge) { Edge.TOP -> -d; Edge.BOTTOM -> d; else -> 0f }
        card.animate().cancel()
        card.animate().alpha(0f).scaleX(0.7f).scaleY(0.7f).translationX(tx).translationY(ty)
            .setDuration(180).setInterpolator(AccelerateInterpolator())
            .withEndAction { if (token == cardToken) done() }.start()
    }

    /** A new line arrived while the card is already out: a small pulse instead of a second entrance. */
    fun bump() {
        if (!cardShowing) return
        cardToken++
        card.animate().cancel()
        card.alpha = 1f
        card.translationX = 0f
        card.translationY = 0f
        card.scaleX = 0.94f
        card.scaleY = 0.94f
        card.animate().scaleX(1f).scaleY(1f).setDuration(200).setInterpolator(OvershootInterpolator(2f)).start()
    }

    private fun resetCardLook() {
        card.animate().cancel()
        card.alpha = 1f
        card.scaleX = 1f
        card.scaleY = 1f
        card.translationX = 0f
        card.translationY = 0f
    }

    fun clearCard() {
        cardToken++
        resetCardLook()
        card.visibility = View.GONE
        for (t in listOf(line1, line2)) {
            t.tag = null
            t.visibility = View.GONE
        }
        arrange()
    }

    // ---- touch: a tap opens the panel, a drag moves the tab ----------------------------------------------------------------------------------
    private inner class TabTouch : View.OnTouchListener {
        private var downX = 0f
        private var downY = 0f
        private var moved = false
        private val slop = ViewConfiguration.get(ctx).scaledTouchSlop

        override fun onTouch(v: View, e: MotionEvent): Boolean {
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = e.rawX
                    downY = e.rawY
                    moved = false
                    host.touched()
                    return true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX
                    val dy = e.rawY - downY
                    if (!moved && (abs(dx) > slop || abs(dy) > slop)) {
                        moved = true
                        host.dragStart()
                    }
                    if (moved) host.dragBy(dx.toInt(), dy.toInt())
                    return true
                }
                MotionEvent.ACTION_UP -> {
                    if (moved) host.dragEnd() else host.tapped()
                    return true
                }
                MotionEvent.ACTION_CANCEL -> {
                    if (moved) host.dragEnd() else host.released()
                    return true
                }
            }
            return false
        }
    }
}
