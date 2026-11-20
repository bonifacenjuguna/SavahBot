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

        init {
            for (t in listOf(viewers, likes)) {
                t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
                t.setTypeface(Typeface.DEFAULT_BOLD)
                t.setSingleLine(true)
                t.gravity = Gravity.CENTER
            }
            if (vertical) {
                box.orientation = LinearLayout.VERTICAL
                box.gravity = Gravity.CENTER_HORIZONTAL
                box.setPadding(dp(8), dp(12), dp(8), dp(12))
                box.minimumWidth = dp(48)
                put(dot, 0, 0)
                put(user, 10, 0)
                put(viewers, 2, 0)
                put(heart, 10, 0)
                put(likes, 2, 0)
            } else {
                box.orientation = LinearLayout.HORIZONTAL
                box.gravity = Gravity.CENTER_VERTICAL
                box.setPadding(dp(14), dp(8), dp(14), dp(8))
                put(dot, 0, 0)
                put(user, 0, 10)
                put(viewers, 0, 4)
                put(heart, 0, 12)
                put(likes, 0, 4)
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

    private fun arrange() {
        val s = active.box
        s.measure(View.MeasureSpec.makeMeasureSpec(ctx.resources.displayMetrics.widthPixels, View.MeasureSpec.AT_MOST), View.MeasureSpec.makeMeasureSpec(ctx.resources.displayMetrics.heightPixels, View.MeasureSpec.AT_MOST))
        val gap = dp(6)
        val boxLp = FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT)
        val cardLp = FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT)
        when (edge) {
            Edge.RIGHT -> {
                boxLp.gravity = Gravity.RIGHT or Gravity.CENTER_VERTICAL
                cardLp.gravity = Gravity.RIGHT or Gravity.CENTER_VERTICAL
                cardLp.rightMargin = s.measuredWidth + gap
            }
            Edge.LEFT -> {
                boxLp.gravity = Gravity.LEFT or Gravity.CENTER_VERTICAL
                cardLp.gravity = Gravity.LEFT or Gravity.CENTER_VERTICAL
                cardLp.leftMargin = s.measuredWidth + gap
            }
            Edge.TOP -> {
                boxLp.gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
                cardLp.gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
                cardLp.topMargin = s.measuredHeight + gap
            }
            Edge.BOTTOM -> {
                boxLp.gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
                cardLp.gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
                cardLp.bottomMargin = s.measuredHeight + gap
            }
        }
        s.layoutParams = boxLp
        card.layoutParams = cardLp
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

    fun clearCard() {
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
