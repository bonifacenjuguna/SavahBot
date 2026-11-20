package com.savahbot.live

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.content.res.Configuration
import android.graphics.drawable.Icon
import android.net.ConnectivityManager
import android.net.Network
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.Settings
import android.widget.RemoteViews

/**
 * Keeps the connection and the floating window alive while the overlay is open, and nothing else.
 * Close the overlay (the X, the notification's Stop, or Stop in the app) and the service ends, the connection closes and nothing runs in the background.
 * When the screen goes off the stream is closed too, and it reopens when the screen comes back on.
 */
class OverlayService : Service(), Feed.Listener {
    companion object {
        const val ACTION_START = "com.savahbot.live.START"
        const val ACTION_STOP = "com.savahbot.live.STOP"
        const val ACTION_LOCK = "com.savahbot.live.LOCK"
        const val ACTION_TOGGLE = "com.savahbot.live.TOGGLE"
        const val ACTION_RESET = "com.savahbot.live.RESET"
        const val ACTION_PRESET = "com.savahbot.live.PRESET"
        private const val CHANNEL = "savahlive_overlay"
        private const val NOTE_ID = 1

        @Volatile var running = false
        @Volatile var status = ""       // read by the main screen

        fun start(context: Context) {
            context.startForegroundService(Intent(context, OverlayService::class.java).setAction(ACTION_START))
        }

        fun stop(context: Context) {
            context.startService(Intent(context, OverlayService::class.java).setAction(ACTION_STOP))
        }
    }

