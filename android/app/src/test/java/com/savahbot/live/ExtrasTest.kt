package com.savahbot.live

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ExtrasTest {
    @Test fun newerVersionsAreComparedByNumber() {
        assertTrue(Versions.isNewer("1.6.2", "1.6.1"))
        assertTrue(Versions.isNewer("1.6.10", "1.6.9"))
        assertTrue(Versions.isNewer("2.0", "1.9.9"))
        assertFalse(Versions.isNewer("1.6.1", "1.6.1"))
        assertFalse(Versions.isNewer("1.6.0", "1.6.1"))
        assertFalse(Versions.isNewer("", "1.6.1"))
        assertFalse(Versions.isNewer("abc", "1.6.1"))
    }

    @Test fun milestonesFireOnceWhenARoundNumberIsPassed() {
        assertEquals(100L, Milestones.crossed(99, 103, 100))
        assertEquals(300L, Milestones.crossed(95, 312, 100))      // a jump over several: the highest one
        assertNull(Milestones.crossed(103, 105, 100))
        assertNull(Milestones.crossed(null, 105, 100))            // the first numbers after connecting never celebrate
        assertNull(Milestones.crossed(120, 90, 100))              // going down never does
        assertNull(Milestones.crossed(99, 200, 0))                // step 0 is off
    }

    @Test fun theTallyCountsPeopleNotNotesOrYourOwnLines() {
        val t = StreamTally()
        t.message(Line(1, "a", "Ann", "hi", "everyone"))
        t.message(Line(2, "a", "Ann", "again", "everyone"))
        t.message(Line(3, "b", "Bo", "yo", "member"))
        t.message(Line(0, "", "", "+5 more messages", "note"))
        t.message(Line(0, "self", "You", "gg", "owner"))
        t.viewers(40); t.viewers(120); t.viewers(80)
        t.likes(10); t.likes(7)
        assertEquals(3, t.messages)
        assertEquals(120L, t.peakViewers)
        assertEquals(10L, t.lastLikes)
        assertEquals(listOf(Pair("Ann", 2), Pair("Bo", 1)), t.top())
        assertTrue(t.hasData)
        assertFalse(StreamTally().hasData)
    }
}
