package com.savahbot.live

import android.os.Handler
import android.os.Looper
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Semaphore
import java.util.concurrent.TimeUnit

/**
 * The one connection SavahLive keeps: SavahBot's /api/live/feed stream, read on a single background thread.
 * It does not talk to YouTube and does no moderation: it only receives what SavahBot already worked out.
 *
 * Reconnecting: if the connection drops after working, it retries within a second or two; if it keeps failing the wait grows to a minute.
 * A change of network wakes it at once. A "revoked/expired" answer from SavahBot is the only thing that makes the phone forget its pairing;
 * a bad signal or an unreachable server never does. Everything the listener receives arrives on the main thread.
 */
class Feed(private val store: Store, private val ui: Listener) {
    interface Listener {
        fun onLink(link: Link, detail: String)
        fun onState(state: State)
        fun onStats(stats: Stats)
        fun onSettings(prefs: Prefs)
        fun onChat(lines: List<Line>, skipped: Int)
        fun onPurge(uids: List<String>, ids: List<Long>)
        fun onUnpaired(code: String)
        fun onUpdate(info: UpdateInfo)
    }

    private enum class Outcome { DROPPED, FAILED, WAIT, UNPAIRED, STOPPED }

    private val main = Handler(Looper.getMainLooper())
    private val wakeups = Semaphore(0)

    @Volatile private var stopped = false
    @Volatile private var paused = false
    @Volatile private var conn: HttpURLConnection? = null
    private var thread: Thread? = null
    private var lastId = 0L            // newest chat id seen; sent as ?since= so a reconnect never repeats or misses a line
    private var everOnline = false

    fun start() {
        if (thread != null) return
        val t = Thread({ loop() }, "savahlive-feed")
        t.isDaemon = true
        thread = t
        t.start()
    }

    fun stop() {
        stopped = true
        wake()
        disconnect()
    }

    /** Screen off: close the connection and stay quiet. */
    fun pause() {
        if (paused || stopped) return
        paused = true
        post { ui.onLink(Link.PAUSED, "") }
        disconnect()
    }

    fun resume() {
        if (!paused) return
        paused = false
        wake()
    }

    /** Skip any waiting and try now (a network came back). */
    fun wake() {
        if (wakeups.availablePermits() < 1) wakeups.release()
    }

    private fun post(r: () -> Unit) {
        main.post { if (!stopped) r() }
    }

    private fun waitFor(ms: Long) {
        try {
            wakeups.tryAcquire(ms, TimeUnit.MILLISECONDS)
        } catch (e: InterruptedException) {
            // fall through: the loop checks its flags
        }
        wakeups.drainPermits()
    }

    /** Closing a socket can touch the network, which Android forbids on the main thread, so it is done on its own thread. */
    private fun disconnect() {
        val c = conn ?: return
        Thread({
            try {
                c.disconnect()
            } catch (e: Exception) {
                // already closed
            }
        }, "savahlive-close").start()
    }

    private fun loop() {
        var attempt = 0
        while (!stopped) {
            if (paused) {
                waitFor(60_000)
                continue
            }
            val outcome = connectOnce()
            if (stopped) return
            when (outcome) {
                Outcome.UNPAIRED -> return
                Outcome.STOPPED -> attempt = 0
                Outcome.WAIT -> {
                    attempt = 0
                    waitFor(30_000)
                }
                Outcome.DROPPED -> {
                    attempt = 0
                    post { ui.onLink(Link.RECONNECTING, "") }
                    waitFor(Backoff.delayMs(0, Math.random()))
                }
                Outcome.FAILED -> {
                    post { ui.onLink(Link.RECONNECTING, "") }
                    waitFor(Backoff.delayMs(attempt, Math.random()))
                    attempt++
                }
            }
        }
    }

    private fun connectOnce(): Outcome {
        val key = store.key()
        val server = store.server
        if (key == null || server.isEmpty()) {
            post { ui.onUnpaired("unpaired") }
            return Outcome.UNPAIRED
        }
        post { ui.onLink(if (everOnline) Link.RECONNECTING else Link.CONNECTING, "") }
        var c: HttpURLConnection? = null
        var onlineAt = 0L
        var ended: Outcome? = null
        try {
            c = URL(server + "/api/live/feed?since=" + lastId + "&app=" + BuildConfig.VERSION_NAME).openConnection() as HttpURLConnection
            conn = c
            if (stopped || paused) return Outcome.STOPPED
            c.connectTimeout = 15_000
            c.readTimeout = 45_000                      // SavahBot sends a heartbeat every 15 seconds, so silence for 45 means the line is dead
            c.useCaches = false
            c.setRequestProperty("Accept", "text/event-stream")
            c.setRequestProperty("Accept-Encoding", "identity")
            c.setRequestProperty("Cache-Control", "no-cache")
            c.setRequestProperty("Authorization", "Bearer $key")
            c.setRequestProperty("User-Agent", "SavahLive/" + BuildConfig.VERSION_NAME + " (Android)")
            val status = c.responseCode
            if (status != 200) return refused(status, c)
            val parser = SseParser { event, data ->
                val result = handle(event, data, key)
                if (event == "hello") {
                    onlineAt = System.currentTimeMillis()
                    everOnline = true
                }
                if (result != null) ended = result
            }
            c.inputStream.bufferedReader(Charsets.UTF_8).use { reader ->
                while (true) {
                    val line = reader.readLine() ?: break
                    parser.feed(line)
                    if (ended != null || stopped || paused) break
                }
            }
        } catch (e: Exception) {
            if (stopped || paused) return Outcome.STOPPED
        } finally {
            try {
                c?.disconnect()
            } catch (e: Exception) {
                // already closed
            }
            if (conn === c) conn = null
        }
        val result = ended
        return when {
            result != null -> result
            stopped || paused -> Outcome.STOPPED
            onlineAt > 0 && System.currentTimeMillis() - onlineAt >= 5_000 -> Outcome.DROPPED
            else -> Outcome.FAILED
        }
    }

