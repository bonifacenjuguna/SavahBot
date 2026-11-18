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
        val o = Overlay(this, store) { shutdown() }
        if (!o.show()) {
            shutdown()
            return
        }
        overlay = o
        running = true
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
        val icon = Icon.createWithResource(this, R.drawable.ic_stat)
        val b = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("SavahLive")
            .setContentText(if (locked) "$text \u00B7 touch locked" else text)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setColor(0xFFE5242B.toInt())
            .addAction(Notification.Action.Builder(icon, "Stop", stopI).build())
            .addAction(Notification.Action.Builder(icon, if (locked) "Unlock touch" else "Lock touch", lockI).build())
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
        if (!finished) overlay?.setState(state)
    }

    override fun onStats(stats: Stats) {
        if (!finished) overlay?.setStats(stats)
    }

    override fun onSettings(prefs: Prefs) {
        if (!finished) overlay?.setPrefs(prefs)
    }

    override fun onChat(lines: List<Line>, skipped: Int) {
        if (!finished) overlay?.addChat(lines, skipped)
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
