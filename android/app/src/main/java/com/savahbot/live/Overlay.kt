package com.savahbot.live

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.PixelFormat
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.WindowManager
import android.view.animation.DecelerateInterpolator

/**
 * Controls the two forms of the floating UI and what they show.
 *  - [PanelView]: the full window (chat, stats, tray). Free-floating, draggable by its bars, resizable proportionally from the bottom corners.
 *  - [TabWindow]: the box on a screen edge it tucks into (tap the X, or drag the panel off the edge).
 * It keeps the one chat model, theme and settings, and feeds whichever window is showing. It draws what SavahBot sent; it decides nothing.
 */
class Overlay(
    private val ctx: Context,
    private val store: Store,
    private val onStop: () -> Unit,
    private val onLockChanged: (Boolean) -> Unit
) : PanelView.Host {
    private companion object {
        const val MIN_SCALE = 0.5f
        const val MAX_SCALE = 1.6f
        val SIZE_PRESETS = floatArrayOf(0.7f, 1.0f, 1.3f)
    }

    private val wm = ctx.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val main = Handler(Looper.getMainLooper())
    private fun dp(v: Int): Int = dpOf(ctx, v)
    private fun screenW(): Int = ctx.resources.displayMetrics.widthPixels
    private fun screenH(): Int = ctx.resources.displayMetrics.heightPixels

    // ---- model ---------------------------------------------------------------------------------------------------------------------------
    private val lines = ArrayList<Line>()
    private val shown = HashSet<Long>()
    private var prefs = Prefs(40, 5, 14, 3)
    private var link = Link.CONNECTING
    private var detail = ""
    private var state = State("live", false, "")
    private var stats: Stats? = null
    private var lastData = 0L
    private var notice = ""
    private var locked = false

    // ---- windows -------------------------------------------------------------------------------------------------------------------------
    private val panel = PanelView(ctx, store, this)
    private val tab = TabWindow(ctx, wm, store) { openPanel() }
    private var panelShown = false
    private var scale = 1f
    private var anim: ValueAnimator? = null
    private val panelParams = WindowManager.LayoutParams(
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
        PixelFormat.TRANSLUCENT
    )
    private var dragStartX = 0
    private var dragStartY = 0
    private var anchorX = 0f
    private var anchorY = 0f
    private var corner = -1
    private val staleCheck = Runnable { redrawHeader() }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    fun show(): Boolean {
        applyLook()
        redrawHeader()
        val ok = if (store.panelOpen) showPanel() else tab.show(null, null)
        if (!ok) hide()
        return ok
    }

    fun hide() {
        main.removeCallbacksAndMessages(null)
        anim?.cancel()
        anim = null
        removePanel()
        tab.hide()
    }

    fun onScreenChanged() {
        if (panelShown) {
            scale = effectiveScale()
            panel.setScale(scale)
            sizeToScale()
            placeFromFractions()
            update()
        }
        tab.onScreenChanged()
    }

    // ---- panel window --------------------------------------------------------------------------------------------------------------------
    private fun effectiveScale(): Float =
        Geo.clampScale(store.panelScale / 100f, MIN_SCALE, Geo.maxScale(panel.baseW, panel.baseH, screenW(), screenH(), dp(8), MIN_SCALE, MAX_SCALE))

    private fun sizeToScale() {
        panelParams.width = (panel.baseW * scale).toInt()
        panelParams.height = (panel.baseH * scale).toInt()
    }

    private fun placeFromFractions() {
        val sw = screenW()
        val sh = screenH()
        panelParams.gravity = Gravity.TOP or Gravity.LEFT
        panelParams.x = Geo.clampInto((store.panelFx / 1000f * (sw - panelParams.width)).toInt(), panelParams.width, sw)
        panelParams.y = Geo.clampInto((store.panelFy / 1000f * (sh - panelParams.height)).toInt(), panelParams.height, sh)
    }

    private fun savePanelPosition() {
        val roomX = screenW() - panelParams.width
        val roomY = screenH() - panelParams.height
        store.panelFx = if (roomX > 0) (panelParams.x * 1000L / roomX).toInt().coerceIn(0, 1000) else 500
        store.panelFy = if (roomY > 0) (panelParams.y * 1000L / roomY).toInt().coerceIn(0, 1000) else 300
    }

    private fun showPanel(): Boolean {
        scale = effectiveScale()
        panel.setScale(scale)
        sizeToScale()
        placeFromFractions()
        panel.setLines(lines)
        panel.setLocked(locked)
        applyLockFlag()
        return try {
            wm.addView(panel.root, panelParams)
            panelShown = true
            store.panelOpen = true
            panel.root.alpha = 0f
            panel.root.animate().alpha(1f).setDuration(160).start()
            true
        } catch (e: Exception) {
            false          // no overlay permission, or the system refused: the service stops
        }
    }

    private fun removePanel() {
        if (!panelShown) return
        panel.closeTray()
        try {
            wm.removeView(panel.root)
        } catch (e: Exception) {
            // already gone
        }
        panelShown = false
    }

    private fun update() {
        if (!panelShown) return
        try {
            wm.updateViewLayout(panel.root, panelParams)
        } catch (e: Exception) {
            // the window is being torn down
        }
    }

    private fun applyLockFlag() {
        panelParams.flags = if (locked) panelParams.flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        else panelParams.flags and WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE.inv()
    }

    fun setLocked(on: Boolean) {
        locked = on
        panel.setLocked(on)
        applyLockFlag()
        update()
    }

    /** Panel's tray button. Locking makes touches pass through the panel, so it can only be unlocked from the notification. */
    override fun toggleLock() {
        setLocked(!locked)
        onLockChanged(locked)
    }

    // ---- opening and tucking -------------------------------------------------------------------------------------------------------------
    private fun openPanel() {
        tab.hide()
        if (!showPanel()) tab.show(null, null)
    }

    private fun tuckInto(e: Edge) {
        val sw = screenW()
        val sh = screenH()
        val cx = panelParams.x + panelParams.width / 2f
        val cy = panelParams.y + panelParams.height / 2f
        val vertical = e == Edge.LEFT || e == Edge.RIGHT
        val fraction = if (vertical) (cy / sh).coerceIn(0f, 1f) else (cx / sw).coerceIn(0f, 1f)
        savePanelPosition()
        removePanel()
        store.panelOpen = false
        if (!tab.show(e, fraction)) showPanel()
    }

    override fun tuck() {
        val cx = panelParams.x + panelParams.width / 2f
        val cy = panelParams.y + panelParams.height / 2f
        tuckInto(Geo.nearestEdge(cx, cy, screenW(), screenH()))
    }

    override fun stopOverlay() {
        onStop()
    }

    // ---- dragging ------------------------------------------------------------------------------------------------------------------------
    override fun dragStart() {
        anim?.cancel()
        dragStartX = panelParams.x
        dragStartY = panelParams.y
    }

    override fun dragBy(dx: Float, dy: Float) {
        val w = panelParams.width
        val h = panelParams.height
        // it may be pulled up to 60% past an edge; letting go that far out tucks it into that edge
        panelParams.x = (dragStartX + dx).toInt().coerceIn((-0.6f * w).toInt(), screenW() - (0.4f * w).toInt())
        panelParams.y = (dragStartY + dy).toInt().coerceIn((-0.6f * h).toInt(), screenH() - (0.4f * h).toInt())
        update()
    }

    override fun dragEnd() {
        val w = panelParams.width
        val h = panelParams.height
        val e = Geo.overshootEdge(panelParams.x, panelParams.y, w, h, screenW(), screenH(), 0.35f)
        if (e != null) {
            tuckInto(e)
            return
        }
        val toX = Geo.clampInto(panelParams.x, w, screenW())
        val toY = Geo.clampInto(panelParams.y, h, screenH())
        val fromX = panelParams.x
        val fromY = panelParams.y
        if (fromX == toX && fromY == toY) {
            savePanelPosition()
            return
        }
        val a = ValueAnimator.ofFloat(0f, 1f)
        a.duration = 160
        a.interpolator = DecelerateInterpolator()
        a.addUpdateListener {
            val t = it.animatedValue as Float
            panelParams.x = (fromX + (toX - fromX) * t).toInt()
            panelParams.y = (fromY + (toY - fromY) * t).toInt()
            update()
        }
        a.addListener(object : android.animation.AnimatorListenerAdapter() {
            override fun onAnimationEnd(animation: android.animation.Animator) {
                savePanelPosition()
            }
        })
        anim = a
        a.start()
    }

    // ---- resizing (proportional, from the bottom corners) ----------------------------------------------------------------------------------
    override fun resizeStart(corner: Int) {
        this.corner = corner
        anchorX = if (corner == 2) (panelParams.x + panelParams.width).toFloat() else panelParams.x.toFloat()    // the top corner opposite the one being dragged
        anchorY = panelParams.y.toFloat()
    }

    override fun resizeTo(rawX: Float, rawY: Float) {
        if (corner < 0) return
        val maxS = Geo.maxScale(panel.baseW, panel.baseH, screenW(), screenH(), dp(8), MIN_SCALE, MAX_SCALE)
        scale = Geo.clampScale(Geo.scaleFromDrag(anchorX, anchorY, rawX, rawY, panel.baseW, panel.baseH), MIN_SCALE, maxS)
        panel.setScale(scale)
        sizeToScale()
        panelParams.x = if (corner == 2) (anchorX - panelParams.width).toInt() else anchorX.toInt()
        panelParams.y = anchorY.toInt()
        update()
    }

    override fun resizeEnd() {
        if (corner < 0) return
        corner = -1
        store.panelScale = Math.round(scale * 100f)
        panelParams.x = Geo.clampInto(panelParams.x, panelParams.width, screenW())
        panelParams.y = Geo.clampInto(panelParams.y, panelParams.height, screenH())
        update()
        savePanelPosition()
    }

    /** The expand button: small, medium, large. */
    override fun cycleSize() {
        val maxS = Geo.maxScale(panel.baseW, panel.baseH, screenW(), screenH(), dp(8), MIN_SCALE, MAX_SCALE)
        var next = SIZE_PRESETS[0]
        for (p in SIZE_PRESETS) {
            if (p > scale + 0.05f) {
                next = p
                break
            }
        }
        scale = Geo.clampScale(next, MIN_SCALE, maxS)
        store.panelScale = Math.round(scale * 100f)
        panel.setScale(scale)
        sizeToScale()
        panelParams.x = Geo.clampInto(panelParams.x, panelParams.width, screenW())
        panelParams.y = Geo.clampInto(panelParams.y, panelParams.height, screenH())
        update()
        savePanelPosition()
    }

    // ---- look and settings ---------------------------------------------------------------------------------------------------------------
    override fun settingsChanged() {
        applyLook()
    }

    private fun applyLook() {
        val theme = Themes.byId(store.themeId, store.customHue, store.customLight)
        panel.setLook(theme, store.panelOpacity, prefs.fontSize.toFloat(), store.textScale, prefs.chatLines)
        tab.setLook(theme, store.tabFade, prefs.hideSeconds, prefs.peekSeconds, prefs.fontSize.toFloat())
    }

    // ---- what SavahBot sends -------------------------------------------------------------------------------------------------------------
    fun setLink(l: Link, d: String) {
        link = l
        detail = d
        main.removeCallbacks(staleCheck)
        if (l == Link.ONLINE) lastData = System.currentTimeMillis() else main.postDelayed(staleCheck, 31_000)
        redrawHeader()
    }

    fun setState(s: State) {
        state = s
        redrawHeader()
    }

    fun setStats(s: Stats) {
        stats = s
        lastData = System.currentTimeMillis()
        redrawHeader()
    }

    fun setPrefs(p: Prefs) {
        prefs = p
        applyLook()
        trim()
        if (panelShown) panel.setLines(lines)
    }

    fun showNotice(text: String) {
        notice = text
        redrawHeader()
    }

    private fun trim() {
        while (lines.size > prefs.chatLines) {
            val old = lines.removeAt(0)
            shown.remove(old.id)
        }
    }

    fun addChat(newLines: List<Line>, skipped: Int) {
        val fresh = ArrayList<Line>()
        if (skipped > 0) fresh.add(Line(0, "", "", "+$skipped more messages", "note"))
        for (l in newLines) {
            if (l.id == 0L || shown.add(l.id)) fresh.add(l)
        }
        if (fresh.isEmpty()) return
        lines.addAll(fresh)
        trim()
        if (panelShown) panel.addLines(fresh) else tab.pop(fresh)
    }

    fun purge(uids: List<String>, ids: List<Long>) {
        val iter = lines.iterator()
        var changed = false
        while (iter.hasNext()) {
            val l = iter.next()
            if ((l.id > 0 && ids.contains(l.id)) || (l.uid.isNotEmpty() && uids.contains(l.uid))) {
                iter.remove()
                shown.remove(l.id)
                changed = true
            }
        }
        if (changed && panelShown) panel.setLines(lines)
    }

    /** The numbers and the status line, worked out once and given to both windows. Nothing is shown as live when it is not. */
    private fun redrawHeader() {
        val fresh = link == Link.ONLINE || System.currentTimeMillis() - lastData < 30_000
        val s = stats
        val canShow = fresh && s != null && s.enabled && state.live
        val viewers = if (canShow && s != null) Fmt.count(s.viewers) else Fmt.count(null)
        val likes = if (canShow && s != null && !s.likesHidden) Fmt.count(s.likes) else Fmt.count(null)
        val dot = when {
            link == Link.ONLINE && state.live -> 0
            link == Link.CONNECTING || link == Link.RECONNECTING || link == Link.WAITING -> 1
            else -> 2
        }
        var text = ""
        var alert = false
        when {
            notice.isNotEmpty() -> {
                text = notice
                alert = true
            }
            link == Link.CONNECTING -> text = "Connecting\u2026"
            link == Link.RECONNECTING -> {
                text = "Reconnecting\u2026"
                alert = true
            }
            link == Link.WAITING -> {
                text = detail
                alert = true
            }
            link == Link.ONLINE && state.mode == "demo" -> text = "Demo mode"
            link == Link.ONLINE && !state.live -> text = "Waiting for your stream"
            link == Link.ONLINE && state.title.isNotEmpty() -> text = state.title
        }
        panel.setHeader(viewers, likes, dot, text, alert)
        tab.setHeader(viewers, likes, dot)
    }
}
