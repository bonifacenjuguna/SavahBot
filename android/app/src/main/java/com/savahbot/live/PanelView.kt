package com.savahbot.live

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Outline
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.os.Handler
import android.os.Looper
import android.text.InputFilter
import android.text.TextUtils
import android.util.TypedValue
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.animation.OvershootInterpolator
import android.view.ViewOutlineProvider
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import kotlin.math.abs

/**
 * The window's outermost view. It watches a thin band along every edge and a larger square at every corner: touching one starts a resize of
 * that edge or corner. Everything else passes through to the panel's own controls. It never changes the view tree, it only reports gestures.
 */
class PanelFrame(
    context: Context,
    private val edge: Int,
    private val topEdge: Int,
    private val corner: Int,
    private val host: PanelView.Host
) : FrameLayout(context) {
    private var mode = 0
    private var downX = 0f
    private var downY = 0f

    override fun onInterceptTouchEvent(e: MotionEvent): Boolean {
        if (e.actionMasked == MotionEvent.ACTION_DOWN) {
            val m = Geo.hitMode(e.x, e.y, width, height, edge, topEdge, corner)
            if (m != 0) {
                mode = m
                downX = e.rawX
                downY = e.rawY
                host.resizeStart(m)
                return true
            }
        }
        return false
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        if (mode == 0) return false
        when (e.actionMasked) {
            MotionEvent.ACTION_MOVE -> host.resizeBy((e.rawX - downX).toInt(), (e.rawY - downY).toInt())
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                mode = 0
                host.resizeEnd()
            }
        }
        return true
    }
}

/** The message box. The Back button closes the keyboard instead of doing nothing (an overlay has no Back of its own). */
class ChatInput(context: Context, private val onBack: () -> Unit) : EditText(context) {
    override fun onKeyPreIme(keyCode: Int, event: KeyEvent): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK && event.action == KeyEvent.ACTION_UP) {
            onBack()
            return true
        }
        return super.onKeyPreIme(keyCode, event)
    }
}

/**
 * The expanded SavahLive window: one slim header (live light, viewers, likes, expand, tuck), the chat, and an optional message box.
 * It is a real window of any size: drag any edge or corner to resize (the chat gets longer or wider, it never scales), drag the header to move it.
 * It draws what the controller gives it and never decides anything itself. Settings live in the SavahLive app, not on the panel.
 */
class PanelView(private val ctx: Context, private val store: Store, private val host: Host) {
    interface Host {
        fun moveStart()
        fun moveBy(dx: Int, dy: Int)
        fun moveEnd()
        fun resizeStart(mode: Int)
        fun resizeBy(dx: Int, dy: Int)
        fun resizeEnd()
        fun toggleExpand()
        fun tuck()
        fun keyboard(on: Boolean)
        fun send(text: String)
        fun pin(line: Line?)
        fun moderate(line: Line, action: String)
    }

    companion object {
        private const val AMBER = 0xFFF5B301.toInt()
    }

    private fun dp(v: Int): Int = dpOf(ctx, v)
    private val main = Handler(Looper.getMainLooper())

    private var theme: Theme = Themes.presets[0]
    private var opacity = 92
    private var fontSp = 14f
    private var textScale = 100
    private var dotKind = 2
    private var chatCap = 40
    private var sending = false
    private var composerOn = false

    private val tints = ArrayList<Pair<ImageView, Int>>()      // icon, role: 0 text, 1 muted, 2 accent, 3 heart
    private val labels = ArrayList<Pair<TextView, Int>>()      // text, role: 0 text, 1 muted
    private val chips = ArrayList<View>()                     // round buttons, repainted with the theme
    private val rows = ArrayList<TextView>()

