package com.savahbot.live

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import kotlin.math.abs

/** The window's outermost view. It watches the two bottom corners: touching one starts a proportional resize. Everything else passes through. */
class PanelRoot(
    context: Context,
    private val zone: Int,
    private val onStart: (Int) -> Unit,
    private val onMove: (Float, Float) -> Unit,
    private val onEnd: () -> Unit
) : FrameLayout(context) {
    private var corner = -1

    override fun onInterceptTouchEvent(e: MotionEvent): Boolean {
        if (e.actionMasked == MotionEvent.ACTION_DOWN) {
            val c = cornerAt(e.x, e.y)
            if (c >= 0) {
                corner = c
                onStart(c)
                return true
            }
        }
        return false
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        if (corner < 0) return false
        when (e.actionMasked) {
            MotionEvent.ACTION_MOVE -> onMove(e.rawX, e.rawY)
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                corner = -1
                onEnd()
            }
        }
        return true
    }

    /** 2 = bottom-left, 3 = bottom-right, -1 = not a corner. */
    private fun cornerAt(x: Float, y: Float): Int {
        if (y < height - zone) return -1
        return when {
            x < zone -> 2
            x > width - zone -> 3
            else -> -1
        }
    }
}

/**
 * The expanded SavahLive window. It is laid out once at a fixed base size and shown scaled (like a phone's own floating windows), so resizing is always
 * proportional. Top bar: expand (cycles S/M/L), the three-dot handle (drag to move, tap for the tray), and close (tucks it into the screen edge).
 * The tray holds opacity, tab fade, theme, lock, text size and stop. It draws what the controller gives it and never decides anything itself.
 */
class PanelView(private val ctx: Context, private val store: Store, private val host: Host) {
    interface Host {
        fun dragStart()
        fun dragBy(dx: Float, dy: Float)
        fun dragEnd()
        fun resizeStart(corner: Int)
        fun resizeTo(rawX: Float, rawY: Float)
        fun resizeEnd()
        fun cycleSize()
        fun tuck()
        fun stopOverlay()
        fun toggleLock()
        fun settingsChanged()
    }

    companion object {
        const val BASE_W_DP = 300
        const val BASE_H_DP = 380
        private const val AMBER = 0xFFF5B301.toInt()
    }

    private fun dp(v: Int): Int = dpOf(ctx, v)
    private val main = Handler(Looper.getMainLooper())

    val baseW = dp(BASE_W_DP)
    val baseH = dp(BASE_H_DP)

    private var theme: Theme = Themes.presets[0]
    private var opacity = 92
    private var fontSp = 14f
    private var textScale = 100
    private var scaleNow = 1f
    private var dotKind = 2
    private var locked = false
    private var chatCap = 40
    private var armedStop = false

    private val tints = ArrayList<Pair<ImageView, Int>>()      // icon, role: 0 text, 1 muted, 2 accent, 3 heart
    private val labels = ArrayList<Pair<TextView, Int>>()      // text, role: 0 text, 1 muted
    private val rows = ArrayList<TextView>()

    private val content = FrameLayout(ctx)
    private val column = LinearLayout(ctx)
    private val topBar = LinearLayout(ctx)
    private val statsRow = LinearLayout(ctx)
    private val statusTv = TextView(ctx)
    private val divider = View(ctx)
    private val scroll = ScrollView(ctx)
    private val list = LinearLayout(ctx)
    private val tray = LinearLayout(ctx)
    private val themeBox = LinearLayout(ctx)
    private val customBox = LinearLayout(ctx)
    private val swatchRow = LinearLayout(ctx)
    private val dotIv: ImageView
    private val lockIv: ImageView
    private val viewersTv = TextView(ctx)
    private val likesTv = TextView(ctx)
    private val opacityValue = TextView(ctx)
    private val fadeValue = TextView(ctx)
    private val opacitySlider = LineSlider(ctx)
    private val fadeSlider = LineSlider(ctx)
    private val hueSlider = LineSlider(ctx)
    private val lightSlider = LineSlider(ctx)
    private val lockBtnIcon: ImageView
    private val lockBtnLabel = TextView(ctx)
    private val stopLabel = TextView(ctx)
    private val gripLeft: ImageView
    private val gripRight: ImageView

