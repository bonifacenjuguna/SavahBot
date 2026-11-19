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
import java.text.DateFormat
import java.util.Date

/**
 * The only screen, in three stages: Pair (once), Allow (the floating-window permission, once), Go (start and stop the overlay).
 * No accounts, no dashboard and no settings of its own: SavahBot (Manage > SavahLive) holds those, and the panel has its own tray for looks.
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

        val how = ui.card(18)
        how.addView(ui.text("How the panel works", 18f, Ui.INK, true))
        how.addView(ui.space(6))
        how.addView(ui.infoRow(R.drawable.ic_move, Ui.RED, "Move it", "Drag the top bar or the numbers row."))
        how.addView(ui.infoRow(R.drawable.ic_expand, Ui.RED, "Resize it", "Drag a bottom corner. The whole panel scales together."))
        how.addView(ui.infoRow(R.drawable.ic_tuck, Ui.RED, "Tuck it away", "Tap the \u2715. It becomes a small tab that hides at the screen edge and pops out when chat arrives."))
        how.addView(ui.infoRow(R.drawable.ic_dots, Ui.RED, "More controls", "Tap the three dots for opacity, theme, lock, text size and stop."))
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