    private val column = LinearLayout(ctx)
    private val header = LinearLayout(ctx)
    private val stats = LinearLayout(ctx)
    private val statusTv = TextView(ctx)
    private val divider = View(ctx)
    private val scroll = ScrollView(ctx)
    private val list = LinearLayout(ctx)
    private val noteTv = TextView(ctx)
    private val composer = LinearLayout(ctx)
    private val input: ChatInput
    private val sendBtn = FrameLayout(ctx)
    private val sendIv: ImageView
    private val liveIv: ImageView
    private val userIv: ImageView
    private val heartIv: ImageView
    private val expandIv: ImageView
    private val viewersTv = TextView(ctx)
    private val likesTv = TextView(ctx)

    val view = PanelFrame(ctx, dp(16), dp(8), dp(24), host)

    private val hideNote = Runnable { noteTv.visibility = View.GONE }

    // pinned line, and the small bar that offers Hide / Time out for a line you held down
    private val pinCard = LinearLayout(ctx)
    private val pinTv = TextView(ctx)
    private lateinit var pinIv: ImageView
    private val modBar = LinearLayout(ctx)
    private val modName = TextView(ctx)
    private val modChips = ArrayList<TextView>()
    private var pinOn = true
    private var modOn = false
    private var modLine: Line? = null
    private var pinned: Line? = null
    private var bannerAlert = false
    private val endCelebrate = Runnable { statusTv.setTypeface(Typeface.DEFAULT); redrawStatus() }
    private var statusText = ""

    init {
        // ---- header: stats on the left (drag here to move), two round buttons on the right ------------------------------------------------
        liveIv = iconView(ctx, R.drawable.ic_live, theme.muted, 17)
        userIv = iconView(ctx, R.drawable.ic_user, theme.muted, 16)
        heartIv = iconView(ctx, R.drawable.ic_heart, theme.heart, 15)
        tints.add(Pair(userIv, 1))
        tints.add(Pair(heartIv, 3))
        for (t in listOf(viewersTv, likesTv)) {
            t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
            t.setTypeface(Typeface.DEFAULT_BOLD)
            t.setSingleLine(true)
            labels.add(Pair(t, 0))
        }
        stats.orientation = LinearLayout.HORIZONTAL
        stats.gravity = Gravity.CENTER_VERTICAL
        stats.setPadding(dp(16), 0, 0, 0)
        stats.addView(liveIv)
        stats.addView(gap(10))
        stats.addView(userIv)
        stats.addView(gap(5))
        stats.addView(viewersTv)
        stats.addView(gap(14))
        stats.addView(heartIv)
        stats.addView(gap(5))
        stats.addView(likesTv)

        expandIv = iconView(ctx, R.drawable.ic_expand, theme.text, 18)
        tints.add(Pair(expandIv, 0))
        val expandBtn = roundButton(expandIv, "Make the panel bigger") { host.toggleExpand() }
        val tuckIv = iconView(ctx, R.drawable.ic_dock, theme.text, 18)
        tints.add(Pair(tuckIv, 0))
        val tuckBtn = roundButton(tuckIv, "Tuck into a small tab") { host.tuck() }

        header.orientation = LinearLayout.HORIZONTAL
        header.gravity = Gravity.CENTER_VERTICAL
        header.setPadding(0, 0, dp(16), 0)
        header.addView(stats, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1f))
        header.addView(expandBtn, LinearLayout.LayoutParams(dp(34), dp(34)).also { it.rightMargin = dp(8) })
        header.addView(tuckBtn, LinearLayout.LayoutParams(dp(34), dp(34)))
        header.setOnTouchListener(HeaderDrag())

        statusTv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
        statusTv.setPadding(dp(16), 0, dp(16), dp(6))
        statusTv.maxLines = 1
        statusTv.ellipsize = TextUtils.TruncateAt.END
        statusTv.visibility = View.GONE

        // ---- chat -----------------------------------------------------------------------------------------------------------------------
        list.orientation = LinearLayout.VERTICAL
        list.setPadding(dp(16), dp(8), dp(16), dp(12))
        scroll.addView(list)
        scroll.isVerticalScrollBarEnabled = false
        scroll.isVerticalFadingEdgeEnabled = true
        scroll.setFadingEdgeLength(dp(20))
        scroll.overScrollMode = View.OVER_SCROLL_NEVER

