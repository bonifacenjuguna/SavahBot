package com.savahbot.live

import android.os.Build
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** The two plain HTTP calls the app makes besides the feed: pairing and key renewal. HttpURLConnection is part of Android, so no library is needed. */
object Net {
    class Reply(val status: Int, val body: String)
    class PairResult(val key: String, val name: String, val expires: Long)
    class PairError(message: String) : Exception(message)

    fun call(method: String, url: String, body: String?, key: String?): Reply {
        val c = URL(url).openConnection() as HttpURLConnection
        try {
            c.requestMethod = method
            c.connectTimeout = 15_000
            c.readTimeout = 20_000
            c.useCaches = false
            c.setRequestProperty("Accept", "application/json")
            c.setRequestProperty("Accept-Encoding", "identity")
            c.setRequestProperty("User-Agent", "SavahLive/" + BuildConfig.VERSION_NAME + " (Android)")
            if (key != null) c.setRequestProperty("Authorization", "Bearer $key")
            if (body != null) {
                c.doOutput = true
                c.setRequestProperty("Content-Type", "application/json")
                c.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val status = c.responseCode
            val stream = if (status in 200..399) c.inputStream else c.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            return Reply(status, text)
        } finally {
            c.disconnect()
        }
    }

    /** SavahBot's `{"error": "...", "code": "..."}` answers. */
    fun message(body: String, fallback: String): String {
        return try {
            val m = JSONObject(body).optString("error", "")
            if (m.isBlank()) fallback else m
        } catch (e: JSONException) {
            fallback
        }
    }

    fun code(body: String): String {
        return try {
            JSONObject(body).optString("code", "")
        } catch (e: JSONException) {
            ""
        }
    }

    fun deviceName(): String {
        val maker = Build.MANUFACTURER ?: ""
        val model = Build.MODEL ?: ""
        val name = if (model.startsWith(maker, ignoreCase = true)) model else maker.replaceFirstChar { it.uppercase() } + " " + model
        return name.trim().ifEmpty { "Android phone" }
    }

    /** Swaps a one-time pairing code for this phone's key. Runs on a background thread. Throws [PairError] with a message fit for the screen. */
    fun pair(server: String, code: String): PairResult {
        val body = JSONObject().put("code", code).put("name", deviceName()).put("app_version", BuildConfig.VERSION_NAME).toString()
        val reply = try {
            call("POST", "$server/api/live/pair", body, null)
        } catch (e: IOException) {
            throw PairError("Could not reach SavahBot at $server. Check the address and your connection.")
        }
        if (reply.status != 200) throw PairError(message(reply.body, "SavahBot did not accept the code (HTTP ${reply.status})."))
        try {
            val j = JSONObject(reply.body)
            val key = j.getString("key")
            if (!key.startsWith("sld_")) throw JSONException("not a device key")
            val expires = if (j.isNull("expires")) 0L else (j.getDouble("expires") * 1000).toLong()
            return PairResult(key, j.optString("name", deviceName()), expires)
        } catch (e: JSONException) {
            throw PairError("SavahBot sent an answer this app does not understand. Update SavahLive and SavahBot to the same version.")
        }
    }

    /** Sends one chat message through SavahBot (only when this phone is allowed to). Returns null on success, or a sentence for the screen. Runs on a background thread. */
    fun send(server: String, key: String, text: String): String? {
        val reply = try {
            call("POST", "$server/api/live/send", JSONObject().put("text", text).toString(), key)
        } catch (e: IOException) {
            return "Could not reach SavahBot."
        }
        if (reply.status == 200) return null
        return message(reply.body, "Could not send (HTTP ${reply.status}).")
    }

    /** Hides one chat message ("delete") or times its author out for five minutes ("timeout"). Null on success, or a sentence for the screen. Runs on a background thread. */
    fun moderate(server: String, key: String, id: Long, action: String): String? {
        val reply = try {
            call("POST", "$server/api/live/mod", JSONObject().put("id", id).put("action", action).toString(), key)
        } catch (e: IOException) {
            return "Could not reach SavahBot."
        }
        if (reply.status == 200) return null
        return message(reply.body, "Could not do that (HTTP ${reply.status}).")
    }
}
