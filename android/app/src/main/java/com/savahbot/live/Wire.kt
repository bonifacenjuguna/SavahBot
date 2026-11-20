package com.savahbot.live

import java.net.URI
import java.net.URLDecoder
import java.util.Locale

// Plain Kotlin, no Android classes in this file: it is what the unit tests in src/test exercise on a normal JVM.

/** One chat line as the overlay draws it. A line with level "note" is a small grey remark such as "+37 more messages". */
data class Line(val id: Long, val uid: String, val name: String, val text: String, val level: String)

data class Stats(val viewers: Long?, val likes: Long?, val likesHidden: Boolean, val enabled: Boolean)

data class State(val mode: String, val live: Boolean, val title: String)

/** What SavahBot tells the phone to do: lines kept, how long new chat stays popped out, text size, the dashboard's tab-hide default, and whether this phone may send chat messages. */
data class Prefs(val chatLines: Int, val peekSeconds: Int, val fontSize: Int, val hideSeconds: Int = 3, val canSend: Boolean = false, val canMod: Boolean = false)

/** What SavahBot says is its own version, and where the app can be downloaded (the release script keeps SavahBot's version and the app's equal). */
data class UpdateInfo(val version: String, val url: String)

object Versions {
    /** True when [latest] is a higher version number than [mine]. "1.6.10" beats "1.6.9". Anything unreadable counts as not newer. */
    fun isNewer(latest: String, mine: String): Boolean {
        fun parts(v: String): List<Int>? {
            val out = v.trim().removePrefix("v").split('.').map { it.takeWhile { c -> c.isDigit() }.toIntOrNull() ?: return null }
            return if (out.isEmpty()) null else out
        }
        val a = parts(latest) ?: return false
        val b = parts(mine) ?: return false
        for (i in 0 until maxOf(a.size, b.size)) {
            val x = a.getOrElse(i) { 0 }
            val y = b.getOrElse(i) { 0 }
            if (x != y) return x > y
        }
        return false
    }
}

/** The step a counter has just crossed: 99 to 103 with a step of 100 gives 100; 103 to 105 gives null. A step of 0 is off. */
object Milestones {
    fun crossed(before: Long?, now: Long?, step: Int): Long? {
        if (step <= 0 || before == null || now == null || now <= before) return null
        val reached = (now / step) * step
        return if (reached > 0 && reached > before) reached else null
    }
}

/** What happened on one stream, kept while the overlay runs and summarised when it stops. */
class StreamTally {
    var startedAt = 0L
    var peakViewers = 0L
    var lastLikes = 0L
    var messages = 0
    var sawLive = false
    private val chatters = HashMap<String, Int>()
    private val names = HashMap<String, String>()

    fun message(line: Line) {
        if (line.level == "note" || line.uid.isEmpty() || line.uid == "self") return
        messages++
        chatters[line.uid] = (chatters[line.uid] ?: 0) + 1
        if (line.name.isNotEmpty()) names[line.uid] = line.name
    }

    fun viewers(v: Long?) { if (v != null && v > peakViewers) peakViewers = v }
    fun likes(v: Long?) { if (v != null && v > lastLikes) lastLikes = v }

    /** The three people who wrote the most, as "name:count". */
    fun top(n: Int = 3): List<Pair<String, Int>> = chatters.entries.sortedByDescending { it.value }.take(n).map { Pair(names[it.key] ?: "?", it.value) }

    val hasData: Boolean get() = sawLive || messages > 0 || peakViewers > 0
}

enum class Link { CONNECTING, ONLINE, RECONNECTING, WAITING, PAUSED, UNPAIRED }

object Fmt {
    /** 950 -> "950", 1234 -> "1.2K", 12500 -> "12.5K", 123456 -> "123K", 2400000 -> "2.4M". null -> a dash. */
    fun count(n: Long?): String {
        if (n == null) return "\u2014"
        if (n < 1_000) return n.toString()
        if (n < 100_000) return trim(n / 1_000.0) + "K"
        if (n < 1_000_000) return (n / 1_000).toString() + "K"
        return trim(n / 1_000_000.0) + "M"
    }

