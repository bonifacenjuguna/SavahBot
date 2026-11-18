package com.savahbot.live

import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.TextUtils
import android.text.style.ForegroundColorSpan
import android.text.style.StyleSpan
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * The floating window. Three shapes of the same window:
 *  - compact: a small pill with the live dot, viewers and likes. A new chat line slides out under it for a few seconds, then tucks away.
 *  - docked: the compact pill pushed flush against the left, right or top edge (drag it there and let go).
 *  - expanded: tap the pill for a bigger window with the recent chat. The minimise button returns to the pill.
 * Long-press the pill (or tap the half-moon button when expanded) to cycle Solid, Glass and Ghost (no background, text only).
 * Everything here runs on the main thread. It draws what SavahBot sent; it decides nothing.
 */
class Overlay(private val ctx: Context, private val store: Store, private val onClose: () -> Unit) {
    private enum class Dock { NONE, LEFT, RIGHT, TOP }

    private val wm = ctx.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val main = Handler(Looper.getMainLooper())
    private val density = ctx.resources.displayMetrics.density

    private fun dp(v: Int): Int = (v * density + 0.5f).toInt()
    private fun screenW(): Int = ctx.resources.displayMetrics.widthPixels
    private fun screenH(): Int = ctx.resources.displayMetrics.heightPixels

    private var expanded = false
    private var dock = Dock.NONE
    private var opacity = store.opacity
    private var added = false
    private var link = Link.CONNECTING
    private var detail = ""
    private var state = State("live", false, "")
    private var stats: Stats? = null
    private var lastData = 0L
    private var prefs = Prefs(40, 5, 14)
    private var notice = ""

    private val dot = View(ctx)
    private val statsView = TextView(ctx)
    private val spacer = View(ctx)
    private val btnOpacity = headerButton("\u25D0")
    private val btnMin = headerButton("\u2013")
    private val btnClose = headerButton("\u2715")
    private val header = LinearLayout(ctx)
    private val statusView = TextView(ctx)
    private val ticker = LinearLayout(ctx)
    private val list = LinearLayout(ctx)
    private val scroll = ScrollView(ctx)
    private val root = LinearLayout(ctx)

    private val rows = ArrayList<TextView>()        // chat lines in the big window
    private val ticks = ArrayList<TextView>()       // the last couple of lines shown under the pill
    private val shown = HashSet<Long>()             // ids on screen, so a reconnect never repeats a line

    private val params = WindowManager.LayoutParams(
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
        PixelFormat.TRANSLUCENT
    )

    private val hideTicker = Runnable { clearTicker() }
    private val staleCheck = Runnable { redraw() }

    private fun headerButton(symbol: String): TextView {
        val t = TextView(ctx)
        t.text = symbol
        t.setTextColor(Color.WHITE)
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
        t.gravity = Gravity.CENTER
        t.minimumWidth = dp(36)
        t.minimumHeight = dp(36)
        t.visibility = View.GONE
        return t
    }

    init {
        params.gravity = Gravity.TOP or Gravity.LEFT

        dot.layoutParams = LinearLayout.LayoutParams(dp(10), dp(10)).apply { rightMargin = dp(8) }
        statsView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        statsView.setTextColor(Color.WHITE)
        statsView.setTypeface(Typeface.DEFAULT_BOLD)
        statsView.setSingleLine(true)

        header.orientation = LinearLayout.HORIZONTAL
        header.gravity = Gravity.CENTER_VERTICAL
        header.setPadding(dp(12), dp(6), dp(10), dp(6))
        header.addView(dot)
        header.addView(statsView)
        header.addView(spacer, LinearLayout.LayoutParams(0, 1, 1f))
        header.addView(btnOpacity)
        header.addView(btnMin)
        header.addView(btnClose)
        header.setOnTouchListener(DragListener())

        statusView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
        statusView.setPadding(dp(12), 0, dp(12), dp(6))
        statusView.visibility = View.GONE

        ticker.orientation = LinearLayout.VERTICAL
        ticker.setPadding(dp(12), 0, dp(12), dp(8))
        ticker.visibility = View.GONE

        list.orientation = LinearLayout.VERTICAL
        list.setPadding(dp(12), 0, dp(12), dp(8))
        scroll.addView(list)
        scroll.visibility = View.GONE

        root.orientation = LinearLayout.VERTICAL
        root.gravity = Gravity.LEFT
        root.addView(header)
        root.addView(statusView)
        root.addView(ticker)
        root.addView(scroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))

