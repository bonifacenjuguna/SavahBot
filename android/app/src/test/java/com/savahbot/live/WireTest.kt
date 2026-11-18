package com.savahbot.live

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WireTest {
    @Test fun countsAreShort() {
        assertEquals("\u2014", Fmt.count(null))
        assertEquals("950", Fmt.count(950))
        assertEquals("1.2K", Fmt.count(1234))
        assertEquals("1K", Fmt.count(1000))
        assertEquals("12.5K", Fmt.count(12_500))
        assertEquals("100K", Fmt.count(99_960))
        assertEquals("123K", Fmt.count(123_456))
        assertEquals("2.4M", Fmt.count(2_400_000))
    }

    @Test fun backoffGrowsAndStaysCapped() {
        assertEquals(1000L, Backoff.delayMs(0, 0.5))
        assertEquals(2000L, Backoff.delayMs(1, 0.5))
        assertEquals(60_000L, Backoff.delayMs(20, 0.5))
        assertTrue(Backoff.delayMs(3, 0.0) < Backoff.delayMs(3, 1.0))
    }

    @Test fun sseEventsAreAssembled() {
        val got = ArrayList<Pair<String, String>>()
        val p = SseParser { e, d -> got.add(e to d) }
        for (l in listOf("retry: 5000", "", ": ping", "event: stats", "data: {\"a\":1}", "", "data: one", "data:two", "")) p.feed(l)
        assertEquals(listOf("stats" to "{\"a\":1}", "message" to "one\ntwo"), got)
    }

    @Test fun pairingLinksAndCodes() {
        val a = Pairing.parse("savahlive://pair?s=https%3A%2F%2Fbot.up.railway.app&c=K7Q49M2X")!!
        assertEquals("https://bot.up.railway.app", a.server)
        assertEquals("K7Q49M2X", a.code)
        val b = Pairing.parse("https://bot.up.railway.app/api/live/pair/open?c=k7q4-9m2x")!!
        assertEquals("https://bot.up.railway.app", b.server)
        assertEquals("K7Q49M2X", b.code)
        val c = Pairing.parse(" k7q4-9m2x ", "bot.example.app")!!
        assertEquals("bot.example.app", c.server)
        assertNull(Pairing.parse("hello"))
        assertNull(Pairing.parse("savahlive://pair?s=x&c=SHORT"))
        assertNull(Pairing.parse("K7Q49M2X1"))
    }

    @Test fun serversMustBeHttps() {
        assertEquals("https://bot.example.app", Pairing.normalizeServer("bot.example.app/", false))
        assertEquals("https://bot.example.app:8443", Pairing.normalizeServer("https://bot.example.app:8443/x", false))
        assertNull(Pairing.normalizeServer("http://bot.example.app", false))
        assertEquals("http://10.0.2.2:8000", Pairing.normalizeServer("http://10.0.2.2:8000", true))
        assertNull(Pairing.normalizeServer("", true))
    }
}
