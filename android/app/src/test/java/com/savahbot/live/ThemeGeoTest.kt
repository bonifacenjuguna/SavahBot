package com.savahbot.live

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ThemeGeoTest {
    @Test fun contrastIsSensible() {
        assertEquals(21.0, Themes.contrast(0xFF000000.toInt(), 0xFFFFFFFF.toInt()), 0.01)
        assertEquals(1.0, Themes.contrast(0xFF808080.toInt(), 0xFF808080.toInt()), 0.001)
    }

    @Test fun everyPresetIsReadable() {
        for (t in Themes.presets) {
            assertTrue(t.name + " text", Themes.contrast(t.text, t.bg) >= 7.0)
            assertTrue(t.name + " muted", Themes.contrast(t.muted, t.bg) >= 3.0)
            assertTrue(t.name + " accent", Themes.contrast(t.accent, t.bg) >= 2.0)
        }
    }

    @Test fun customThemesStayReadableAtEveryLightness() {
        for (hue in 0 until 360 step 30) for (light in 8..94 step 6) {
            val t = Themes.custom(hue, light)
            assertTrue("hue $hue light $light", Themes.contrast(t.text, t.bg) >= 4.0)
        }
    }

    @Test fun unknownThemeFallsBackToMidnight() {
        assertEquals(0, Themes.byId(99, 0, 0).id)
        assertEquals(Themes.CUSTOM, Themes.byId(Themes.CUSTOM, 200, 20).id)
    }

    @Test fun alphaKeepsTheColour() {
        assertEquals(0x112233, Themes.withAlpha(0xFF112233.toInt(), 50) and 0xFFFFFF)
        assertEquals(0x00, Themes.withAlpha(0xFFFFFFFF.toInt(), 0) ushr 24)
        assertEquals(0xFF, Themes.withAlpha(0xFFFFFFFF.toInt(), 100) ushr 24)
    }

    @Test fun scaleStaysProportionalAndFitsTheScreen() {
        assertEquals(1.5f, Geo.scaleFromDrag(0f, 0f, 450f, 300f, 300, 380), 0.001f)
        assertEquals(1.0f, Geo.scaleFromDrag(100f, 0f, -200f, 380f, 300, 380), 0.001f)
        assertEquals(1.173f, Geo.maxScale(600, 760, 720, 1600, 8, 0.5f, 1.6f), 0.01f)
        assertEquals(0.5f, Geo.maxScale(600, 760, 300, 300, 8, 0.5f, 1.6f), 0.001f)
        assertEquals(0.5f, Geo.clampScale(0.1f, 0.5f, 1.2f), 0.001f)
    }

    @Test fun tuckingPicksTheRightEdge() {
        assertEquals(Edge.LEFT, Geo.nearestEdge(100f, 800f, 720, 1600))
        assertEquals(Edge.RIGHT, Geo.nearestEdge(650f, 800f, 720, 1600))
        assertEquals(Edge.TOP, Geo.nearestEdge(360f, 100f, 720, 1600))
        assertEquals(Edge.BOTTOM, Geo.nearestEdge(360f, 1500f, 720, 1600))
        assertNull(Geo.overshootEdge(100, 100, 300, 380, 720, 1600, 0.35f))
        assertEquals(Edge.LEFT, Geo.overshootEdge(-150, 500, 300, 380, 720, 1600, 0.35f))
        assertEquals(Edge.RIGHT, Geo.overshootEdge(600, 500, 300, 380, 720, 1600, 0.35f))
        assertEquals(Edge.BOTTOM, Geo.overshootEdge(100, 1500, 300, 380, 720, 1600, 0.35f))
    }

    @Test fun positionAlongAnEdgeSurvivesRotation() {
        val f = Geo.alongFraction(Edge.RIGHT, 0, 700, 100, 200, 720, 1600)
        assertEquals(0.5f, f, 0.001f)
        assertEquals(260, Geo.alongPx(Edge.RIGHT, f, 100, 200, 1600, 720))   // rotated to landscape: still halfway down the right edge
        assertEquals(Pair(-90, 300), Geo.flush(Edge.LEFT, 300, 100, 200, 720, 1600, 90))
        assertEquals(Pair(710, 300), Geo.flush(Edge.RIGHT, 300, 100, 200, 720, 1600, 90))
        assertEquals(Pair(200, -190), Geo.flush(Edge.TOP, 200, 100, 200, 720, 1600, 190))
    }

    // ---- the free-form panel: touch zones and resizing -------------------------------------------------------------------------------------
    @Test fun touchZonesCoverEveryEdgeAndCorner() {
        val w = 800
        val h = 1000
        assertEquals(0, Geo.hitMode(400f, 500f, w, h, 40, 20, 60))                         // the middle belongs to the chat
        assertEquals(Geo.L, Geo.hitMode(10f, 500f, w, h, 40, 20, 60))
        assertEquals(Geo.R, Geo.hitMode(790f, 500f, w, h, 40, 20, 60))
        assertEquals(Geo.T, Geo.hitMode(400f, 5f, w, h, 40, 20, 60))
        assertEquals(Geo.B, Geo.hitMode(400f, 990f, w, h, 40, 20, 60))
        assertEquals(Geo.L or Geo.T, Geo.hitMode(5f, 5f, w, h, 40, 20, 60))
        assertEquals(Geo.R or Geo.B, Geo.hitMode(795f, 995f, w, h, 40, 20, 60))
        assertEquals(Geo.L or Geo.T, Geo.hitMode(50f, 50f, w, h, 40, 20, 60))              // the corner square is bigger than the side bands
        assertEquals(0, Geo.hitMode(70f, 70f, w, h, 40, 20, 60))
    }

    @Test fun resizingMovesOnlyTheHeldSides() {
        // window at (100, 200), 400 x 500, on a 1080 x 2200 screen; min 200 x 150, max 700 x 900
        fun r(mode: Int, dx: Int, dy: Int) = Geo.resize(mode, 100, 200, 400, 500, dx, dy, 200, 150, 700, 900, 1080, 2200).toList()
        assertEquals(listOf(100, 200, 500, 500), r(Geo.R, 100, 999))                         // the right edge: only the width changes
        assertEquals(listOf(50, 200, 450, 500), r(Geo.L, -50, 0))                            // the left edge moves out, the right side stays at 500
        assertEquals(listOf(100, 150, 400, 550), r(Geo.T, 0, -50))
        assertEquals(listOf(100, 200, 400, 600), r(Geo.B, 0, 100))
        assertEquals(listOf(100, 200, 500, 600), r(Geo.R or Geo.B, 100, 100))                // a corner moves two sides
    }

    @Test fun resizingNeverGoesBelowTheMinimumAboveTheMaximumOrOffScreen() {
        fun r(mode: Int, dx: Int, dy: Int) = Geo.resize(mode, 100, 200, 400, 500, dx, dy, 200, 150, 700, 900, 1080, 2200).toList()
        assertEquals(listOf(300, 200, 200, 500), r(Geo.L, 900, 0))                           // dragged far right: stops at the minimum width, right side still 500
        assertEquals(listOf(100, 200, 200, 150), r(Geo.R or Geo.B, -900, -900))
        assertEquals(listOf(100, 200, 700, 500), r(Geo.R, 5000, 0))                          // stops at the maximum width
        assertEquals(listOf(0, 200, 500, 500), r(Geo.L, -5000, 0))                           // and at the screen's left edge (never past 0)
        val tight = Geo.resize(Geo.R, 100, 200, 400, 500, 5000, 0, 200, 150, 5000, 900, 600, 2200)
        assertEquals(500, tight[2])                                                           // a 600 px wide screen: from x=100 the width tops out at 500
    }

    @Test fun clampNeverThrowsEvenWhenTheLimitsCross() {
        assertEquals(5, Geo.clampI(3, 5, 1))                                                  // coerceIn would throw here; the lower limit wins
        assertEquals(7, Geo.clampI(7, 0, 10))
        assertEquals(10, Geo.clampI(99, 0, 10))
    }

    @Test fun expandedWindowFitsAPhoneAndStaysSaneOnATablet() {
        val phone = Geo.expandedSize(1080, 2400, 24, 1260, 1860)
        assertEquals(1032, phone[0])
        assertTrue(phone[1] in 1000..1860)
        val tablet = Geo.expandedSize(2560, 1600, 24, 1260, 1860)
        assertEquals(1260, tablet[0])
        assertTrue(tablet[1] < 1600)
    }
}