        btnClose.setOnClickListener { onClose() }
        btnMin.setOnClickListener { setExpanded(false) }
        btnOpacity.setOnClickListener { cycleOpacity() }
    }

    // ---------------------------------------------------------------------------------------------- window
    fun show(): Boolean {
        if (added) return true
        dock = Dock.values().getOrElse(store.dock) { Dock.NONE }
        params.x = if (store.posX >= 0) store.posX else max(0, screenW() - dp(170))
        params.y = if (store.posY >= 0) store.posY else dp(120)
        params.gravity = Gravity.TOP or Gravity.LEFT
        applyDock()
        clamp()
        applyLook()
        redraw()
        return try {
            wm.addView(root, params)
            added = true
            true
        } catch (e: Exception) {
            false          // no overlay permission, or the system refused: the service stops
        }
    }

    fun hide() {
        main.removeCallbacksAndMessages(null)
        if (added) {
            try {
                wm.removeView(root)
            } catch (e: Exception) {
                // already gone
            }
        }
        added = false
    }

    private fun update() {
        if (!added) return
        try {
            wm.updateViewLayout(root, params)
        } catch (e: Exception) {
            // the window is being torn down
        }
    }

    fun setLocked(on: Boolean) {
        params.flags = if (on) params.flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        else params.flags and WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE.inv()
        update()
    }

    fun onScreenChanged() {
        toAbsolute()
        if (expanded) sizeExpanded()
        applyDock()
        clamp()
        update()
    }

    private fun isRight(): Boolean = (params.gravity and Gravity.RIGHT) == Gravity.RIGHT

    private fun widthNow(): Int = if (params.width > 0) params.width else if (root.width > 0) root.width else dp(160)
    private fun heightNow(): Int = if (params.height > 0) params.height else if (root.height > 0) root.height else dp(44)

    /** While dragging the window is positioned from its left edge; a right-docked window is anchored to the right edge, so convert first. */
    private fun toAbsolute() {
        if (isRight()) {
            params.x = max(0, screenW() - widthNow() - params.x)
            params.gravity = Gravity.TOP or Gravity.LEFT
        }
    }

    private fun clamp() {
        if (!isRight()) params.x = params.x.coerceIn(0, max(0, screenW() - widthNow()))
        params.y = params.y.coerceIn(0, max(0, screenH() - heightNow()))
    }

    private fun applyDock() {
        if (expanded) return
        when (dock) {
            Dock.LEFT -> {
                params.gravity = Gravity.TOP or Gravity.LEFT
                params.x = 0
            }
            Dock.RIGHT -> {
                params.gravity = Gravity.TOP or Gravity.RIGHT
                params.x = 0
            }
            Dock.TOP -> {
                params.gravity = Gravity.TOP or Gravity.LEFT
                params.y = 0
            }
            Dock.NONE -> params.gravity = Gravity.TOP or Gravity.LEFT
        }
        root.gravity = if (dock == Dock.RIGHT) Gravity.RIGHT else Gravity.LEFT
    }

    /** After a drag: close to an edge means "dock there". */
    private fun snap() {
        val edge = dp(36)
        val left = params.x
        val right = screenW() - (params.x + widthNow())
        val top = params.y
        val best = min(left, min(right, top))
        dock = when {
            best > edge -> Dock.NONE
            best == left -> Dock.LEFT
            best == right -> Dock.RIGHT
            else -> Dock.TOP
        }
        applyDock()
        update()
        savePosition()
    }

    private fun savePosition() {
        val absX = if (isRight()) max(0, screenW() - widthNow() - params.x) else params.x
        store.savePosition(absX, params.y, dock.ordinal)
    }

    private fun sizeExpanded() {
        params.width = min(dp(340), screenW() - dp(16))
        params.height = min(dp(380), (screenH() * 0.55f).toInt())
    }

    private fun setExpanded(on: Boolean) {
        if (expanded == on) return
        toAbsolute()
        expanded = on
        if (on) {
            clearTicker()
            sizeExpanded()
            root.gravity = Gravity.LEFT
        } else {
            params.width = WindowManager.LayoutParams.WRAP_CONTENT
            params.height = WindowManager.LayoutParams.WRAP_CONTENT
            applyDock()
        }
        scroll.visibility = if (on) View.VISIBLE else View.GONE
        val buttons = if (on) View.VISIBLE else View.GONE
        btnOpacity.visibility = buttons
        btnMin.visibility = buttons
        btnClose.visibility = buttons
        clamp()
        redraw()
        update()
        if (on) scrollDown()
        savePosition()
    }

    private fun cycleOpacity() {
        opacity = (opacity + 1) % 3
        store.opacity = opacity
        applyLook()
    }

    private inner class DragListener : View.OnTouchListener {
        private var downX = 0f
        private var downY = 0f
        private var startX = 0
        private var startY = 0
        private var moved = false
        private var longPressed = false
        private val slop = ViewConfiguration.get(ctx).scaledTouchSlop
        private val longPress = Runnable {
            if (!moved) {
                longPressed = true
                cycleOpacity()
            }
        }

        override fun onTouch(v: View, e: MotionEvent): Boolean {
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    toAbsolute()
                    downX = e.rawX
                    downY = e.rawY
                    startX = params.x
                    startY = params.y
                    moved = false
                    longPressed = false
                    main.postDelayed(longPress, ViewConfiguration.getLongPressTimeout().toLong())
                    return true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX
                    val dy = e.rawY - downY
                    if (!moved && (abs(dx) > slop || abs(dy) > slop)) {
                        moved = true
                        main.removeCallbacks(longPress)
                        if (!expanded) dock = Dock.NONE
                    }
                    if (moved) {
                        params.x = (startX + dx).toInt()
                        params.y = (startY + dy).toInt()
                        clamp()
                        update()
                    }
                    return true
                }
                MotionEvent.ACTION_UP -> {
                    main.removeCallbacks(longPress)
                    if (moved) {
                        if (!expanded) snap() else savePosition()
                    } else if (!longPressed && !expanded) {
                        setExpanded(true)
                    }
                    return true
                }
                MotionEvent.ACTION_CANCEL -> {
                    main.removeCallbacks(longPress)
                    if (moved) {
                        if (!expanded) snap() else savePosition()
                    }
                    return true
                }
            }
            return false
        }
    }

    // ---------------------------------------------------------------------------------------------- what is shown
    fun setLink(l: Link, d: String) {
        link = l
        detail = d
        main.removeCallbacks(staleCheck)
        if (l == Link.ONLINE) lastData = System.currentTimeMillis() else main.postDelayed(staleCheck, 31_000)
        redraw()
    }

    fun setState(s: State) {
        state = s
        redraw()
    }

    fun setStats(s: Stats) {
        stats = s
        lastData = System.currentTimeMillis()
        redraw()
    }

    fun setPrefs(p: Prefs) {
        prefs = p
        for (r in rows) r.setTextSize(TypedValue.COMPLEX_UNIT_SP, p.fontSize.toFloat())
        for (t in ticks) t.setTextSize(TypedValue.COMPLEX_UNIT_SP, p.fontSize.toFloat())
        trimRows()
    }

    fun showNotice(text: String) {
        notice = text
        redraw()
    }

    fun addChat(lines: List<Line>, skipped: Int) {
        val atBottom = !expanded || scroll.height == 0 || scroll.scrollY + scroll.height >= list.height - dp(48)
        val fresh = ArrayList<Line>()
        if (skipped > 0) fresh.add(Line(0, "", "", "+$skipped more messages", "note"))
        for (l in lines) {
            if (l.id > 0 && shown.contains(l.id)) continue
            fresh.add(l)
        }
        if (fresh.isEmpty()) return
        for (l in fresh) {
            val row = makeLine(l, false)
            list.addView(row)
            rows.add(row)
            if (l.id > 0) shown.add(l.id)
        }
        trimRows()
        if (expanded) {
            if (atBottom) scrollDown()
        } else {
            peek(fresh)
        }
    }

    fun purge(uids: List<String>, ids: List<Long>) {
        val gone = ArrayList<TextView>()
        for (r in rows) {
            val l = r.tag as? Line ?: continue
            if (l.id > 0 && ids.contains(l.id) || l.uid.isNotEmpty() && uids.contains(l.uid)) gone.add(r)
        }
        for (r in gone) {
            list.removeView(r)
            rows.remove(r)
            (r.tag as? Line)?.let { shown.remove(it.id) }
        }
        val goneTicks = ArrayList<TextView>()
        for (t in ticks) {
            val l = t.tag as? Line ?: continue
            if (l.id > 0 && ids.contains(l.id) || l.uid.isNotEmpty() && uids.contains(l.uid)) goneTicks.add(t)
        }
        for (t in goneTicks) {
            ticker.removeView(t)
            ticks.remove(t)
        }
        if (ticks.isEmpty()) ticker.visibility = View.GONE
    }

    private fun trimRows() {
        while (rows.size > prefs.chatLines) {
            val v = rows.removeAt(0)
            list.removeView(v)
            (v.tag as? Line)?.let { shown.remove(it.id) }
        }
    }

    private fun scrollDown() {
        scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
    }

    /** Compact mode: the newest line or two slide out under the pill, then tuck away after the peek time. */
    private fun peek(fresh: List<Line>) {
        val newest = if (fresh.size > 2) fresh.subList(fresh.size - 2, fresh.size) else fresh
        for (l in newest) {
            val t = makeLine(l, true)
            ticker.addView(t, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT))
            ticks.add(t)
        }
        while (ticks.size > 2) {
            ticker.removeView(ticks.removeAt(0))
        }
        ticker.visibility = View.VISIBLE
        main.removeCallbacks(hideTicker)
        main.postDelayed(hideTicker, prefs.peekSeconds * 1000L)
    }

    private fun clearTicker() {
        main.removeCallbacks(hideTicker)
        ticker.removeAllViews()
        ticks.clear()
        ticker.visibility = View.GONE
    }

    private fun makeLine(line: Line, forTicker: Boolean): TextView {
        val t = TextView(ctx)
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, prefs.fontSize.toFloat())
        t.setTextColor(0xFFF1F2F5.toInt())
        t.setPadding(0, dp(2), 0, dp(2))
        t.setShadowLayer(if (opacity == 2) 4f else 0f, 0f, 1f, Color.BLACK)
        t.text = lineText(line)
        t.tag = line
        if (forTicker) {
            t.maxLines = 2
            t.ellipsize = TextUtils.TruncateAt.END
            t.maxWidth = min(dp(280), (screenW() * 0.75f).toInt())
        }
        return t
    }

    private fun lineText(line: Line): CharSequence {
        val sb = SpannableStringBuilder()
        if (line.level == "note") {
            val start = sb.length
            sb.append(line.text)
            sb.setSpan(ForegroundColorSpan(0xFF9AA0B0.toInt()), start, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            sb.setSpan(StyleSpan(Typeface.ITALIC), start, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            return sb
        }
        val color = when (line.level) {
            "owner" -> 0xFFFFC857.toInt()
            "mod" -> 0xFF6EA8FF.toInt()
            "member" -> 0xFF4ADE80.toInt()
            else -> 0xFFB8BECC.toInt()
        }
        val start = sb.length
        sb.append(line.name).append("  ")
        sb.setSpan(ForegroundColorSpan(color), start, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        sb.setSpan(StyleSpan(Typeface.BOLD), start, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        sb.append(line.text)
        return sb
    }

    // ---------------------------------------------------------------------------------------------- drawing
    private fun applyLook() {
        val bg = GradientDrawable()
        bg.setCornerRadius(dp(14).toFloat())
        when (opacity) {
            0 -> {
                bg.setColor(0xF2111318.toInt())
                bg.setStroke(dp(1), 0x33FFFFFF)
            }
            1 -> {
                bg.setColor(0x99111318.toInt())
                bg.setStroke(dp(1), 0x22FFFFFF)
            }
            else -> bg.setColor(Color.TRANSPARENT)
        }
        root.background = bg
        val shadow = if (opacity == 2) 4f else 0f
        statsView.setShadowLayer(shadow, 0f, 1f, Color.BLACK)
        statusView.setShadowLayer(shadow, 0f, 1f, Color.BLACK)
        for (r in rows) r.setShadowLayer(shadow, 0f, 1f, Color.BLACK)
        for (t in ticks) t.setShadowLayer(shadow, 0f, 1f, Color.BLACK)
    }

    private fun redraw() {
        val fresh = link == Link.ONLINE || System.currentTimeMillis() - lastData < 30_000
        val s = stats
        val canShow = fresh && s != null && s.enabled && state.live
        val sb = SpannableStringBuilder()
        sb.append("\uD83D\uDC41 ").append(if (canShow && s != null) Fmt.count(s.viewers) else Fmt.count(null))
        sb.append("   ")
        val heart = sb.length
        sb.append("\u2665")
        sb.setSpan(ForegroundColorSpan(0xFFFF4D55.toInt()), heart, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        sb.append(" ").append(if (canShow && s != null && !s.likesHidden) Fmt.count(s.likes) else Fmt.count(null))
        statsView.text = sb

        val dotColor = when {
            link == Link.ONLINE && state.live -> 0xFFE5242B.toInt()
            link == Link.CONNECTING || link == Link.RECONNECTING || link == Link.WAITING -> 0xFFF5B301.toInt()
            else -> 0xFF8A90A0.toInt()
        }
        val d = GradientDrawable()
        d.shape = GradientDrawable.OVAL
        d.setColor(dotColor)
        dot.background = d

        var text = ""
        var color = 0xFFB8BECC.toInt()
        when {
            notice.isNotEmpty() -> {
                text = notice
                color = 0xFFFF6B6B.toInt()
            }
            link == Link.CONNECTING -> text = "Connecting\u2026"
            link == Link.RECONNECTING -> {
                text = "Reconnecting\u2026"
                color = 0xFFF5B301.toInt()
            }
            link == Link.WAITING -> {
                text = detail
                color = 0xFFF5B301.toInt()
            }
            link == Link.ONLINE && state.mode == "demo" -> text = "Demo mode"
            link == Link.ONLINE && !state.live -> text = "Waiting for your stream"
            link == Link.ONLINE && expanded && state.title.isNotEmpty() -> text = state.title
        }
        statusView.text = text
        statusView.setTextColor(color)
        statusView.visibility = if (text.isEmpty()) View.GONE else View.VISIBLE
        applyLook()
    }
}