    /** SavahBot said no before the stream began. Only a clear "this phone is not paired" makes the phone forget its pairing. */
    private fun refused(status: Int, c: HttpURLConnection): Outcome {
        val body = try {
            c.errorStream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
        } catch (e: Exception) {
            ""
        }
        val code = Net.code(body)
        if (status == 401 && code in FORGET) {
            post { ui.onUnpaired(code) }
            return Outcome.UNPAIRED
        }
        if (status == 403 || status == 429) {
            val msg = Net.message(body, "SavahBot asked this phone to wait.")
            post { ui.onLink(Link.WAITING, msg) }
            return Outcome.WAIT
        }
        return Outcome.FAILED
    }

    /** Returns an outcome when the event ends the connection, otherwise null. */
    private fun handle(event: String, data: String, key: String): Outcome? {
        val j = try {
            JSONObject(data)
        } catch (e: JSONException) {
            return null
        }
        when (event) {
            "hello" -> {
                val state = parseState(j.optJSONObject("state"))
                val stats = parseStats(j.optJSONObject("stats"))
                val prefs = parsePrefs(j.optJSONObject("settings"))
                val lines = parseLines(j.optJSONArray("chat"))
                val update = j.optJSONObject("update")?.let { UpdateInfo(it.optString("version", ""), it.optString("url", "")) }
                post {
                    ui.onLink(Link.ONLINE, "")
                    if (update != null && update.version.isNotEmpty()) ui.onUpdate(update)
                    ui.onState(state)
                    ui.onStats(stats)
                    ui.onSettings(prefs)
                    ui.onChat(lines, 0)
                }
                if (j.optBoolean("rotate", false)) renewKey(key)
            }
            "stats" -> {
                val stats = parseStats(j)
                post { ui.onStats(stats) }
            }
            "state" -> {
                val state = parseState(j)
                post { ui.onState(state) }
            }
            "settings" -> {
                val prefs = parsePrefs(j)
                post { ui.onSettings(prefs) }
            }
            "chat" -> {
                val lines = parseLines(j.optJSONArray("lines"))
                val skipped = j.optInt("skipped", 0)
                post { ui.onChat(lines, skipped) }
            }
            "purge" -> {
                val uids = ArrayList<String>()
                val ids = ArrayList<Long>()
                val u = j.optJSONArray("uids")
                if (u != null) for (i in 0 until u.length()) uids.add(u.optString(i))
                val n = j.optJSONArray("ids")
                if (n != null) for (i in 0 until n.length()) ids.add(n.optLong(i))
                post { ui.onPurge(uids, ids) }
            }
            "unpaired" -> {
                val code = j.optString("code", "revoked")
                return when {
                    code in FORGET -> {
                        post { ui.onUnpaired(code) }
                        Outcome.UNPAIRED
                    }
                    code == "disabled" -> {
                        post { ui.onLink(Link.WAITING, "SavahLive is switched off in SavahBot.") }
                        Outcome.WAIT
                    }
                    code == "lockdown" -> {
                        post { ui.onLink(Link.WAITING, "SavahBot is in lockdown.") }
                        Outcome.WAIT
                    }
                    else -> Outcome.WAIT          // "replaced": a newer connection of this phone took over
                }
            }
        }
        return null
    }

    /** SavahBot asked for a new key (every 30 days by default). Done quietly; if anything fails, the old key keeps working and it asks again next time. */
    private fun renewKey(old: String) {
        try {
            val r = Net.call("POST", store.server + "/api/live/rotate", "{}", old)
            if (r.status == 200) {
                val fresh = JSONObject(r.body).optString("key", "")
                if (fresh.startsWith("sld_")) store.saveKey(fresh)
            }
        } catch (e: Exception) {
            // try again on the next connection
        }
    }

    private fun parseState(o: JSONObject?): State =
        State(o?.optString("mode", "live") ?: "live", o?.optBoolean("live", false) ?: false, o?.optString("title", "") ?: "")

    private fun nullableLong(o: JSONObject, name: String): Long? = if (o.isNull(name)) null else o.optLong(name)

    private fun parseStats(o: JSONObject?): Stats =
        if (o == null) Stats(null, null, false, false)
        else Stats(nullableLong(o, "viewers"), nullableLong(o, "likes"), o.optBoolean("likes_hidden", false), o.optBoolean("enabled", true))

    private fun parsePrefs(o: JSONObject?): Prefs = Prefs(
        (o?.optInt("chat_lines", 40) ?: 40).coerceIn(10, 100),
        (o?.optInt("peek_seconds", 5) ?: 5).coerceIn(2, 15),
        (o?.optInt("font_size", 14) ?: 14).coerceIn(11, 22),
        (o?.optInt("hide_seconds", 3) ?: 3).coerceIn(0, 30),
        o?.optBoolean("can_send", false) ?: false,
        o?.optBoolean("can_mod", false) ?: false
    )

    private fun parseLines(arr: JSONArray?): List<Line> {
        val out = ArrayList<Line>()
        if (arr == null) return out
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val line = Line(o.optLong("id", 0L), o.optString("uid", ""), o.optString("name", ""), o.optString("text", ""), o.optString("level", "everyone"))
            if (line.id > lastId) lastId = line.id
            out.add(line)
        }
        return out
    }

    private companion object {
        val FORGET = setOf("unpaired", "revoked", "expired", "idle")
    }
}
