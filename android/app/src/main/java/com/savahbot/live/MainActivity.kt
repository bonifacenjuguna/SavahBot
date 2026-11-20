package com.savahbot.live

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.text.DateFormat
import java.util.Date

/**
 * The only screen, in three stages: Pair (once), Allow (the floating-window permission, once), Go (start and stop the overlay, and choose how the overlay looks).
 * No accounts and no dashboard: SavahBot (Manage > SavahLive) holds what the stream shows. Everything about how the panel, tab and pop-outs look and behave is here,
 * so the panel itself only carries what you need while playing. Changes apply to the open overlay at once.
 */
class MainActivity : Activity() {
    private companion object {
        const val ASK_NOTIFICATIONS = 7
    }

    private lateinit var store: Store
    private lateinit var ui: Ui
    private val main = Handler(Looper.getMainLooper())
    private var typedCode = ""
    private var typedServer = ""
    private var showServer = false
    private var message = ""
    private var messageIsError = true
    private var pairing = false
    private var autoPair: PairInput? = null
    private var autoOpened = false
    private var presetName = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = Store(this)
        ui = Ui(this)
        window.statusBarColor = Ui.BG
        window.navigationBarColor = Ui.BG
        take(intent)
        render()
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        take(intent)
        render()
    }

    override fun onResume() {
        super.onResume()
        // "Start the overlay when this app opens": once per launch of the app, and never behind the person's back after they pressed Stop
        if (store.autoOpen && !autoOpened && store.isPaired && Settings.canDrawOverlays(this) && !OverlayService.running) {
            autoOpened = true
            OverlayService.start(this)
        }
        render()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        render()
    }

    /** A savahlive://pair?... link (from the button on SavahBot's pairing page) pairs straight away. */
    private fun take(i: Intent?) {
        if (i == null) return
        val link = i.data ?: return
        if (i.action == Intent.ACTION_VIEW && link.scheme == "savahlive") {
            val input = Pairing.parse(link.toString())
            if (input != null) {
                autoPair = input
            } else {
                message = "That pairing link is not complete. Make a new one in SavahBot."
                messageIsError = true
            }
            i.data = null
        }
    }

    private fun stage(): Int = when {
        !store.isPaired -> 0
        !Settings.canDrawOverlays(this) -> 1
        else -> 2
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    private fun render() {
        val stage = stage()
        val col = LinearLayout(this)
        col.orientation = LinearLayout.VERTICAL
        col.setPadding(ui.dp(22), ui.dp(30), ui.dp(22), ui.dp(26))

        brand(col, stage != 2)
        if (stage < 2) col.addView(ui.stepBar(stage))
        when (stage) {
            0 -> pairStage(col)
            1 -> allowStage(col)
            else -> homeStage(col)
        }
        col.addView(ui.space(6))
        col.addView(ui.text("SavahLive " + BuildConfig.VERSION_NAME + "  \u00B7  SavahBot does the work, SavahLive shows the results.", 12f, Ui.MUTED))

        val scroll = ScrollView(this)
        scroll.setBackgroundColor(Ui.BG)
        scroll.isFillViewport = true
        scroll.isVerticalScrollBarEnabled = false
        scroll.addView(col)
        setContentView(scroll)

        val auto = autoPair
        if (auto != null) {
            autoPair = null
            if (!store.isPaired) pair(auto)
        }
    }

    private fun brand(col: LinearLayout, big: Boolean) {
        if (big) {
            val logo = ImageView(this)
            logo.setImageResource(R.drawable.logo_icon)
            col.addView(logo, LinearLayout.LayoutParams(ui.dp(72), ui.dp(72)))
            col.addView(ui.space(16))
            col.addView(ui.wordmark(36f))
            col.addView(ui.space(6))
            col.addView(ui.text("Your stream chat, viewers and likes, floating over any game.", 16f, Ui.MUTED))
            col.addView(ui.space(24))
        } else {
            val row = LinearLayout(this)
            row.orientation = LinearLayout.HORIZONTAL
            row.gravity = Gravity.CENTER_VERTICAL
            val logo = ImageView(this)
            logo.setImageResource(R.drawable.logo_icon)
            row.addView(logo, LinearLayout.LayoutParams(ui.dp(44), ui.dp(44)))
            row.addView(ui.wordmark(26f), LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).also { it.leftMargin = ui.dp(12) })
            row.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).also { it.bottomMargin = ui.dp(20) }
            col.addView(row)
        }
    }

    // ---- stage 0: pair ----------------------------------------------------------------------------------------------------------------------
    private fun pairStage(col: LinearLayout) {
        if (store.notice.isNotEmpty()) {
            val n = ui.card(16)
            n.background = ui.round(0x26F5B301, 20, 0x55F5B301, 1)
            n.addView(ui.text(store.notice, 14f, Ui.AMBER))
            col.addView(n)
        }
        val c = ui.card()
        c.addView(ui.text("Link your SavahBot", 22f, Ui.INK, true))
        c.addView(ui.space(4))
        c.addView(ui.text("You only do this once.", 14f, Ui.MUTED))
        c.addView(ui.space(12))
        c.addView(ui.numberedStep(1, "In SavahBot open Manage, then SavahLive, then Pair a phone."))
        c.addView(ui.numberedStep(2, "Scan the QR with your camera and tap Open SavahLive."))
        c.addView(ui.numberedStep(3, "Or paste the link, or type the code, below."))
        c.addView(ui.space(12))

        val row = LinearLayout(this)
        row.orientation = LinearLayout.HORIZONTAL
        row.gravity = Gravity.CENTER_VERTICAL
        val code = ui.field("Pairing link or code", typedCode) { typedCode = it }
        code.letterSpacing = 0.06f
        row.addView(code, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        val paste = LinearLayout(this)
        paste.gravity = Gravity.CENTER
        paste.background = ui.round(Ui.RAISED, 16, Ui.LINE, 1)
        paste.addView(ui.icon(R.drawable.ic_paste, Ui.INK, 22), LinearLayout.LayoutParams(ui.dp(22), ui.dp(22)))
        paste.isClickable = true
        paste.contentDescription = "Paste"
        paste.setOnClickListener { pasteFromClipboard() }
        row.addView(paste, LinearLayout.LayoutParams(ui.dp(52), ui.dp(52)).also { it.leftMargin = ui.dp(8) })
        c.addView(row)

        if (showServer) {
            c.addView(ui.space(8))
            c.addView(ui.field("SavahBot address, like https://yourbot.up.railway.app", typedServer) { typedServer = it })
        } else {
            val more = ui.button("Typing only the code? Add the address", null, Ui.QUIET) {
                showServer = true
                render()
            }
            c.addView(more)
        }
        val go = ui.button(if (pairing) "Pairing\u2026" else "Pair this phone", R.drawable.ic_check, Ui.PRIMARY) { onPairClicked() }
        ui.setEnabled(go, !pairing)
        c.addView(go)
        if (message.isNotEmpty()) {
            val m = ui.text(message, 14f, if (messageIsError && !pairing) Ui.AMBER else Ui.MUTED)
            m.setPadding(0, ui.dp(12), 0, 0)
            c.addView(m)
        }
        col.addView(c)
    }

    // ---- stage 1: allow the floating window -------------------------------------------------------------------------------------------------
    private fun allowStage(col: LinearLayout) {
        val c = ui.card()
        c.addView(ui.iconBadge(R.drawable.ic_layers, Ui.RED, 60))
        c.addView(ui.space(14))
        c.addView(ui.text("Let SavahLive float", 24f, Ui.INK, true))
        c.addView(ui.space(8))
        c.addView(ui.text("To sit above your game, Android needs one switch turned on for SavahLive: \u201CDisplay over other apps\u201D.", 15f, Ui.MUTED))
        c.addView(ui.space(12))
        c.addView(ui.numberedStep(1, "Tap the button. Android opens a settings page."))
        c.addView(ui.numberedStep(2, "Find SavahLive and turn the switch on."))
        c.addView(ui.numberedStep(3, "Press back. You land here, ready to go."))
        c.addView(ui.button("Open settings", R.drawable.ic_layers, Ui.PRIMARY) {
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
        })
        col.addView(c)
        optionalCards(col)
    }

    /** Notifications and battery: nice to have, never blocking. */
    private fun optionalCards(col: LinearLayout) {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            val n = ui.card(18)
            n.addView(ui.infoRow(R.drawable.ic_bell, Ui.AMBER, "Notifications (optional)", "Shows the Stop button while the overlay runs."))
            n.addView(ui.button("Allow notifications", null, Ui.SECONDARY) { requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), ASK_NOTIFICATIONS) })
            col.addView(n)
        }
        val power = getSystemService(Context.POWER_SERVICE) as PowerManager
        if (!power.isIgnoringBatteryOptimizations(packageName)) {
            val b = ui.card(18)
            b.addView(ui.infoRow(R.drawable.ic_power, Ui.GREEN, "Keep it running (optional)", "Some phones stop background apps during long games. Choose Unrestricted for SavahLive."))
            b.addView(ui.button("Open battery settings", null, Ui.SECONDARY) { startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) })
            col.addView(b)
        }
    }

    // ---- stage 2: go ------------------------------------------------------------------------------------------------------------------------
    private fun homeStage(col: LinearLayout) {
        val running = OverlayService.running
        val hero = ui.card(22)
        hero.background = GradientDrawable(GradientDrawable.Orientation.TL_BR, intArrayOf(if (running) 0xFF0F3D2E.toInt() else 0xFF2A1114.toInt(), Ui.CARD)).also {
            it.setCornerRadius(ui.dp(26).toFloat())
            it.setStroke(ui.dp(1), Ui.LINE)
        }
        val status = LinearLayout(this)
        status.orientation = LinearLayout.HORIZONTAL
        status.gravity = Gravity.CENTER_VERTICAL
        val dot = View(this)
        dot.background = ui.round(if (running) Ui.GREEN else Ui.MUTED, 6)
        status.addView(dot, LinearLayout.LayoutParams(ui.dp(12), ui.dp(12)))
        status.addView(ui.text(if (running) "On air" else "Ready", 14f, if (running) Ui.GREEN else Ui.MUTED, true), LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).also { it.leftMargin = ui.dp(8) })
        hero.addView(status)
        hero.addView(ui.space(10))
        hero.addView(ui.text(if (running) "Overlay is floating" else "Start the overlay", 26f, Ui.INK, true))
        hero.addView(ui.space(6))
        val sub = if (running && OverlayService.status.isNotEmpty()) OverlayService.status else "Then open PUBG Mobile or any app. SavahLive stays on top."
        hero.addView(ui.text(sub, 15f, Ui.MUTED))
        if (running) {
            hero.addView(ui.button("Stop overlay", R.drawable.ic_power, Ui.SECONDARY) {
                OverlayService.stop(this)
                main.postDelayed({ render() }, 500)
            })
        } else {
            hero.addView(ui.button("Start overlay", R.drawable.ic_live, Ui.PRIMARY) { startOverlay() })
        }
        if (message.isNotEmpty()) {
            val m = ui.text(message, 14f, Ui.AMBER)
            m.setPadding(0, ui.dp(10), 0, 0)
            hero.addView(m)
        }
        col.addView(hero)

        updateCard(col)
        summaryCard(col)
        looksCards(col)
        extrasCards(col)

        val how = ui.card(18)
        how.addView(ui.text("How the panel works", 18f, Ui.INK, true))
        how.addView(ui.space(6))
        how.addView(ui.infoRow(R.drawable.ic_move, Ui.RED, "Move it", "Drag the top row, where the viewers and likes are."))
        how.addView(ui.infoRow(R.drawable.ic_expand, Ui.RED, "Resize it", "Drag any edge or corner. The chat gets longer or wider."))
        how.addView(ui.infoRow(R.drawable.ic_collapse, Ui.RED, "Make it big", "Tap the expand button for a big window. Tap it again to go back."))
        how.addView(ui.infoRow(R.drawable.ic_dock, Ui.RED, "Tuck it away", "Tap the tuck button. It becomes a small tab on the screen edge. Tap the tab to open the panel, or drag it to another edge."))
        col.addView(how)

        val info = ui.card(18)
        info.addView(ui.text("This phone", 18f, Ui.INK, true))
        info.addView(ui.space(8))
        val host = Uri.parse(store.server).host ?: store.server
        val chips = LinearLayout(this)
        chips.orientation = LinearLayout.HORIZONTAL
        chips.addView(ui.chip(host, Ui.GREEN))
        info.addView(chips)
        info.addView(ui.space(8))
        info.addView(ui.text(store.deviceName, 15f, Ui.INK))
        info.addView(ui.text(
            if (store.expires == 0L) "Stays paired until you remove it in SavahBot."
            else "Pairing ends " + DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(store.expires)) + ".",
            13f, Ui.MUTED
        ))
        info.addView(ui.button("Unpair this phone", null, Ui.QUIET) { confirmUnpair() })
        col.addView(info)
        optionalCards(col)
    }

    // ---- how the overlay looks: sliders, switches and choices that apply to the open overlay at once ------------------------------------------
    private val matchWidth = LinearLayout.LayoutParams.MATCH_PARENT
    private val wrap = LinearLayout.LayoutParams.WRAP_CONTENT

    private fun sliderRow(title: String, body: String, min: Int, max: Int, value: Int, suffix: String, onChange: (Int) -> Unit): LinearLayout {
        val col = LinearLayout(this)
        col.orientation = LinearLayout.VERTICAL
        col.setPadding(0, ui.dp(10), 0, ui.dp(2))
        val top = LinearLayout(this)
        top.orientation = LinearLayout.HORIZONTAL
        top.gravity = Gravity.CENTER_VERTICAL
        val valueTv = ui.text("$value$suffix", 14f, Ui.MUTED)
        top.addView(ui.text(title, 15f, Ui.INK, true), LinearLayout.LayoutParams(0, wrap, 1f))
        top.addView(valueTv)
        col.addView(top)
        if (body.isNotEmpty()) col.addView(ui.text(body, 13f, Ui.MUTED))
        val slider = LineSlider(this)
        slider.min = min
        slider.max = max
        slider.value = value
        slider.trackColor = 0x33FFFFFF
        slider.fillColor = Ui.RED
        slider.thumbColor = Ui.INK
        slider.contentDescription = title
        slider.onChange = { v ->
            valueTv.text = "$v$suffix"
            onChange(v)
        }
        col.addView(slider, LinearLayout.LayoutParams(matchWidth, ui.dp(34)))
        return col
    }

    private fun toggleRow(title: String, body: String, on: Boolean, onChange: (Boolean) -> Unit): LinearLayout {
        val row = LinearLayout(this)
        row.orientation = LinearLayout.HORIZONTAL
        row.gravity = Gravity.CENTER_VERTICAL
        row.setPadding(0, ui.dp(10), 0, ui.dp(6))
        val col = LinearLayout(this)
        col.orientation = LinearLayout.VERTICAL
        col.addView(ui.text(title, 15f, Ui.INK, true))
        col.addView(ui.text(body, 13f, Ui.MUTED))
        row.addView(col, LinearLayout.LayoutParams(0, wrap, 1f))
        val pill = LinearLayout(this)
        pill.setPadding(ui.dp(3), 0, ui.dp(3), 0)
        val knob = View(this)
        knob.background = ui.round(Ui.INK, 11)
        pill.addView(knob, LinearLayout.LayoutParams(ui.dp(22), ui.dp(22)))
        var state = on
        fun paint() {
            pill.background = ui.round(if (state) Ui.RED else Ui.RAISED, 14, Ui.LINE, 1)
            pill.gravity = (if (state) Gravity.END else Gravity.START) or Gravity.CENTER_VERTICAL
        }
        paint()
        pill.isClickable = true
        pill.contentDescription = title
        pill.setOnClickListener {
            state = !state
            paint()
            onChange(state)
        }
        row.addView(pill, LinearLayout.LayoutParams(ui.dp(52), ui.dp(28)).also { it.leftMargin = ui.dp(12) })
        return row
    }

    private fun segmented(options: List<Pair<String, Int>>, current: Int, onPick: (Int) -> Unit): LinearLayout {
        val row = LinearLayout(this)
        row.orientation = LinearLayout.HORIZONTAL
        row.setPadding(0, ui.dp(8), 0, ui.dp(4))
        val cells = ArrayList<TextView>()
        fun paint(selected: Int) {
            for ((i, c) in cells.withIndex()) {
                val on = options[i].second == selected
                c.background = ui.round(if (on) Ui.RED else Ui.RAISED, 12, Ui.LINE, 1)
                c.setTextColor(if (on) Ui.INK else Ui.MUTED)
            }
        }
        for ((i, o) in options.withIndex()) {
            val c = ui.text(o.first, 13f, Ui.MUTED, true)
            c.gravity = Gravity.CENTER
            c.setPadding(0, ui.dp(10), 0, ui.dp(10))
            c.isClickable = true
            c.setOnClickListener {
                onPick(o.second)
                paint(o.second)
            }
            cells.add(c)
            row.addView(c, LinearLayout.LayoutParams(0, wrap, 1f).also { it.rightMargin = if (i < options.size - 1) ui.dp(6) else 0 })
        }
        paint(current)
        return row
    }

    /** Six themes and Custom. The panel, the tab and the pop-outs all take their colours from the one you pick. */
    private fun themeChooser(): LinearLayout {
        val box = LinearLayout(this)
        box.orientation = LinearLayout.VERTICAL
        val row = LinearLayout(this)
        row.orientation = LinearLayout.HORIZONTAL
        row.gravity = Gravity.CENTER_VERTICAL
        row.setPadding(0, ui.dp(8), 0, ui.dp(4))
        val custom = LinearLayout(this)
        custom.orientation = LinearLayout.VERTICAL
        val hue = LineSlider(this)
        hue.min = 0
        hue.max = 359
        hue.value = store.customHue
        hue.gradient = IntArray(7) { i -> Themes.hsl(i * 60 % 360, 0.85f, 0.55f) }
        hue.thumbColor = Ui.INK
        hue.contentDescription = "Colour"
        hue.onChange = { v -> store.customHue = v }
        val light = LineSlider(this)
        light.min = 8
        light.max = 94
        light.value = store.customLight
        light.gradient = intArrayOf(0xFF000000.toInt(), 0xFF808080.toInt(), 0xFFFFFFFF.toInt())
        light.thumbColor = Ui.INK
        light.contentDescription = "Light or dark"
        light.onChange = { v -> store.customLight = v }
        custom.addView(hue, LinearLayout.LayoutParams(matchWidth, ui.dp(34)))
        custom.addView(light, LinearLayout.LayoutParams(matchWidth, ui.dp(34)))
        fun draw() {
            row.removeAllViews()
            val ids = ArrayList<Int>()
            for (t in Themes.presets) ids.add(t.id)
            ids.add(Themes.CUSTOM)
            val current = if (ids.contains(store.themeId)) store.themeId else 0
            for (id in ids) {
                val g = GradientDrawable()
                g.shape = GradientDrawable.OVAL
                if (id == Themes.CUSTOM) {
                    g.setGradientType(GradientDrawable.SWEEP_GRADIENT)
                    g.setColors(IntArray(7) { i -> Themes.hsl(i * 60 % 360, 0.85f, 0.55f) })
                } else {
                    g.setColor(Themes.byId(id, 0, 0).bg)
                }
                val on = id == current
                g.setStroke(ui.dp(if (on) 3 else 1), if (on) Ui.RED else Ui.MUTED)
                val v = View(this)
                v.background = g
                v.contentDescription = if (id == Themes.CUSTOM) "Custom colour" else Themes.byId(id, 0, 0).name
                v.setOnClickListener {
                    store.themeId = id
                    draw()
                }
                row.addView(v, LinearLayout.LayoutParams(ui.dp(36), ui.dp(36)).also { it.rightMargin = ui.dp(10) })
            }
            custom.visibility = if (current == Themes.CUSTOM) View.VISIBLE else View.GONE
        }
        draw()
        box.addView(row)
        box.addView(custom)
        return box
    }

    private fun sectionHead(res: Int, title: String, body: String): LinearLayout {
        val row = ui.infoRow(res, Ui.RED, title, body)
        row.setPadding(0, 0, 0, ui.dp(2))
        return row
    }

    private fun looksCards(col: LinearLayout) {
        val panelCard = ui.card(18)
        panelCard.addView(sectionHead(R.drawable.ic_layers, "Panel", "The window with the chat."))
        panelCard.addView(sliderRow("Opacity", "How see-through the panel background is. Text stays clear.", 20, 100, store.panelOpacity, "%") { store.panelOpacity = it })
        panelCard.addView(sliderRow("Chat text size", "", 80, 140, store.textScale, "%") { store.textScale = it })
        panelCard.addView(ui.text("Theme", 15f, Ui.INK, true).also { it.setPadding(0, ui.dp(12), 0, 0) })
        panelCard.addView(themeChooser())
        col.addView(panelCard)

        val tabCard = ui.card(18)
        tabCard.addView(sectionHead(R.drawable.ic_tab, "Tab", "The small box on the screen edge."))
        tabCard.addView(sliderRow("Opacity", "It never gets fainter than 40%, so you can always find it.", 40, 100, store.tabOpacity, "%") { store.tabOpacity = it })
        tabCard.addView(ui.text("Slide away", 15f, Ui.INK, true).also { it.setPadding(0, ui.dp(12), 0, 0) })
        tabCard.addView(ui.text("Tuck the tab mostly off screen when you are not touching it. It slides back out for new chat.", 13f, Ui.MUTED))
        tabCard.addView(segmented(listOf(Pair("Never", 0), Pair("3 s", 3), Pair("5 s", 5), Pair("10 s", 10), Pair("20 s", 20)), store.tabHide) { store.tabHide = it })
        col.addView(tabCard)

        val popCard = ui.card(18)
        popCard.addView(sectionHead(R.drawable.ic_chat, "Chat pop-outs", "The new messages that slide out beside the tab. Separate from the panel."))
        popCard.addView(sliderRow("Size", "", 70, 170, store.popScale, "%") { store.popScale = it })
        popCard.addView(sliderRow("Opacity", "", 30, 100, store.popOpacity, "%") { store.popOpacity = it })
        col.addView(popCard)

        val sendCard = ui.card(18)
        sendCard.addView(sectionHead(R.drawable.ic_send, "Send messages", "Type to your chat from the panel."))
        sendCard.addView(toggleRow("Show the message box", "Needs permission in SavahBot: Manage, SavahLive, then this phone.", store.sendEnabled) { store.sendEnabled = it })
        col.addView(sendCard)

        val resetCard = ui.card(18)
        resetCard.addView(ui.text("Panel in the wrong place?", 16f, Ui.INK, true))
        resetCard.addView(ui.text("Puts the panel and the tab back to where they start.", 13f, Ui.MUTED))
        resetCard.addView(ui.button("Reset size and position", null, Ui.SECONDARY) {
            store.panelWdp = 270
            store.panelHdp = 300
            store.expanded = false
            store.panelFx = 500
            store.panelFy = 300
            store.tabEdge = Edge.RIGHT.ordinal
            store.tabAlong = 400
            message = "Reset. The panel is back in the middle."
            render()
        })
        col.addView(resetCard)
    }

    // ---- extras: each one has its own switch here ---------------------------------------------------------------------------------------------
    private fun pill(label: String, tint: Int = Ui.INK, onClick: () -> Unit): TextView {
        val t = ui.text(label, 13f, tint, true)
        t.setPadding(ui.dp(12), ui.dp(8), ui.dp(12), ui.dp(8))
        t.background = ui.round(Ui.RAISED, 12)
        t.isClickable = true
        t.setOnClickListener { onClick() }
        return t
    }

    private fun extrasCards(col: LinearLayout) {
        val chatCard = ui.card(18)
        chatCard.addView(sectionHead(R.drawable.ic_chat, "Chat tools", "What a tap or a long press on a chat line does."))
        chatCard.addView(toggleRow("Pin a message", "Tap a line to pin it at the top of the panel. Tap the pin to let it go.", store.pinEnabled) { store.pinEnabled = it })
        chatCard.addView(toggleRow("Hide or time out people", "Hold a line to hide it or time its author out for 5 minutes. Needs permission in SavahBot: Manage, SavahLive, then this phone.", store.modEnabled) { store.modEnabled = it })
        col.addView(chatCard)

        val mileCard = ui.card(18)
        mileCard.addView(sectionHead(R.drawable.ic_heart, "Milestones", "The panel and tab celebrate when viewers or likes pass a round number."))
        mileCard.addView(segmented(listOf(Pair("Off", 0), Pair("50", 50), Pair("100", 100), Pair("250", 250), Pair("500", 500), Pair("1000", 1000)), store.milestoneStep) { store.milestoneStep = it })
        col.addView(mileCard)

        val autoCard = ui.card(18)
        autoCard.addView(sectionHead(R.drawable.ic_power, "Automatic", "Fewer taps on stream day."))
        autoCard.addView(toggleRow("Start when the app opens", "Opening SavahLive starts the overlay for you.", store.autoOpen) { store.autoOpen = it })
        autoCard.addView(ui.text("Stop after the stream ends", 15f, Ui.INK, true).also { it.setPadding(0, ui.dp(12), 0, 0) })
        autoCard.addView(ui.text("The overlay stops this long after SavahBot says your stream is over. It carries on if you go live again.", 13f, Ui.MUTED))
        autoCard.addView(segmented(listOf(Pair("Never", 0), Pair("5 min", 5), Pair("15 min", 15), Pair("30 min", 30), Pair("1 hour", 60)), store.autoStopMin) { store.autoStopMin = it })
        autoCard.addView(toggleRow("Keep a stream summary", "Peak viewers, likes, messages and top chatters, shown here after you stop.", store.summaryOn) { store.summaryOn = it })
        col.addView(autoCard)

        val linkCard = ui.card(18)
        linkCard.addView(sectionHead(R.drawable.ic_phone, "Connection", "When something is wrong, say so plainly."))
        linkCard.addView(toggleRow("Show the connection status", "Offline or retrying appears on the panel and replaces the numbers on the tab.", store.statusBanner) { store.statusBanner = it })
        linkCard.addView(toggleRow("Tell me about new versions", "Shows a card here when SavahBot has a newer SavahLive.", store.updateCheck) { store.updateCheck = it })
        col.addView(linkCard)

        val looks = ui.card(18)
        looks.addView(sectionHead(R.drawable.ic_palette, "Saved looks", "Keep a layout and theme, for example one for PUBG in landscape. The notification can switch to the next one."))
        val saved = Presets.list(store)
        for ((i, p) in saved.withIndex()) {
            val row = LinearLayout(this)
            row.orientation = LinearLayout.HORIZONTAL
            row.gravity = Gravity.CENTER_VERTICAL
            row.setPadding(0, ui.dp(10), 0, 0)
            val label = ui.text(if (i == store.presetIndex) p.name + "  (in use)" else p.name, 15f, Ui.INK, i == store.presetIndex)
            row.addView(label, LinearLayout.LayoutParams(0, wrap, 1f))
            row.addView(pill("Use") {
                Presets.apply(store, i)
                message = "Using \"" + p.name + "\"."
                render()
            })
            row.addView(pill("Delete", Ui.MUTED) {
                Presets.delete(store, i)
                render()
            }, LinearLayout.LayoutParams(wrap, wrap).also { it.leftMargin = ui.dp(6) })
            looks.addView(row)
        }
        looks.addView(ui.space(8))
        looks.addView(ui.field("Name this look", presetName) { presetName = it })
        looks.addView(ui.button("Save the current look", R.drawable.ic_check, Ui.SECONDARY) {
            message = if (Presets.save(store, presetName)) "Saved." else "You can keep up to ${Presets.MAX} looks. Delete one first."
            presetName = ""
            render()
        })
        col.addView(looks)
    }

    /** SavahBot keeps the app and itself on the same version number, so a higher number there means a newer app exists. */
    private fun updateCard(col: LinearLayout) {
        if (!store.updateCheck) return
        val info = try {
            org.json.JSONObject(store.updateJson.ifEmpty { "{}" })
        } catch (e: Exception) {
            return
        }
        val version = info.optString("version", "")
        if (version.isEmpty() || !Versions.isNewer(version, BuildConfig.VERSION_NAME)) return
        val url = info.optString("url", "")
        val card = ui.card(18)
        card.addView(sectionHead(R.drawable.ic_check, "SavahLive $version is available", "You have ${BuildConfig.VERSION_NAME}."))
        if (url.startsWith("https://") || url.startsWith("http://")) {
            card.addView(ui.button("Download", null, Ui.PRIMARY) {
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                } catch (e: Exception) {
                    message = "Could not open the link."
                    render()
                }
            })
        } else {
            card.addView(ui.text("Ask whoever runs SavahBot for the new file.", 13f, Ui.MUTED))
        }
        col.addView(card)
    }

    private fun summaryCard(col: LinearLayout) {
        if (!store.summaryOn || store.summaryJson.isEmpty()) return
        val o = try {
            org.json.JSONObject(store.summaryJson)
        } catch (e: Exception) {
            return
        }
        val secs = o.optLong("seconds", 0)
        val duration = if (secs >= 3600) "${secs / 3600} h ${(secs % 3600) / 60} min" else "${maxOf(1L, secs / 60)} min"
        val card = ui.card(18)
        card.addView(sectionHead(R.drawable.ic_live, "Last stream", DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(o.optLong("ended", 0))) + "  ·  " + duration))
        val row = LinearLayout(this)
        row.orientation = LinearLayout.HORIZONTAL
        row.setPadding(0, ui.dp(10), 0, 0)
        fun stat(label: String, value: String) {
            val box = LinearLayout(this)
            box.orientation = LinearLayout.VERTICAL
            box.addView(ui.text(value, 22f, Ui.INK, true))
            box.addView(ui.text(label, 12f, Ui.MUTED))
            row.addView(box, LinearLayout.LayoutParams(0, wrap, 1f))
        }
        stat("Peak viewers", Fmt.count(o.optLong("peak", 0)))
        stat("Likes", Fmt.count(o.optLong("likes", 0)))
        stat("Messages", Fmt.count(o.optLong("messages", 0)))
        card.addView(row)
        val top = o.optJSONArray("top")
        if (top != null && top.length() > 0) {
            val names = ArrayList<String>()
            for (i in 0 until top.length()) {
                val t = top.optJSONArray(i) ?: continue
                names.add(t.optString(0) + " (" + t.optInt(1) + ")")
            }
            card.addView(ui.space(8))
            card.addView(ui.text("Top chatters: " + names.joinToString(", "), 13f, Ui.MUTED))
        }
        card.addView(ui.button("Clear", null, Ui.QUIET) {
            store.summaryJson = ""
            render()
        })
        col.addView(card)
    }

    // ---- actions ----------------------------------------------------------------------------------------------------------------------------
    private fun pasteFromClipboard() {
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val clip = cm.primaryClip
        val text = if (clip != null && clip.itemCount > 0) (clip.getItemAt(0).coerceToText(this)?.toString() ?: "") else ""
        if (text.isBlank()) {
            message = "Nothing to paste yet. Copy the pairing link or code first."
            messageIsError = true
            render()
            return
        }
        typedCode = text.trim()
        onPairClicked()
    }

    private fun onPairClicked() {
        val input = Pairing.parse(typedCode, typedServer)
        if (input == null) {
            message = "That does not look like a pairing link or code. A code has 8 letters and numbers, like K7Q4-9M2X."
            messageIsError = true
            render()
            return
        }
        pair(input)
    }

    private fun pair(input: PairInput) {
        if (pairing) return
        val server = Pairing.normalizeServer(input.server ?: typedServer, BuildConfig.DEBUG)
        if (server == null) {
            message = "Add the SavahBot address (it starts with https://). It is in the pairing link, or on the pairing page."
            messageIsError = true
            showServer = true
            render()
            return
        }
        pairing = true
        message = "Pairing\u2026"
        messageIsError = false
        render()
        Thread({
            var ok: Net.PairResult? = null
            var err = ""
            try {
                ok = Net.pair(server, input.code)
            } catch (e: Net.PairError) {
                err = e.message ?: "Pairing failed."
            } catch (e: Exception) {
                err = "Pairing failed. Please try again."
            }
            val done = ok
            runOnUiThread {
                pairing = false
                if (done != null) {
                    store.savePairing(server, done.key, done.name, done.expires)
                    message = ""
                    typedCode = ""
                } else {
                    message = err
                    messageIsError = true
                }
                render()
            }
        }, "savahlive-pair").start()
    }

    private fun startOverlay() {
        if (!Settings.canDrawOverlays(this)) {
            render()
            return
        }
        message = ""
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), ASK_NOTIFICATIONS)    // asked once; the overlay starts either way
        }
        OverlayService.start(this)
        main.postDelayed({ render() }, 700)
    }

    private fun confirmUnpair() {
        AlertDialog.Builder(this)
            .setTitle("Unpair this phone?")
            .setMessage("The overlay stops and this phone forgets SavahBot. You can pair again with a new code any time.")
            .setPositiveButton("Unpair") { _, _ ->
                OverlayService.stop(this)
                store.clearPairing("")
                message = ""
                render()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }
}