        // ---- message box (only when SavahBot lets this phone send, and it is switched on in the app) -----------------------------------------
        noteTv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
        noteTv.setPadding(dp(16), 0, dp(16), dp(4))
        noteTv.maxLines = 1
        noteTv.ellipsize = TextUtils.TruncateAt.END
        noteTv.visibility = View.GONE
        input = ChatInput(ctx) { host.keyboard(false) }
        input.hint = "Message chat"
        input.setSingleLine(true)
        input.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        input.imeOptions = EditorInfo.IME_ACTION_SEND or EditorInfo.IME_FLAG_NO_EXTRACT_UI
        input.filters = arrayOf<InputFilter>(InputFilter.LengthFilter(200))
        input.setPadding(dp(14), dp(8), dp(14), dp(8))
        input.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                submit()
                true
            } else {
                false
            }
        }
        input.setOnTouchListener { _, e ->
            if (e.actionMasked == MotionEvent.ACTION_DOWN) host.keyboard(true)
            false
        }
        sendIv = iconView(ctx, R.drawable.ic_send, theme.bg, 18)
        sendBtn.addView(sendIv, FrameLayout.LayoutParams(dp(18), dp(18), Gravity.CENTER))
        sendBtn.contentDescription = "Send"
        sendBtn.isClickable = true
        sendBtn.setOnClickListener { submit() }
        composer.orientation = LinearLayout.HORIZONTAL
        composer.gravity = Gravity.CENTER_VERTICAL
        composer.setPadding(dp(12), dp(4), dp(12), dp(12))
        composer.addView(input, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        composer.addView(sendBtn, LinearLayout.LayoutParams(dp(40), dp(40)).also { it.leftMargin = dp(8) })
        composer.visibility = View.GONE

        // ---- pinned line: tap it to let go ---------------------------------------------------------------------------------------------------
        pinIv = iconView(ctx, R.drawable.ic_pin, theme.accent, 14)
        tints.add(Pair(pinIv, 2))
        pinTv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        pinTv.maxLines = 3
        pinTv.ellipsize = TextUtils.TruncateAt.END
        pinCard.orientation = LinearLayout.HORIZONTAL
        pinCard.gravity = Gravity.CENTER_VERTICAL
        pinCard.setPadding(dp(12), dp(8), dp(12), dp(8))
        pinCard.addView(pinIv, LinearLayout.LayoutParams(dp(14), dp(14)).also { it.rightMargin = dp(8) })
        pinCard.addView(pinTv, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        pinCard.contentDescription = "Pinned message. Tap to unpin."
        pinCard.isClickable = true
        pinCard.setOnClickListener { host.pin(null) }
        pinCard.visibility = View.GONE

        // ---- moderation bar: appears after a long press on a line ---------------------------------------------------------------------------------
        modName.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
        modName.maxLines = 1
        modName.ellipsize = TextUtils.TruncateAt.END
        modBar.orientation = LinearLayout.HORIZONTAL
        modBar.gravity = Gravity.CENTER_VERTICAL
        modBar.setPadding(dp(12), dp(6), dp(12), dp(6))
        modBar.addView(modName, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        fun modChip(label: String, onClick: () -> Unit): TextView {
            val t = TextView(ctx)
            t.text = label
            t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
            t.setTypeface(Typeface.DEFAULT_BOLD)
            t.setPadding(dp(10), dp(6), dp(10), dp(6))
            t.isClickable = true
            t.setOnClickListener { onClick() }
            modChips.add(t)
            modBar.addView(t, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).also { it.leftMargin = dp(6) })
            return t
        }
        modChip("Hide") { modLine?.let { host.moderate(it, "delete") }; closeMod() }
        modChip("Time out 5 min") { modLine?.let { host.moderate(it, "timeout") }; closeMod() }
        modChip("Cancel") { closeMod() }
        modBar.visibility = View.GONE

        column.orientation = LinearLayout.VERTICAL
        column.addView(header, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(50)))
        column.addView(divider, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 1))
        column.addView(statusTv, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).also { it.topMargin = dp(6) })
        column.addView(pinCard, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).also { it.leftMargin = dp(12); it.rightMargin = dp(12); it.topMargin = dp(2) })
        column.addView(scroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        column.addView(modBar)
        column.addView(noteTv)
        column.addView(composer)

        view.addView(column, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        view.outlineProvider = object : ViewOutlineProvider() {
            override fun getOutline(v: View, outline: Outline) {
                outline.setRoundRect(0, 0, v.width, v.height, dp(20).toFloat())
            }
        }
        view.clipToOutline = true
        recolor()
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    private fun gap(w: Int): View {
        val v = View(ctx)
        v.layoutParams = LinearLayout.LayoutParams(dp(w), 1)
        return v
    }

    /** A round, softly tinted button with a ripple, holding one icon. */
    private fun roundButton(icon: ImageView, description: String, onClick: () -> Unit): FrameLayout {
        val box = FrameLayout(ctx)
        box.addView(icon, FrameLayout.LayoutParams(icon.layoutParams.width, icon.layoutParams.height, Gravity.CENTER))
        box.contentDescription = description
        box.isClickable = true
        box.setOnClickListener { onClick() }
        chips.add(box)
        return box
    }

    private fun paintChip(v: View) {
        fun disc(): GradientDrawable {
            val g = GradientDrawable()
            g.shape = GradientDrawable.OVAL
            g.setColor(Themes.withAlpha(theme.text, 12))
            return g
        }
        v.background = RippleDrawable(ColorStateList.valueOf(Themes.withAlpha(theme.text, 30)), disc(), disc())
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    /** One finger on the header (not on a button) moves the whole window. */
    private inner class HeaderDrag : View.OnTouchListener {
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
                    host.moveStart()
                    return true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX
                    val dy = e.rawY - downY
                    if (!moved && (abs(dx) > slop || abs(dy) > slop)) {
                        moved = true
                        outline(true)
                    }
                    if (moved) host.moveBy(dx.toInt(), dy.toInt())
                    return true
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    if (moved) outline(false)
                    host.moveEnd()
                    return true
                }
            }
            return false
        }
    }

    /** A thin outline while the window is being moved or resized, so you can see it is held. */
    fun outline(on: Boolean) {
        if (!on) {
            view.foreground = null
            return
        }
        val g = GradientDrawable()
        g.setColor(Color.TRANSPARENT)
        g.setCornerRadius(dp(20).toFloat())
        g.setStroke(dp(2), theme.accent)
        view.foreground = g
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    fun setExpanded(on: Boolean) {
        expandIv.setImageResource(if (on) R.drawable.ic_collapse else R.drawable.ic_expand)
        (expandIv.parent as? View)?.contentDescription = if (on) "Make the panel smaller" else "Make the panel bigger"
    }

    fun setLook(t: Theme, opacityPct: Int, baseFontSp: Float, textScalePct: Int, cap: Int) {
        // Called on every change anywhere: do nothing unless something the panel draws actually changed.
        if (t.id == theme.id && t.bg == theme.bg && t.text == theme.text && t.accent == theme.accent && t.surface == theme.surface && t.muted == theme.muted &&
            opacityPct == opacity && baseFontSp == fontSp && textScalePct == textScale && cap == chatCap) return
        theme = t
        opacity = opacityPct
        fontSp = baseFontSp
        textScale = textScalePct
        chatCap = cap
        recolor()
    }

    fun setHeader(viewers: String, likes: String, dot: Int, status: String, alert: Boolean) {
        viewersTv.text = viewers
        likesTv.text = likes
        dotKind = dot
        liveIv.setColorFilter(dotColor())
        statusText = status
        bannerAlert = alert
        redrawStatus()
    }

    /** The status line: calm grey normally; on a bad connection a clear amber banner you cannot miss. */
    private fun redrawStatus() {
        statusTv.text = statusText
        statusTv.setTextColor(if (bannerAlert) AMBER else theme.muted)
        statusTv.visibility = if (statusText.isEmpty()) View.GONE else View.VISIBLE
        if (bannerAlert) {
            val g = GradientDrawable()
            g.setCornerRadius(dp(10).toFloat())
            g.setColor(Themes.withAlpha(AMBER, 36))
            statusTv.background = g
            statusTv.setTypeface(Typeface.DEFAULT_BOLD)
            statusTv.setPadding(dp(12), dp(5), dp(12), dp(5))
        } else {
            statusTv.background = null
            statusTv.setTypeface(Typeface.DEFAULT)
            statusTv.setPadding(dp(16), 0, dp(16), dp(6))
        }
    }

    /** A milestone: the numbers pulse and the status line says what was reached for a few seconds. */
    fun celebrate(text: String) {
        main.removeCallbacks(endCelebrate)
        statusTv.text = text
        statusTv.setTextColor(theme.accent)
        statusTv.setTypeface(Typeface.DEFAULT_BOLD)
        statusTv.background = null
        statusTv.setPadding(dp(16), 0, dp(16), dp(6))
        statusTv.visibility = View.VISIBLE
        stats.pivotX = 0f
        stats.pivotY = stats.height / 2f
        stats.animate().cancel()
        stats.scaleX = 1f
        stats.scaleY = 1f
        stats.animate().scaleX(1.18f).scaleY(1.18f).setDuration(160).withEndAction {
            stats.animate().scaleX(1f).scaleY(1f).setDuration(260).setInterpolator(OvershootInterpolator(2.5f)).start()
        }.start()
        main.postDelayed(endCelebrate, 3500)
    }

    // ---- pin and moderation -----------------------------------------------------------------------------------------------------------------
    /** Which things a tap or a long press on a chat line may do (each is a switch in the app; moderating also needs SavahBot's permission). */
    fun setInteractions(pin: Boolean, moderate: Boolean) {
        if (pin == pinOn && moderate == modOn) return
        pinOn = pin
        modOn = moderate
        if (!moderate) closeMod()
        for (r in rows) bindRow(r)
    }

    fun setPin(line: Line?) {
        pinned = line
        if (line == null) {
            pinCard.visibility = View.GONE
            return
        }
        pinTv.text = ChatStyle.render(theme, line)
        pinCard.visibility = View.VISIBLE
    }

    private fun realLine(tv: TextView): Line? {
        val l = tv.tag as? Line ?: return null
        return if (l.level == "note" || l.id <= 0L) null else l
    }

    private fun bindRow(tv: TextView) {
        val line = realLine(tv)
        if (line != null && pinOn) tv.setOnClickListener { host.pin(line) } else { tv.setOnClickListener(null); tv.isClickable = false }
        if (line != null && modOn && line.level != "owner") {
            tv.setOnLongClickListener {
                tv.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
                openMod(line)
                true
            }
        } else {
            tv.setOnLongClickListener(null)
            tv.isLongClickable = false
        }
    }

    private fun openMod(line: Line) {
        modLine = line
        modName.text = line.name
        modBar.visibility = View.VISIBLE
    }

    private fun closeMod() {
        modLine = null
        modBar.visibility = View.GONE
    }

    /** A short message under the chat (an answer to a moderation tap, or a send error). */
    fun showNote(text: String, warn: Boolean) {
        noteTv.text = text
        noteTv.setTextColor(if (warn) AMBER else theme.muted)
        noteTv.visibility = View.VISIBLE
        main.removeCallbacks(hideNote)
        main.postDelayed(hideNote, 4000)
    }

    private fun dotColor(): Int = when (dotKind) {
        0 -> theme.accent
        1 -> AMBER
        else -> theme.muted
    }

    private fun paintBackground() {
        val top = Themes.mix(theme.bg, theme.text, 0.06f)
        val g = GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, intArrayOf(Themes.withAlpha(top, opacity), Themes.withAlpha(theme.bg, opacity)))
        g.setCornerRadius(dp(20).toFloat())
        g.setStroke(dp(1), Themes.withAlpha(theme.text, 26))
        view.background = g
    }

    private fun roleColor(role: Int): Int = when (role) {
        0 -> theme.text
        1 -> theme.muted
        2 -> theme.accent
        else -> theme.heart
    }

    private fun shadowFor(t: TextView) {
        if (opacity < 65) t.setShadowLayer(4f, 0f, 1f, if (Themes.luminance(theme.bg) < 0.5) 0xCC000000.toInt() else 0xCCFFFFFF.toInt())
        else t.setShadowLayer(0f, 0f, 0f, 0)
    }

    private fun recolor() {
        paintBackground()
        for ((iv, role) in tints) iv.setColorFilter(roleColor(role))
        for ((tv, role) in labels) {
            tv.setTextColor(roleColor(role))
            shadowFor(tv)
        }
        liveIv.setColorFilter(dotColor())
        for (c in chips) paintChip(c)
        divider.setBackgroundColor(Themes.withAlpha(theme.text, 16))
        redrawStatus()
        noteTv.setTextColor(theme.muted)
        val pg = GradientDrawable()
        pg.setCornerRadius(dp(12).toFloat())
        pg.setColor(Themes.withAlpha(theme.accent, 30))
        pg.setStroke(dp(1), Themes.withAlpha(theme.accent, 90))
        pinCard.background = pg
        pinTv.setTextColor(theme.text)
        pinned?.let { pinTv.text = ChatStyle.render(theme, it) }
        modName.setTextColor(theme.muted)
        for (m in modChips) {
            val mg = GradientDrawable()
            mg.setCornerRadius(dp(12).toFloat())
            mg.setColor(Themes.withAlpha(theme.accent, 34))
            m.background = mg
            m.setTextColor(theme.text)
        }
        val field = GradientDrawable()
        field.setCornerRadius(dp(20).toFloat())
        field.setColor(Themes.withAlpha(theme.text, 12))
        field.setStroke(dp(1), Themes.withAlpha(theme.text, 26))
        input.background = field
        input.setTextColor(theme.text)
        input.setHintTextColor(theme.muted)
        val send = GradientDrawable()
        send.shape = GradientDrawable.OVAL
        send.setColor(theme.accent)
        sendBtn.background = send
        sendIv.setColorFilter(if (Themes.contrast(theme.bg, theme.accent) > Themes.contrast(theme.text, theme.accent)) theme.bg else theme.text)
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
        tv.setPadding(0, dp(4), 0, dp(4))
        tv.setLineSpacing(0f, 1.08f)
        styleRow(tv)
        tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, fontSp * textScale / 100f)
        bindRow(tv)
        return tv
    }

    /** Rebuilds the list from the controller's model (when the panel opens, or after a purge). */
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

    // ---- message box -------------------------------------------------------------------------------------------------------------------------
    fun setComposer(on: Boolean) {
        if (on == composerOn) return
        composerOn = on
        composer.visibility = if (on) View.VISIBLE else View.GONE
        if (!on) {
            noteTv.visibility = View.GONE
            hideKeyboard()
            host.keyboard(false)
        }
    }

    private fun submit() {
        if (sending) return
        val text = input.text.toString().trim()
        if (text.isEmpty()) return
        sending = true
        sendBtn.alpha = 0.5f
        host.send(text)
    }

    /** The answer to a send. On success the box empties and the keyboard stays up for the next line; on failure the text is kept so nothing is lost. */
    fun sendResult(error: String) {
        sending = false
        sendBtn.alpha = 1f
        if (error.isEmpty()) {
            input.setText("")
            return
        }
        showNote(error, true)
    }

    fun focusInput() {
        input.requestFocus()
        val imm = ctx.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
        imm.showSoftInput(input, InputMethodManager.SHOW_IMPLICIT)
    }

    fun hideKeyboard() {
        val imm = ctx.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
        imm.hideSoftInputFromWindow(input.windowToken, 0)
        input.clearFocus()
    }
}