    private fun trim(v: Double): String {
        val s = String.format(Locale.US, "%.1f", v)
        return if (s.endsWith(".0")) s.dropLast(2) else s
    }
}

object Backoff {
    /** 1s, 2s, 4s ... capped at 60s, spread by +-25% so many phones never retry in step. `random` is 0.0 to 1.0. */
    fun delayMs(attempt: Int, random: Double): Long {
        val base = minOf(60_000L, 1_000L shl minOf(maxOf(attempt, 0), 6))
        return (base * (0.75 + 0.5 * random)).toLong()
    }
}

/** Reads a Server-Sent Events stream one line at a time and calls [onEvent] for each complete event. Comment lines (": ping") are ignored. */
class SseParser(private val onEvent: (event: String, data: String) -> Unit) {
    private var event = ""
    private val data = StringBuilder()
    private var hasData = false

    fun feed(line: String) {
        if (line.isEmpty()) {
            if (hasData) onEvent(if (event.isEmpty()) "message" else event, data.toString())
            event = ""
            data.setLength(0)
            hasData = false
            return
        }
        if (line.startsWith(":")) return
        val i = line.indexOf(':')
        val field = if (i < 0) line else line.substring(0, i)
        var value = if (i < 0) "" else line.substring(i + 1)
        if (value.startsWith(" ")) value = value.substring(1)
        when (field) {
            "event" -> event = value
            "data" -> {
                if (hasData) data.append('\n')
                data.append(value)
                hasData = true
            }
        }
    }
}

class PairInput(val server: String?, val code: String)

object Pairing {
    private val CODE = Regex("^[A-Z0-9]{8}$")

    fun cleanCode(raw: String): String = raw.filter { it.isLetterOrDigit() }.uppercase(Locale.ROOT)

    private fun query(url: String): Map<String, String> {
        val q = url.substringAfter('?', "").substringBefore('#')
        val out = HashMap<String, String>()
        for (part in q.split('&')) {
            if (part.isEmpty()) continue
            try {
                out[URLDecoder.decode(part.substringBefore('='), "UTF-8")] = URLDecoder.decode(part.substringAfter('=', ""), "UTF-8")
            } catch (e: IllegalArgumentException) {
                // a broken %-escape: skip that one parameter
            }
        }
        return out
    }

    private fun originOf(url: String): String? = try {
        val u = URI(url.trim())
        if (u.scheme == null || u.authority == null) null else u.scheme + "://" + u.authority
    } catch (e: Exception) {
        null
    }

    /**
     * Accepts what SavahBot hands out: the savahlive://pair?s=...&c=... link, the https://server/api/live/pair/open?c=... link
     * (typed or pasted), or just the 8-character code (then the server comes from [typedServer]). Returns null if there is no valid code.
     */
    fun parse(text: String, typedServer: String = ""): PairInput? {
        val t = text.trim()
        if (t.contains("://")) {
            val q = query(t)
            val code = cleanCode(q["c"] ?: "")
            if (!CODE.matches(code)) return null
            val server = if (t.startsWith("savahlive:", ignoreCase = true)) q["s"] else originOf(t)
            return PairInput(server, code)
        }
        val code = cleanCode(t)
        return if (CODE.matches(code)) PairInput(if (typedServer.isBlank()) null else typedServer, code) else null
    }

    /** "bot.example.app" or "https://bot.example.app/" -> "https://bot.example.app". Only https, unless [allowHttp] (debug builds). */
    fun normalizeServer(raw: String?, allowHttp: Boolean): String? {
        var s = (raw ?: "").trim().trimEnd('/')
        if (s.isEmpty()) return null
        if (!s.contains("://")) s = "https://$s"
        val origin = originOf(s) ?: return null
        val scheme = origin.substringBefore("://").lowercase(Locale.ROOT)
        if (scheme != "https" && !(allowHttp && scheme == "http")) return null
        return scheme + "://" + origin.substringAfter("://")
    }
}