    val root = PanelRoot(ctx, dp(34), { c -> host.resizeStart(c); outline(true) }, { x, y -> host.resizeTo(x, y) }, { host.resizeEnd(); outline(false) })

    private val hideStopArm = Runnable {
        armedStop = false
        stopLabel.text = "Stop"
        stopLabel.setTextColor(theme.muted)
    }

    init {
        // ---- top bar ---------------------------------------------------------------------------------------------------------------------
        topBar.orientation = LinearLayout.HORIZONTAL
        topBar.gravity = Gravity.CENTER_VERTICAL
        val fit = button(R.drawable.ic_expand, 0, 22, "Change size") { host.cycleSize() }
        val close = button(R.drawable.ic_close, 0, 22, "Tuck into the screen edge") { host.tuck() }
        val dots = iconView(ctx, R.drawable.ic_dots, theme.muted, 26)
        tints.add(Pair(dots, 1))
        dots.contentDescription = "Drag to move. Tap for options."
        val dotsBox = FrameLayout(ctx)
        dotsBox.addView(dots, FrameLayout.LayoutParams(dp(26), dp(26), Gravity.CENTER))
        topBar.addView(fit, LinearLayout.LayoutParams(dp(46), dp(46)))
        topBar.addView(dotsBox, LinearLayout.LayoutParams(0, dp(46), 1f))
        topBar.addView(close, LinearLayout.LayoutParams(dp(46), dp(46)))
        dotsBox.setOnTouchListener(DragHandle(true))
        topBar.setOnTouchListener(DragHandle(false))

        // ---- stats row ---------------------------------------------------------------------------------------------------------------------
        statsRow.orientation = LinearLayout.HORIZONTAL
        statsRow.gravity = Gravity.CENTER_VERTICAL
        statsRow.setPadding(dp(16), 0, dp(16), 0)
        dotIv = iconView(ctx, R.drawable.ic_live, theme.muted, 16)
        val eye = iconView(ctx, R.drawable.ic_eye, theme.muted, 18)
        val heart = iconView(ctx, R.drawable.ic_heart, theme.heart, 16)
        lockIv = iconView(ctx, R.drawable.ic_lock, theme.muted, 16)
        lockIv.visibility = View.GONE
        tints.add(Pair(eye, 1))
        tints.add(Pair(heart, 3))
        tints.add(Pair(lockIv, 1))
        for (t in listOf(viewersTv, likesTv)) {
            t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
            t.setTypeface(Typeface.DEFAULT_BOLD)
            t.setSingleLine(true)
            labels.add(Pair(t, 0))
        }
        val gap = { w: Int -> View(ctx).also { it.layoutParams = LinearLayout.LayoutParams(dp(w), 1) } }
        statsRow.addView(dotIv)
        statsRow.addView(gap(10))
        statsRow.addView(eye)
        statsRow.addView(gap(6))
        statsRow.addView(viewersTv)
        statsRow.addView(gap(16))
        statsRow.addView(heart)
        statsRow.addView(gap(6))
        statsRow.addView(likesTv)
        statsRow.addView(View(ctx), LinearLayout.LayoutParams(0, 1, 1f))
        statsRow.addView(lockIv)
        statsRow.setOnTouchListener(DragHandle(false))

        statusTv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
        statusTv.setPadding(dp(16), 0, dp(16), dp(6))
        statusTv.maxLines = 1
        statusTv.ellipsize = android.text.TextUtils.TruncateAt.END
        statusTv.visibility = View.GONE

        // ---- chat ---------------------------------------------------------------------------------------------------------------------------
        list.orientation = LinearLayout.VERTICAL
        list.setPadding(dp(16), dp(8), dp(16), dp(26))
        scroll.addView(list)
        scroll.isVerticalScrollBarEnabled = false
        scroll.isVerticalFadingEdgeEnabled = true
        scroll.setFadingEdgeLength(dp(22))
        scroll.overScrollMode = View.OVER_SCROLL_NEVER

        column.orientation = LinearLayout.VERTICAL
        column.addView(topBar, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(46)))
        column.addView(statsRow, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(36)))
        column.addView(statusTv)
        column.addView(divider, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 1))
        column.addView(scroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))

        // ---- resize grips (bottom corners) -----------------------------------------------------------------------------------------
        gripRight = iconView(ctx, R.drawable.ic_grip, theme.muted, 18)
        gripLeft = iconView(ctx, R.drawable.ic_grip, theme.muted, 18)
        gripLeft.scaleX = -1f
        tints.add(Pair(gripRight, 1))
        tints.add(Pair(gripLeft, 1))

        // ---- tray ---------------------------------------------------------------------------------------------------------------------------
        lockBtnIcon = iconView(ctx, R.drawable.ic_unlock, theme.text, 22)
        buildTray()

        content.addView(column, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        content.addView(gripRight, FrameLayout.LayoutParams(dp(18), dp(18), Gravity.BOTTOM or Gravity.RIGHT).also { it.setMargins(0, 0, dp(6), dp(6)) })
        content.addView(gripLeft, FrameLayout.LayoutParams(dp(18), dp(18), Gravity.BOTTOM or Gravity.LEFT).also { it.setMargins(dp(6), 0, 0, dp(6)) })
        content.addView(tray, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.TOP).also { it.setMargins(dp(8), dp(46), dp(8), 0) })
        content.pivotX = 0f
        content.pivotY = 0f
        root.addView(content, FrameLayout.LayoutParams(baseW, baseH))
        recolor()
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    private fun button(res: Int, role: Int, sizeDp: Int, description: String, onClick: () -> Unit): FrameLayout {
        val box = FrameLayout(ctx)
        val iv = iconView(ctx, res, theme.text, sizeDp)
        tints.add(Pair(iv, role))
        box.addView(iv, FrameLayout.LayoutParams(dp(sizeDp), dp(sizeDp), Gravity.CENTER))
        box.contentDescription = description
        box.isClickable = true
        box.setOnClickListener { onClick() }
        return box
    }

    private fun action(res: Int, label: TextView, onClick: () -> Unit, icon: ImageView = iconView(ctx, res, theme.text, 22)): LinearLayout {
        val col = LinearLayout(ctx)
        col.orientation = LinearLayout.VERTICAL
        col.gravity = Gravity.CENTER_HORIZONTAL
        col.setPadding(0, dp(6), 0, dp(6))
        tints.add(Pair(icon, 0))
        label.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
        label.gravity = Gravity.CENTER
        label.setSingleLine(true)
        col.addView(icon)
        col.addView(label, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).also { it.topMargin = dp(2) })
        col.isClickable = true
        col.setOnClickListener { onClick() }
        return col
    }

    private fun sliderRow(res: Int, slider: LineSlider, value: TextView, description: String): LinearLayout {
        val row = LinearLayout(ctx)
        row.orientation = LinearLayout.HORIZONTAL
        row.gravity = Gravity.CENTER_VERTICAL
        val iv = iconView(ctx, res, theme.muted, 20)
        tints.add(Pair(iv, 1))
        slider.contentDescription = description
        value.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
        value.gravity = Gravity.END
        labels.add(Pair(value, 1))
        row.addView(iv)
        row.addView(slider, LinearLayout.LayoutParams(0, dp(34), 1f).also { it.setMargins(dp(8), 0, dp(6), 0) })
        row.addView(value, LinearLayout.LayoutParams(dp(38), LinearLayout.LayoutParams.WRAP_CONTENT))
        return row
    }

    private fun buildTray() {
        tray.orientation = LinearLayout.VERTICAL
        tray.setPadding(dp(12), dp(10), dp(12), dp(8))
        tray.visibility = View.GONE
        tray.isClickable = true      // taps on the tray itself never fall through to the chat

        opacitySlider.min = 20
        opacitySlider.max = 100
        opacitySlider.value = store.panelOpacity
        opacitySlider.onChange = { v ->
            store.panelOpacity = v
            opacity = v
            opacityValue.text = "$v%"
            paintBackground()
            host.settingsChanged()
        }
        fadeSlider.min = 10
        fadeSlider.max = 100
        fadeSlider.value = store.tabFade
        fadeSlider.onChange = { v ->
            store.tabFade = v
            fadeValue.text = "$v%"
            host.settingsChanged()
        }
        opacityValue.text = "${store.panelOpacity}%"
        fadeValue.text = "${store.tabFade}%"
        tray.addView(sliderRow(R.drawable.ic_opacity, opacitySlider, opacityValue, "Panel opacity"))
        tray.addView(sliderRow(R.drawable.ic_tab, fadeSlider, fadeValue, "How visible the tab is when tucked away"))

        val buttons = LinearLayout(ctx)
        buttons.orientation = LinearLayout.HORIZONTAL
        val themeLabel = TextView(ctx).also { it.text = "Theme"; labels.add(Pair(it, 1)) }
        val smallerLabel = TextView(ctx).also { it.text = "Text -"; labels.add(Pair(it, 1)) }
        val biggerLabel = TextView(ctx).also { it.text = "Text +"; labels.add(Pair(it, 1)) }
        lockBtnLabel.text = "Lock"
        labels.add(Pair(lockBtnLabel, 1))
        stopLabel.text = "Stop"
        labels.add(Pair(stopLabel, 1))
        val w = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        buttons.addView(action(R.drawable.ic_palette, themeLabel, { toggleThemeBox() }), w)
        buttons.addView(action(R.drawable.ic_unlock, lockBtnLabel, { host.toggleLock() }, lockBtnIcon), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        buttons.addView(action(R.drawable.ic_minus, smallerLabel, { nudgeText(-10) }), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        buttons.addView(action(R.drawable.ic_plus, biggerLabel, { nudgeText(10) }), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        buttons.addView(action(R.drawable.ic_power, stopLabel, { onStopTapped() }), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        tray.addView(buttons, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).also { it.topMargin = dp(4) })

        themeBox.orientation = LinearLayout.VERTICAL
        themeBox.visibility = View.GONE
        swatchRow.orientation = LinearLayout.HORIZONTAL
        swatchRow.gravity = Gravity.CENTER
        themeBox.addView(swatchRow)
        customBox.orientation = LinearLayout.VERTICAL
        customBox.visibility = View.GONE
        hueSlider.min = 0
        hueSlider.max = 359
        hueSlider.value = store.customHue
        hueSlider.gradient = IntArray(7) { i -> Themes.hsl(i * 60 % 360, 0.85f, 0.55f) }
        hueSlider.contentDescription = "Colour"
        hueSlider.onChange = { v ->
            store.customHue = v
            chooseTheme(Themes.CUSTOM)
        }
        lightSlider.min = 8
        lightSlider.max = 94
        lightSlider.value = store.customLight
        lightSlider.gradient = intArrayOf(0xFF000000.toInt(), 0xFF808080.toInt(), 0xFFFFFFFF.toInt())
        lightSlider.contentDescription = "Light or dark"
        lightSlider.onChange = { v ->
            store.customLight = v
            chooseTheme(Themes.CUSTOM)
        }
        customBox.addView(hueSlider)
        customBox.addView(lightSlider)
        themeBox.addView(customBox)
        tray.addView(themeBox)
        drawSwatches()
    }

    private fun drawSwatches() {
        swatchRow.removeAllViews()
        val all = ArrayList<Int>()
        for (t in Themes.presets) all.add(t.id)
        all.add(Themes.CUSTOM)
        for (id in all) {
            val v = View(ctx)
            val g = GradientDrawable()
            g.shape = GradientDrawable.OVAL
            if (id == Themes.CUSTOM) {
                g.setGradientType(GradientDrawable.SWEEP_GRADIENT)
                g.setColors(IntArray(7) { i -> Themes.hsl(i * 60 % 360, 0.85f, 0.55f) })
            } else {
                g.setColor(Themes.byId(id, 0, 0).bg)
            }
            val on = store.themeId == id || (id == 0 && Themes.presets.none { it.id == store.themeId } && store.themeId != Themes.CUSTOM)
            g.setStroke(dp(if (on) 3 else 1), if (on) theme.accent else theme.muted)
            v.background = g
            v.contentDescription = if (id == Themes.CUSTOM) "Custom colour" else Themes.byId(id, 0, 0).name
            v.setOnClickListener { chooseTheme(id) }
            swatchRow.addView(v, LinearLayout.LayoutParams(dp(30), dp(30)).also { it.setMargins(dp(4), dp(8), dp(4), dp(4)) })
        }
        customBox.visibility = if (store.themeId == Themes.CUSTOM) View.VISIBLE else View.GONE
    }

    private fun chooseTheme(id: Int) {
        store.themeId = id
        host.settingsChanged()
    }

    private fun toggleThemeBox() {
        themeBox.visibility = if (themeBox.visibility == View.VISIBLE) View.GONE else View.VISIBLE
    }

    private fun nudgeText(delta: Int) {
        store.textScale = store.textScale + delta
        host.settingsChanged()
    }

    private fun onStopTapped() {
        if (armedStop) {
            main.removeCallbacks(hideStopArm)
            host.stopOverlay()
            return
        }
        armedStop = true
        stopLabel.text = "Sure?"
        stopLabel.setTextColor(AMBER)
        main.postDelayed(hideStopArm, 2500)
    }

    fun toggleTray() {
        tray.visibility = if (tray.visibility == View.VISIBLE) View.GONE else View.VISIBLE
    }

    fun closeTray() {
        tray.visibility = View.GONE
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    /** One finger on the top bar or the stats row moves the whole window. A tap (no movement) on the dots opens or closes the tray. */
    private inner class DragHandle(private val tapOpensTray: Boolean) : View.OnTouchListener {
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
                    host.dragStart()
                    return true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX
                    val dy = e.rawY - downY
                    if (!moved && (abs(dx) > slop || abs(dy) > slop)) {
                        moved = true
                        outline(true)
                    }
                    if (moved) host.dragBy(dx, dy)
                    return true
                }
                MotionEvent.ACTION_UP -> {
                    outline(false)
                    if (moved) host.dragEnd() else if (tapOpensTray) toggleTray()
                    return true
                }
                MotionEvent.ACTION_CANCEL -> {
                    outline(false)
                    if (moved) host.dragEnd()
                    return true
                }
            }
            return false
        }
    }

    private fun outline(on: Boolean) {
        if (!on) {
            root.foreground = null
            return
        }
        val g = GradientDrawable()
        g.setColor(Color.TRANSPARENT)
        g.setCornerRadius(dp(16) * scaleNow)
        g.setStroke(dp(2), theme.accent)
        root.foreground = g
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    fun setScale(s: Float) {
        scaleNow = s
        content.scaleX = s
        content.scaleY = s
    }

    fun setLook(t: Theme, opacityPct: Int, baseFontSp: Float, textScalePct: Int, cap: Int) {
        // Sliders call this on every movement: do nothing unless something the panel draws actually changed.
        if (t.bg == theme.bg && t.text == theme.text && t.accent == theme.accent && t.surface == theme.surface && t.muted == theme.muted &&
            opacityPct == opacity && baseFontSp == fontSp && textScalePct == textScale && cap == chatCap) return
        theme = t
        opacity = opacityPct
        fontSp = baseFontSp
        textScale = textScalePct
        chatCap = cap
        opacitySlider.value = store.panelOpacity
        fadeSlider.value = store.tabFade
        opacityValue.text = "${store.panelOpacity}%"
        fadeValue.text = "${store.tabFade}%"
        drawSwatches()
        recolor()
    }

    fun setHeader(viewers: String, likes: String, dot: Int, status: String, alert: Boolean) {
        viewersTv.text = viewers
        likesTv.text = likes
        dotKind = dot
        dotIv.setColorFilter(dotColor())
        statusTv.text = status
        statusTv.setTextColor(if (alert) AMBER else theme.muted)
        statusTv.visibility = if (status.isEmpty()) View.GONE else View.VISIBLE
    }

    fun setLocked(on: Boolean) {
        locked = on
        lockIv.visibility = if (on) View.VISIBLE else View.GONE
        lockBtnIcon.setImageResource(if (on) R.drawable.ic_lock else R.drawable.ic_unlock)
        lockBtnLabel.text = if (on) "Locked" else "Lock"
    }

    private fun dotColor(): Int = when (dotKind) {
        0 -> theme.accent
        1 -> AMBER
        else -> theme.muted
    }

    private fun paintBackground() {
        val bg = GradientDrawable()
        bg.setColor(Themes.withAlpha(theme.bg, opacity))
        bg.setCornerRadius(dp(16).toFloat())
        bg.setStroke(dp(1), Themes.withAlpha(theme.text, 22))
        content.background = bg
    }

    private fun roleColor(role: Int): Int = when (role) {
        0 -> theme.text
        1 -> theme.muted
        2 -> theme.accent
        else -> theme.heart
    }

    private fun shadowFor(t: TextView) {
        val glow = opacity < 65
        if (glow) t.setShadowLayer(4f, 0f, 1f, if (Themes.luminance(theme.bg) < 0.5) 0xCC000000.toInt() else 0xCCFFFFFF.toInt())
        else t.setShadowLayer(0f, 0f, 0f, 0)
    }

    private fun recolor() {
        paintBackground()
        for ((iv, role) in tints) iv.setColorFilter(roleColor(role))
        for ((tv, role) in labels) {
            tv.setTextColor(roleColor(role))
            shadowFor(tv)
        }
        dotIv.setColorFilter(dotColor())
        divider.setBackgroundColor(Themes.withAlpha(theme.text, 16))
        val trayBg = GradientDrawable()
        trayBg.setColor(theme.surface)
        trayBg.setCornerRadius(dp(14).toFloat())
        trayBg.setStroke(dp(1), Themes.withAlpha(theme.text, 24))
        tray.background = trayBg
        for (s in listOf(opacitySlider, fadeSlider)) {
            s.trackColor = Themes.withAlpha(theme.text, 28)
            s.fillColor = theme.accent
            s.thumbColor = theme.text
        }
        for (s in listOf(hueSlider, lightSlider)) s.thumbColor = theme.text
        statusTv.setTextColor(theme.muted)
        for (r in rows) styleRow(r)
        textSizes()
    }

    private fun textSizes() {
        val sp = fontSp * textScale / 100f
        for (r in rows) r.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
    }

    // ---- chat --------------------------------------------------------------------------------------------------------------------------------
    private fun styleRow(tv: TextView) {
        val line = tv.tag as? Line ?: return
        tv.text = ChatStyle.render(theme, line)
        tv.setTextColor(theme.text)
        shadowFor(tv)
    }

    private fun makeRow(line: Line): TextView {
        val tv = TextView(ctx)
        tv.tag = line
        tv.setPadding(0, dp(3), 0, dp(3))
        styleRow(tv)
        tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, fontSp * textScale / 100f)
        return tv
    }

    /** Rebuilds the list from the controller's model (used when the panel opens, or after a purge or theme change). */
    fun setLines(lines: List<Line>) {
        list.removeAllViews()
        rows.clear()
        val from = if (lines.size > chatCap) lines.size - chatCap else 0
        for (i in from until lines.size) {
            val r = makeRow(lines[i])
            rows.add(r)
            list.addView(r)
        }
        scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
    }

    fun addLines(lines: List<Line>) {
        val atBottom = scroll.height == 0 || scroll.scrollY + scroll.height >= list.height - dp(60)
        for (l in lines) {
            val r = makeRow(l)
            rows.add(r)
            list.addView(r)
        }
        while (rows.size > chatCap) list.removeView(rows.removeAt(0))
        if (atBottom) scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
    }
}