    private lateinit var store: Store
    private val main = Handler(Looper.getMainLooper())
    private var overlay: Overlay? = null
    private var feed: Feed? = null
    private var locked = false
    private var noteText = ""
    private var receiver: BroadcastReceiver? = null
    private var netCallback: ConnectivityManager.NetworkCallback? = null
    private var finished = false
    private val tally = StreamTally()
    private var lastViewers: Long? = null
    private var lastLikes: Long? = null
    private val autoStop = Runnable { shutdown() }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        store = Store(this)
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "SavahLive overlay", NotificationManager.IMPORTANCE_LOW))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                shutdown()
                return START_NOT_STICKY
            }
            ACTION_RESET -> {
                // same values as the app's "Reset size and position"; the open overlay follows the change live
                store.panelWdp = 270
                store.panelHdp = 300
                store.expanded = false
                store.panelFx = 500
                store.panelFy = 300
                store.tabEdge = Edge.RIGHT.ordinal
                store.tabAlong = 400
                return START_NOT_STICKY
            }
            ACTION_PRESET -> {
                // the next saved look and layout; the open overlay follows the change live, and the notification names it
                val name = Presets.next(store)
                if (name != null) note(noteText)
                return START_NOT_STICKY
            }
            ACTION_TOGGLE -> {
                overlay?.togglePanel()
                return START_NOT_STICKY
            }
            ACTION_LOCK -> {
                if (overlay != null) {
                    locked = !locked
                    overlay?.setLocked(locked)
                    note(noteText)
                }
                return START_NOT_STICKY
            }
        }
        // Android requires this within a few seconds of startForegroundService, whatever happens next.
        noteText = "Starting\u2026"
        val n = notification(noteText)
        if (Build.VERSION.SDK_INT >= 34) startForeground(NOTE_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE) else startForeground(NOTE_ID, n)
        if (overlay == null) begin()
        return START_NOT_STICKY
    }

    private fun begin() {
        if (!Settings.canDrawOverlays(this) || !store.isPaired) {
            shutdown()
            return
        }
        val o = Overlay(this, store, { shutdown() }, { on ->
            locked = on
            note(noteText)
        })
        if (!o.show()) {
            shutdown()
            return
        }
        overlay = o
        running = true
        tally.startedAt = System.currentTimeMillis()
        status = "Starting\u2026"
        val f = Feed(store, this)
        feed = f
        f.start()
        watchScreen(f)
        watchNetwork(f)
    }

    private fun watchScreen(f: Feed) {
        val r = object : BroadcastReceiver() {
            override fun onReceive(c: Context?, i: Intent?) {
                if (i?.action == Intent.ACTION_SCREEN_OFF) f.pause() else if (i?.action == Intent.ACTION_SCREEN_ON) f.resume()
            }
        }
        receiver = r
        val filter = IntentFilter()
        filter.addAction(Intent.ACTION_SCREEN_OFF)
        filter.addAction(Intent.ACTION_SCREEN_ON)
        registerReceiver(r, filter)
    }

    private fun watchNetwork(f: Feed) {
        try {
            val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val cb = object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) {
                    f.wake()
                }
            }
            netCallback = cb
            cm.registerDefaultNetworkCallback(cb)
        } catch (e: Exception) {
            netCallback = null      // reconnecting still works, just on its own timer
        }
    }

    private fun shutdown() {
        if (finished) return
        finished = true
        saveSummary()
        main.removeCallbacksAndMessages(null)
        feed?.stop()
        feed = null
        try {
            receiver?.let { unregisterReceiver(it) }
        } catch (e: Exception) {
            // not registered
        }
        receiver = null
        try {
            netCallback?.let { (getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager).unregisterNetworkCallback(it) }
        } catch (e: Exception) {
            // not registered
        }
        netCallback = null
        overlay?.hide()
        overlay = null
        running = false
        status = ""
        stopForeground(Service.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    /** One short record of the stream that just ended, for the home screen. Never throws: a summary is not worth a crash. */
    private fun saveSummary() {
        try {
            if (!store.summaryOn || !tally.hasData) return
            val top = org.json.JSONArray()
            for ((name, n) in tally.top()) top.put(org.json.JSONArray().put(name).put(n))
            store.summaryJson = org.json.JSONObject()
                .put("ended", System.currentTimeMillis())
                .put("seconds", (System.currentTimeMillis() - tally.startedAt) / 1000)
                .put("peak", tally.peakViewers)
                .put("likes", tally.lastLikes)
                .put("messages", tally.messages)
                .put("top", top)
                .toString()
        } catch (e: Exception) {
            // keep going: stopping must always work
        }
    }

    override fun onDestroy() {
        shutdown()
        super.onDestroy()
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        overlay?.onScreenChanged()
    }

    // ---------------------------------------------------------------------------------------------- notification
    private fun notification(text: String): Notification {
        val flags = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), flags)
        val stopI = PendingIntent.getService(this, 1, Intent(this, OverlayService::class.java).setAction(ACTION_STOP), flags)
        val lockI = PendingIntent.getService(this, 2, Intent(this, OverlayService::class.java).setAction(ACTION_LOCK), flags)
        val toggleI = PendingIntent.getService(this, 3, Intent(this, OverlayService::class.java).setAction(ACTION_TOGGLE), flags)
        val resetI = PendingIntent.getService(this, 4, Intent(this, OverlayService::class.java).setAction(ACTION_RESET), flags)
        val shown = if (locked) "$text \u00B7 touch locked" else text

        // two layouts: a compact row (status light, name, five round icon buttons) and an expanded card (status line, then five labelled buttons)
        val night = (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
        val ink = if (night) 0xFFE8EAED.toInt() else 0xFF3C4043.toInt()
        val red = 0xFFE5242B.toInt()
        val chip = if (night) R.drawable.nc_chip_dark else R.drawable.nc_chip_light
        val light = when {
            text.startsWith("Connected") -> 0xFF2ECC71.toInt()
            text.startsWith("Demo") -> 0xFF8E9AAF.toInt()
            text.startsWith("Starting") || text.startsWith("Connecting") || text.startsWith("Reconnect") -> 0xFFF5B301.toInt()
            else -> 0xFF8E9AAF.toInt()
        }
        val lockIcon = if (locked) R.drawable.ic_unlock else R.drawable.ic_lock
        val lockWord = if (locked) "Unlock" else "Lock"

        val small = RemoteViews(packageName, R.layout.notif_compact)
        small.setImageViewResource(R.id.nc_dot, R.drawable.ic_dot)
        small.setInt(R.id.nc_dot, "setColorFilter", light)
        small.setTextViewText(R.id.nc_text, shown)
        small.setTextColor(R.id.nc_text, ink)
        fun round(id: Int, icon: Int, label: String, pi: PendingIntent, red_: Boolean = false) {
            small.setImageViewResource(id, icon)
            small.setInt(id, "setColorFilter", if (red_) red else ink)
            small.setInt(id, "setBackgroundResource", if (red_) R.drawable.nc_chip_red else chip)
            small.setContentDescription(id, label)
            small.setOnClickPendingIntent(id, pi)
        }
        round(R.id.nc_toggle, R.drawable.ic_dock, "Hide or show the panel", toggleI)
        round(R.id.nc_lock, lockIcon, "$lockWord touch", lockI)
        round(R.id.nc_reset, R.drawable.ic_move, "Reset position", resetI)
        round(R.id.nc_open, R.drawable.ic_phone, "Open SavahLive", open)
        round(R.id.nc_stop, R.drawable.ic_power, "Stop", stopI, true)

        val big = RemoteViews(packageName, R.layout.notif_big)
        big.setImageViewResource(R.id.nb_dot, R.drawable.ic_dot)
        big.setInt(R.id.nb_dot, "setColorFilter", light)
        big.setTextViewText(R.id.nb_text, shown)
        big.setTextColor(R.id.nb_text, ink)
        fun card(id: Int, iconId: Int, labelId: Int, icon: Int, word: String, desc: String, pi: PendingIntent, red_: Boolean = false) {
            val tint = if (red_) red else ink
            big.setImageViewResource(iconId, icon)
            big.setInt(iconId, "setColorFilter", tint)
            big.setTextViewText(labelId, word)
            big.setTextColor(labelId, tint)
            big.setInt(id, "setBackgroundResource", if (red_) R.drawable.nc_chip_red else chip)
            big.setContentDescription(id, desc)
            big.setOnClickPendingIntent(id, pi)
        }
        card(R.id.nb_toggle, R.id.nbi_toggle, R.id.nbt_toggle, R.drawable.ic_dock, "Hide", "Hide or show the panel", toggleI)
        card(R.id.nb_lock, R.id.nbi_lock, R.id.nbt_lock, lockIcon, lockWord, "$lockWord touch", lockI)
        card(R.id.nb_reset, R.id.nbi_reset, R.id.nbt_reset, R.drawable.ic_move, "Reset", "Reset position", resetI)
        card(R.id.nb_open, R.id.nbi_open, R.id.nbt_open, R.drawable.ic_phone, "Open", "Open SavahLive", open)
        val presets = Presets.list(store)
        if (presets.isNotEmpty()) {
            val current = presets.getOrNull(store.presetIndex)
            val presetI = PendingIntent.getService(this, 5, Intent(this, OverlayService::class.java).setAction(ACTION_PRESET), flags)
            big.setViewVisibility(R.id.nb_preset, android.view.View.VISIBLE)
            card(R.id.nb_preset, R.id.nbi_preset, R.id.nbt_preset, R.drawable.ic_palette, (current?.name ?: "Look").take(7), "Next saved look: ${current?.name ?: "none yet"}", presetI)
        }
        card(R.id.nb_stop, R.id.nbi_stop, R.id.nbt_stop, R.drawable.ic_power, "Stop", "Stop", stopI, true)

        val b = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("SavahLive")
            .setContentText(shown)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setColor(0xFFE5242B.toInt())
            .setStyle(Notification.DecoratedCustomViewStyle())
            .setCustomContentView(small)
            .setCustomBigContentView(big)
        if (Build.VERSION.SDK_INT >= 31) b.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE)
        return b.build()
    }

    /** Only called when the connection state changes (never per chat line or per stat), so it costs almost nothing. */
    private fun note(text: String) {
        noteText = text
        status = text
        if (finished) return
        (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).notify(NOTE_ID, notification(text))
    }

    // ---------------------------------------------------------------------------------------------- Feed.Listener (main thread)
    override fun onLink(link: Link, detail: String) {
        if (finished) return
        overlay?.setLink(link, detail)
        note(
            when (link) {
                Link.ONLINE -> "Connected to SavahBot"
                Link.CONNECTING -> "Connecting\u2026"
                Link.RECONNECTING -> "Reconnecting\u2026"
                Link.WAITING -> detail.ifEmpty { "Waiting for SavahBot" }
                Link.PAUSED -> "Paused while the screen is off"
                Link.UNPAIRED -> "Unpaired"
            }
        )
    }

    override fun onState(state: State) {
        if (finished) return
        overlay?.setState(state)
        if (state.live) {
            tally.sawLive = true
            main.removeCallbacks(autoStop)
        } else if (tally.sawLive && store.autoStopMin > 0) {
            main.removeCallbacks(autoStop)
            main.postDelayed(autoStop, store.autoStopMin * 60_000L)       // stops the overlay a while after the stream ends, unless it goes live again
        }
    }

    override fun onStats(stats: Stats) {
        if (finished) return
        overlay?.setStats(stats)
        if (!stats.enabled) return
        tally.viewers(stats.viewers)
        tally.likes(if (stats.likesHidden) null else stats.likes)
        val step = store.milestoneStep
        val l = if (stats.likesHidden) null else Milestones.crossed(lastLikes, stats.likes, step)
        val v = Milestones.crossed(lastViewers, stats.viewers, step)
        if (stats.viewers != null) lastViewers = stats.viewers
        if (stats.likes != null && !stats.likesHidden) lastLikes = stats.likes
        if (l != null) overlay?.celebrate("${Fmt.count(l)} likes")
        else if (v != null) overlay?.celebrate("${Fmt.count(v)} watching")
    }

    override fun onSettings(prefs: Prefs) {
        if (!finished) overlay?.setPrefs(prefs)
    }

    override fun onChat(lines: List<Line>, skipped: Int) {
        if (finished) return
        for (l in lines) tally.message(l)
        overlay?.addChat(lines, skipped)
    }

    /** SavahBot says which version is current (it is kept equal to this app's version). The home screen compares it with the installed one. */
    override fun onUpdate(info: UpdateInfo) {
        if (finished || !store.updateCheck) return
        store.updateJson = org.json.JSONObject().put("version", info.version).put("url", info.url).toString()
    }

    override fun onPurge(uids: List<String>, ids: List<Long>) {
        if (!finished) overlay?.purge(uids, ids)
    }

    /** SavahBot cancelled this phone's pairing. Forget it, say so on the overlay for a few seconds, then stop. */
    override fun onUnpaired(code: String) {
        if (finished) return
        val message = when (code) {
            "expired" -> "The pairing for this phone has ended. Open SavahLive to pair again."
            "idle" -> "This phone was unpaired because it was not used for a while. Open SavahLive to pair again."
            "unpaired" -> "SavahBot does not know this phone. Open SavahLive to pair again."
            else -> "This phone was unpaired from SavahBot. Open SavahLive to pair again."
        }
        store.clearPairing(message)
        feed?.stop()
        overlay?.setLink(Link.UNPAIRED, "")
        overlay?.showNotice(message)
        note("Unpaired")
        main.postDelayed({ shutdown() }, 8_000)
    }
}
