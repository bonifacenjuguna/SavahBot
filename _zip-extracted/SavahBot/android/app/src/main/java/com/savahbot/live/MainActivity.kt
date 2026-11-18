package com.savahbot.live

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.text.Editable
import android.text.InputType
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.TextWatcher
import android.text.style.ForegroundColorSpan
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.text.DateFormat
import java.util.Date

/**
 * The only screen: pair this phone with SavahBot once, allow the floating window, start or stop the overlay.
 * No accounts, no dashboard, no settings: SavahBot (Manage > SavahLive) holds all of that.
 */
class MainActivity : Activity() {
    private companion object {
        const val BG = 0xFF0F1116.toInt()
        const val CARD = 0xFF181B23.toInt()
        const val FIELD = 0xFF242834.toInt()
        const val INK = 0xFFF1F2F5.toInt()
        const val MUTED = 0xFF9AA0B0.toInt()
        const val RED = 0xFFE5242B.toInt()
        const val GREEN = 0xFF4ADE80.toInt()
        const val AMBER = 0xFFF5B301.toInt()
        const val ASK_NOTIFICATIONS = 7
    }

    private lateinit var store: Store
    private val main = Handler(Looper.getMainLooper())
    private var typedCode = ""
    private var typedServer = ""
    private var message = ""
    private var pairing = false
    private var autoPair: PairInput? = null

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density + 0.5f).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = Store(this)
        window.statusBarColor = BG
        window.navigationBarColor = BG
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
            if (input != null) autoPair = input else message = "That pairing link is not complete. Make a new one in SavahBot."
            i.data = null
        }
    }

    // ---------------------------------------------------------------------------------------------- building blocks
    private fun label(s: CharSequence, sp: Float, color: Int, bold: Boolean = false): TextView {
        val t = TextView(this)
        t.text = s
        t.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, sp)
        t.setTextColor(color)
        if (bold) t.setTypeface(Typeface.DEFAULT_BOLD)
        return t
    }

    private fun gap(h: Int): View {
        val v = View(this)
        v.layoutParams = LinearLayout.LayoutParams(1, dp(h))
        return v
    }

    private fun card(): LinearLayout {
        val c = LinearLayout(this)
        c.orientation = LinearLayout.VERTICAL
        c.setPadding(dp(16), dp(14), dp(16), dp(14))
        val bg = GradientDrawable()
        bg.setColor(CARD)
        bg.setCornerRadius(dp(16).toFloat())
        c.background = bg
        c.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(12) }
        return c
    }

    private fun button(text: String, primary: Boolean, onClick: () -> Unit): Button {
        val b = Button(this)
        b.text = text
        b.setAllCaps(false)
        b.setTextColor(Color.WHITE)
        b.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 16f)
        b.setTypeface(Typeface.DEFAULT_BOLD)
        val shape = GradientDrawable()
        shape.setCornerRadius(dp(12).toFloat())
        if (primary) shape.setColor(RED) else {
            shape.setColor(FIELD)
            shape.setStroke(dp(1), 0x33FFFFFF)
        }
        b.background = RippleDrawable(ColorStateList.valueOf(0x33FFFFFF), shape, null)
        b.minimumHeight = dp(50)
        b.setOnClickListener { onClick() }
        b.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(8) }
        return b
    }

    private fun field(hint: String, value: String, uri: Boolean, onChange: (String) -> Unit): EditText {
        val e = EditText(this)
        e.hint = hint
        e.setText(value)
        e.setTextColor(INK)
        e.setHintTextColor(MUTED)
        e.setSingleLine(true)
        e.inputType = if (uri) InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI else InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        e.setPadding(dp(14), dp(12), dp(14), dp(12))
        val bg = GradientDrawable()
        bg.setColor(FIELD)
        bg.setCornerRadius(dp(12).toFloat())
        e.background = bg
        e.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(8) }
        e.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                onChange(s?.toString() ?: "")
            }
        })
        return e
    }

    // ---------------------------------------------------------------------------------------------- the screen
    private fun render() {
        val col = LinearLayout(this)
        col.orientation = LinearLayout.VERTICAL
        col.setPadding(dp(20), dp(28), dp(20), dp(28))

        val logo = ImageView(this)
        logo.setImageResource(R.drawable.logo_icon)
        logo.layoutParams = LinearLayout.LayoutParams(dp(72), dp(72))
        col.addView(logo)
        val title = SpannableStringBuilder("SavahLive")
        title.setSpan(ForegroundColorSpan(RED), 5, title.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        val head = label(title, 30f, INK, true)
        head.setPadding(0, dp(12), 0, 0)
        col.addView(head)
        col.addView(label("Your SavahBot livestream, floating above any app.", 15f, MUTED))
        col.addView(gap(18))

        if (store.isPaired) pairedView(col) else unpairedView(col)

        col.addView(gap(8))
        col.addView(label("SavahLive " + BuildConfig.VERSION_NAME + "  \u00B7  SavahBot does the work, SavahLive shows the results.", 12f, MUTED))

        val scroll = ScrollView(this)
        scroll.setBackgroundColor(BG)
        scroll.isFillViewport = true
        scroll.addView(col)
        setContentView(scroll)

        val auto = autoPair
        if (auto != null) {
            autoPair = null
            if (!store.isPaired) pair(auto)
        }
    }

    private fun unpairedView(col: LinearLayout) {
        if (store.notice.isNotEmpty()) {
            val n = card()
            n.addView(label(store.notice, 14f, AMBER))
            col.addView(n)
        }
        val c = card()
        c.addView(label("Pair with SavahBot", 18f, INK, true))
        c.addView(gap(6))
        c.addView(label("In SavahBot open Manage \u203A SavahLive \u203A Pair a phone. Scan the QR code with this phone's camera and tap Open SavahLive, or paste the link or type the code below. You only pair once.", 14f, MUTED))
        c.addView(field("Pairing link or code", typedCode, false) { typedCode = it })
        c.addView(field("SavahBot address (only if you typed just the code)", typedServer, true) { typedServer = it })
        val go = button(if (pairing) "Pairing\u2026" else "Pair this phone", true) { onPairClicked() }
        go.isEnabled = !pairing
        c.addView(go)
        if (message.isNotEmpty()) {
            val m = label(message, 14f, if (pairing) MUTED else AMBER)
            m.setPadding(0, dp(10), 0, 0)
            c.addView(m)
        }
        col.addView(c)
    }

    private fun pairedView(col: LinearLayout) {
        val info = card()
        info.addView(label("Paired with SavahBot", 18f, INK, true))
        info.addView(gap(4))
        val host = Uri.parse(store.server).host ?: store.server
        info.addView(label(host, 14f, MUTED))
        info.addView(label("This phone: " + store.deviceName, 14f, MUTED))
        info.addView(label(
            if (store.expires == 0L) "Stays paired until you remove it in SavahBot."
            else "Pairing ends " + DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(store.expires)) + ".", 14f, MUTED))
        col.addView(info)

        val canDraw = Settings.canDrawOverlays(this)
        val steps = card()
        steps.addView(label("Before you start", 16f, INK, true))
        steps.addView(gap(6))
        steps.addView(label(if (canDraw) "\u2713  Display over other apps: allowed" else "Display over other apps: not allowed yet", 14f, if (canDraw) GREEN else AMBER))
        if (!canDraw) steps.addView(button("Allow display over other apps", true) {
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
        })
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            steps.addView(gap(8))
            steps.addView(label("Notifications: needed to show the Stop button while the overlay runs (optional).", 14f, MUTED))
            steps.addView(button("Allow notifications", false) { requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), ASK_NOTIFICATIONS) })
        }
        val power = getSystemService(Context.POWER_SERVICE) as PowerManager
        if (!power.isIgnoringBatteryOptimizations(packageName)) {
            steps.addView(gap(8))
            steps.addView(label("Optional: on some phones (Xiaomi, Oppo, Samsung) the system stops background apps. Choose \u201CUnrestricted\u201D or \u201CDon't optimise\u201D for SavahLive if the overlay disappears during long games.", 13f, MUTED))
            steps.addView(button("Open battery settings", false) { startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) })
        }
        col.addView(steps)

        val run = card()
        if (OverlayService.running) {
            run.addView(label("Overlay is running", 18f, GREEN, true))
            if (OverlayService.status.isNotEmpty()) run.addView(label(OverlayService.status, 14f, MUTED))
            run.addView(gap(4))
            run.addView(button("Stop overlay", false) {
                OverlayService.stop(this)
                main.postDelayed({ render() }, 500)
            })
        } else {
            run.addView(label("Overlay is off", 18f, INK, true))
            run.addView(gap(4))
            run.addView(label("Start it, then open PUBG Mobile or any app. Tap the small pill for the chat window, drag it to an edge to dock it, long-press it to change how see-through it is.", 14f, MUTED))
            run.addView(button("Start overlay", true) { startOverlay() })
        }
        if (message.isNotEmpty()) {
            val m = label(message, 14f, AMBER)
            m.setPadding(0, dp(10), 0, 0)
            run.addView(m)
        }
        col.addView(run)

        val unpair = button("Unpair this phone", false) { confirmUnpair() }
        col.addView(unpair)
    }

    // ---------------------------------------------------------------------------------------------- actions
    private fun onPairClicked() {
        val input = Pairing.parse(typedCode, typedServer)
        if (input == null) {
            message = "That does not look like a pairing code. It has 8 letters and numbers, like K7Q4-9M2X."
            render()
            return
        }
        pair(input)
    }

    private fun pair(input: PairInput) {
        if (pairing) return
        val server = Pairing.normalizeServer(input.server ?: typedServer, BuildConfig.DEBUG)
        if (server == null) {
            message = "Enter the SavahBot address (it starts with https://)."
            render()
            return
        }
        pairing = true
        message = "Pairing\u2026"
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
                }
                render()
            }
        }, "savahlive-pair").start()
    }

    private fun startOverlay() {
        if (!Settings.canDrawOverlays(this)) {
            message = "Allow \u201CDisplay over other apps\u201D first."
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
