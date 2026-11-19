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
}
