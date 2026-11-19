package com.savahbot.live

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.text.TextUtils
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.view.animation.DecelerateInterpolator
import android.widget.LinearLayout
import android.widget.TextView
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * The panel's other form: a small box on a screen edge with the live dot, viewers and likes.
 * - It can sit on the left, right, top or bottom edge, anywhere along it: drag it and let go, it snaps to the nearest edge.
 * - After a few seconds untouched it slides almost completely out of sight (only a sliver stays) and fades to the opacity you chose.
 * - When new chat arrives it slides out and a small card shows the latest line(s) for the pop-out time, then it tucks away again.
 * - Tap it to open the full panel.
 * Owns its own window.
 */
class TabWindow(
    private val ctx: Context,
    private val wm: WindowManager,
    private val store: Store,
    private val onOpen: () -> Unit
) {
    private val main = Handler(Looper.getMainLooper())
    private fun dp(v: Int): Int = dpOf(ctx, v)
    private fun screenW(): Int = ctx.resources.displayMetrics.widthPixels
    private fun screenH(): Int = ctx.resources.displayMetrics.heightPixels

    private var theme: Theme = Themes.presets[0]
    private var tabFade = 45
    private var hideSeconds = 3
    private var peekSeconds = 5
    private var fontSp = 14f
    private var edge = Edge.RIGHT
    private var along = 0.4f
    private var hiddenF = 0f            // 0 = fully out, 1 = tucked away (only a sliver shows)
    private var added = false
    private var dragging = false
    private var cardShowing = false
    private var dotKind = 2
    private var anim: ValueAnimator? = null
    private val sliver = dp(14)

    private val root = LinearLayout(ctx)
    private val box = LinearLayout(ctx)
    private val card = LinearLayout(ctx)
    private val dotIv = iconView(ctx, R.drawable.ic_dot, theme.muted, 12)
    private val eyeIv = iconView(ctx, R.drawable.ic_eye, theme.muted, 14)
    private val heartIv = iconView(ctx, R.drawable.ic_heart, theme.heart, 13)
    private val viewersTv = TextView(ctx)
    private val likesTv = TextView(ctx)

    private val params = WindowManager.LayoutParams(
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
        PixelFormat.TRANSLUCENT
    )

    private val hideRun = Runnable { if (!dragging && !cardShowing) animateHidden(1f) }
    private val cardRun = Runnable { clearCard() }

    init {
        for (t in listOf(viewersTv, likesTv)) {
            t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
            t.setTypeface(Typeface.DEFAULT_BOLD)
            t.setSingleLine(true)
            t.gravity = Gravity.CENTER
        }
        card.orientation = LinearLayout.VERTICAL
        card.setPadding(dp(12), dp(8), dp(12), dp(8))
        card.visibility = View.GONE
        root.gravity = Gravity.CENTER
        val drag = DragListener()
        box.setOnTouchListener(drag)
        card.setOnTouchListener(drag)
        box.contentDescription = "SavahLive. Tap to open."
    }

    private val vertical: Boolean get() = edge == Edge.LEFT || edge == Edge.RIGHT

    // ---------------------------------------------------------------------------------------------------------------------------------------
    fun show(tuckInto: Edge?, alongFrac: Float?): Boolean {
        if (added) return true
        if (tuckInto != null) {
            edge = tuckInto
            if (alongFrac != null) along = alongFrac
            save()
        } else {
            edge = Edge.values().getOrElse(store.tabEdge) { Edge.RIGHT }
            along = store.tabAlong / 1000f
        }
        hiddenF = 0f
        orient()
        paint()
        place()
        return try {
            wm.addView(root, params)
            added = true
            scheduleHide()
            true
        } catch (e: Exception) {
            false
        }
    }

    fun hide() {
        main.removeCallbacksAndMessages(null)
        anim?.cancel()
        anim = null
        if (added) {
            try {
                wm.removeView(root)
            } catch (e: Exception) {
                // already gone
            }
        }
        added = false
        cardShowing = false
        card.visibility = View.GONE
        card.removeAllViews()
    }

    fun isShowing(): Boolean = added

    fun onScreenChanged() {
        if (added) place()
    }

    fun setLook(t: Theme, tabFadePct: Int, hideAfter: Int, peekFor: Int, baseFontSp: Float) {
        theme = t
        tabFade = tabFadePct
        hideSeconds = hideAfter
        peekSeconds = peekFor
        fontSp = baseFontSp
        paint()
        if (added) {
            place()
            scheduleHide()
        }
    }

    fun setHeader(viewers: String, likes: String, dot: Int) {
        viewersTv.text = viewers
        likesTv.text = likes
        dotKind = dot
        dotIv.setColorFilter(dotColor())
        if (added) place()
    }

    /** New chat: slide out, show the latest line or two, then tuck away after the pop-out time. */
    fun pop(lines: List<Line>) {
        if (!added || dragging || lines.isEmpty()) return
        val newest = if (lines.size > 2) lines.subList(lines.size - 2, lines.size) else lines
        for (l in newest) {
            val tv = TextView(ctx)
            tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, min(fontSp, 15f))
            tv.setTextColor(theme.text)
            tv.maxLines = 2
            tv.ellipsize = TextUtils.TruncateAt.END
            tv.maxWidth = min(dp(250), (screenW() * 0.66f).toInt())
            tv.setPadding(0, dp(2), 0, dp(2))
            tv.text = ChatStyle.render(theme, l)
            card.addView(tv)
        }
        while (card.childCount > 2) card.removeViewAt(0)
        card.visibility = View.VISIBLE
        cardShowing = true
        main.removeCallbacks(hideRun)
        animateHidden(0f)
        main.removeCallbacks(cardRun)
        main.postDelayed(cardRun, peekSeconds * 1000L)
        place()
    }

    private fun clearCard() {
        main.removeCallbacks(cardRun)
        cardShowing = false
        card.visibility = View.GONE
        card.removeAllViews()
        if (added) place()
        scheduleHide()
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    private fun dotColor(): Int = when (dotKind) {
        0 -> theme.accent
        1 -> 0xFFF5B301.toInt()
        else -> theme.muted
    }

    private fun paint() {
        val bg = GradientDrawable()
        bg.setColor(Themes.withAlpha(theme.bg, 96))
        bg.setCornerRadius(dp(14).toFloat())
        bg.setStroke(dp(1), Themes.withAlpha(theme.text, 30))
        box.background = bg
        val cardBg = GradientDrawable()
        cardBg.setColor(Themes.withAlpha(theme.surface, 96))
        cardBg.setCornerRadius(dp(14).toFloat())
        cardBg.setStroke(dp(1), Themes.withAlpha(theme.text, 30))
        card.background = cardBg
        viewersTv.setTextColor(theme.text)
        likesTv.setTextColor(theme.text)
        eyeIv.setColorFilter(theme.muted)
        heartIv.setColorFilter(theme.heart)
        dotIv.setColorFilter(dotColor())
        for (i in 0 until card.childCount) (card.getChildAt(i) as? TextView)?.setTextColor(theme.text)
    }

    /** Icons keep their fixed size; text views (which have no layout params yet) wrap their content. */
    private fun lpFor(v: View): LinearLayout.LayoutParams {
        val lp = v.layoutParams
        return if (lp != null && lp.width > 0 && lp.height > 0) LinearLayout.LayoutParams(lp.width, lp.height)
        else LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT)
    }

    /** Arranges the box (and the pop-out card beside it) for the current edge. */
    private fun orient() {
        box.removeAllViews()
        root.removeAllViews()
        val gap = dp(6)
        if (vertical) {
            box.orientation = LinearLayout.VERTICAL
            box.gravity = Gravity.CENTER_HORIZONTAL
            box.setPadding(dp(6), dp(10), dp(6), dp(10))
            box.minimumWidth = dp(52)
            for (v in listOf<View>(dotIv, eyeIv, viewersTv, heartIv, likesTv)) {
                box.addView(v, lpFor(v).also { it.topMargin = if (v === eyeIv || v === heartIv) gap else 2 })
            }
            root.orientation = LinearLayout.HORIZONTAL
        } else {
            box.orientation = LinearLayout.HORIZONTAL
            box.gravity = Gravity.CENTER_VERTICAL
            box.setPadding(dp(12), dp(7), dp(12), dp(7))
            box.minimumWidth = 0
            for (v in listOf<View>(dotIv, eyeIv, viewersTv, heartIv, likesTv)) {
                box.addView(v, lpFor(v).also { it.leftMargin = if (v === dotIv) 0 else if (v === heartIv) dp(10) else dp(5) })
            }
            root.orientation = LinearLayout.VERTICAL
        }
        val boxFirst = edge == Edge.LEFT || edge == Edge.TOP
        val lp = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT)
        if (vertical) { if (boxFirst) lp.leftMargin = gap else lp.rightMargin = gap } else { if (boxFirst) lp.topMargin = gap else lp.bottomMargin = gap }
        if (boxFirst) {
            root.addView(box)
            root.addView(card, lp)
        } else {
            root.addView(card, lp)
            root.addView(box)
        }
    }

    private fun measureRoot() {
        root.measure(
            View.MeasureSpec.makeMeasureSpec(screenW(), View.MeasureSpec.AT_MOST),
            View.MeasureSpec.makeMeasureSpec(screenH(), View.MeasureSpec.AT_MOST)
        )
    }

    private fun boxSize(): Pair<Int, Int> {
        box.measure(
            View.MeasureSpec.makeMeasureSpec(screenW(), View.MeasureSpec.AT_MOST),
            View.MeasureSpec.makeMeasureSpec(screenH(), View.MeasureSpec.AT_MOST)
        )
        return Pair(box.measuredWidth, box.measuredHeight)
    }

    /** Puts the window flush against its edge, pushed out of sight by [hiddenF], anchored to that edge so a growing pop-out card never shifts it. */
    private fun place() {
        val sw = screenW()
        val sh = screenH()
        val (bw, bh) = boxSize()
        measureRoot()
        val winW = root.measuredWidth
        val winH = root.measuredHeight
        val extent = if (vertical) bw else bh
        val hidden = ((extent - sliver) * hiddenF).toInt()
        val alongBox = Geo.alongPx(edge, along, bw, bh, sw, sh)
        when (edge) {
            Edge.LEFT -> {
                params.gravity = Gravity.TOP or Gravity.LEFT
                params.x = -hidden
                params.y = Geo.clampInto(alongBox - (winH - bh) / 2, winH, sh)
            }
            Edge.RIGHT -> {
                params.gravity = Gravity.TOP or Gravity.RIGHT
                params.x = -hidden
                params.y = Geo.clampInto(alongBox - (winH - bh) / 2, winH, sh)
            }
            Edge.TOP -> {
                params.gravity = Gravity.TOP or Gravity.LEFT
                params.x = Geo.clampInto(alongBox - (winW - bw) / 2, winW, sw)
                params.y = -hidden
            }
            Edge.BOTTOM -> {
                params.gravity = Gravity.BOTTOM or Gravity.LEFT
                params.x = Geo.clampInto(alongBox - (winW - bw) / 2, winW, sw)
                params.y = -hidden
            }
        }
        root.alpha = 1f - (1f - tabFade / 100f) * hiddenF
        update()
    }

    private fun update() {
        if (!added) return
        try {
            wm.updateViewLayout(root, params)
        } catch (e: Exception) {
            // the window is being torn down
        }
    }

    private fun animateHidden(to: Float) {
        anim?.cancel()
        if (abs(hiddenF - to) < 0.001f) return
        val a = ValueAnimator.ofFloat(hiddenF, to)
        a.duration = if (to > hiddenF) 260 else 180
        a.interpolator = DecelerateInterpolator()
        a.addUpdateListener {
            hiddenF = it.animatedValue as Float
            place()
        }
        anim = a
        a.start()
    }

    private fun scheduleHide() {
        main.removeCallbacks(hideRun)
        if (hideSeconds > 0 && added) main.postDelayed(hideRun, hideSeconds * 1000L)
    }

    private fun save() {
        store.tabEdge = edge.ordinal
        store.tabAlong = (along * 1000).toInt()
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    private inner class DragListener : View.OnTouchListener {
        private var downX = 0f
        private var downY = 0f
        private var startX = 0
        private var startY = 0
        private var moved = false
        private val slop = ViewConfiguration.get(ctx).scaledTouchSlop

        override fun onTouch(v: View, e: MotionEvent): Boolean {
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = e.rawX
                    downY = e.rawY
                    moved = false
                    main.removeCallbacks(hideRun)
                    animateHidden(0f)
                    return true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX
                    val dy = e.rawY - downY
                    if (!moved && (abs(dx) > slop || abs(dy) > slop)) {
                        moved = true
                        beginDrag()
                        startX = params.x
                        startY = params.y
                    }
                    if (moved) {
                        params.x = Geo.clampInto((startX + dx).toInt(), root.width, screenW())
                        params.y = Geo.clampInto((startY + dy).toInt(), root.height, screenH())
                        update()
                    }
                    return true
                }
                MotionEvent.ACTION_UP -> {
                    if (moved) endDrag() else onOpen()
                    return true
                }
                MotionEvent.ACTION_CANCEL -> {
                    if (moved) endDrag() else scheduleHide()
                    return true
                }
            }
            return false
        }
    }

    /** From edge-anchored to free positioning, so the tab follows the finger anywhere. */
    private fun beginDrag() {
        dragging = true
        anim?.cancel()
        hiddenF = 0f
        main.removeCallbacks(cardRun)
        cardShowing = false
        card.visibility = View.GONE
        card.removeAllViews()
        measureRoot()
        val w = root.measuredWidth
        val h = root.measuredHeight
        val (bw, bh) = boxSize()
        val along0 = Geo.alongPx(edge, along, bw, bh, screenW(), screenH())
        val (x, y) = Geo.flush(edge, along0, w, h, screenW(), screenH(), 0)
        params.gravity = Gravity.TOP or Gravity.LEFT
        params.x = x
        params.y = y
        root.alpha = 1f
        update()
    }

    /** Let go: snap to the nearest edge and slide there. */
    private fun endDrag() {
        val sw = screenW()
        val sh = screenH()
        val w = max(1, root.width)
        val h = max(1, root.height)
        val e = Geo.nearestEdge(params.x + w / 2f, params.y + h / 2f, sw, sh)
        val fraction = Geo.alongFraction(e, params.x, params.y, w, h, sw, sh)
        edge = e
        along = fraction
        orient()
        val (bw, bh) = boxSize()
        measureRoot()
        val tw = root.measuredWidth
        val th = root.measuredHeight
        val target = Geo.flush(e, Geo.alongPx(e, fraction, bw, bh, sw, sh), tw, th, sw, sh, 0)
        val fromX = params.x
        val fromY = params.y
        val a = ValueAnimator.ofFloat(0f, 1f)
        a.duration = 200
        a.interpolator = DecelerateInterpolator()
        a.addUpdateListener {
            val t = it.animatedValue as Float
            params.x = (fromX + (target.first - fromX) * t).toInt()
            params.y = (fromY + (target.second - fromY) * t).toInt()
            update()
        }
        a.addListener(object : android.animation.AnimatorListenerAdapter() {
            override fun onAnimationEnd(animation: android.animation.Animator) {
                dragging = false
                save()
                place()
                scheduleHide()
            }
        })
        anim = a
        a.start()
    }
}
