package com.savahbot.live

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow

// Plain Kotlin, no Android classes: unit-tested on a normal JVM.

/** The colours of the panel. Everything the overlay draws (text, icons, sliders, outlines) takes its colour from one of these, so one choice re-colours the lot. */
class Theme(
    val id: Int,
    val name: String,
    val bg: Int,        // window background (its transparency is the opacity slider)
    val surface: Int,   // raised parts: the tray, the chat pop-out card
    val text: Int,
    val muted: Int,
    val accent: Int,    // live dot, sliders, the resize outline
    val heart: Int      // the likes heart
)

object Themes {
    const val CUSTOM = 100

    val presets: List<Theme> = listOf(
        Theme(0, "Midnight", 0xFF0F1116.toInt(), 0xFF1B1F29.toInt(), 0xFFF1F2F5.toInt(), 0xFF9AA0B0.toInt(), 0xFFE5242B.toInt(), 0xFFFF4D55.toInt()),
        Theme(1, "Light", 0xFFFFFFFF.toInt(), 0xFFEEF0F5.toInt(), 0xFF14161C.toInt(), 0xFF5B6170.toInt(), 0xFFE5242B.toInt(), 0xFFE5242B.toInt()),
        Theme(2, "Savah red", 0xFF8E1016.toInt(), 0xFFA8141B.toInt(), 0xFFFFFFFF.toInt(), 0xFFF2B8BB.toInt(), 0xFFFFFFFF.toInt(), 0xFFFFD0D3.toInt()),
        Theme(3, "Ocean", 0xFF0A2533.toInt(), 0xFF103447.toInt(), 0xFFE8F6FF.toInt(), 0xFF8FB4C8.toInt(), 0xFF38BDF8.toInt(), 0xFFFF6B8A.toInt()),
        Theme(4, "Forest", 0xFF0D2419.toInt(), 0xFF143325.toInt(), 0xFFE9FBF1.toInt(), 0xFF8DB9A0.toInt(), 0xFF34D399.toInt(), 0xFFFF6B7A.toInt()),
        Theme(5, "Violet", 0xFF1A1230.toInt(), 0xFF241A44.toInt(), 0xFFF1ECFF.toInt(), 0xFFA99BD0.toInt(), 0xFFA78BFA.toInt(), 0xFFFF6BB0.toInt())
    )

    fun byId(id: Int, hue: Int, light: Int): Theme =
        if (id == CUSTOM) custom(hue, light) else (presets.firstOrNull { it.id == id } ?: presets[0])

    /** Your own colour: pick a hue (0 to 359) and how light it is (8 to 94). Text, icons and cards pick colours that stay readable on it. */
    fun custom(hue: Int, light: Int): Theme {
        val bg = hsl(hue.coerceIn(0, 359), 0.42f, light.coerceIn(8, 94) / 100f)
        val lightInk = 0xFFF4F5F8.toInt()
        val darkInk = 0xFF13151B.toInt()
        val text = if (contrast(lightInk, bg) >= contrast(darkInk, bg)) lightInk else darkInk   // whichever reads better on this colour
        val surface = mix(bg, text, 0.09f)
        val muted = mix(bg, text, 0.62f)
        val red = 0xFFE5242B.toInt()
        val accent = if (contrast(red, bg) >= 2.2) red else text
        val heart = if (contrast(0xFFFF4D55.toInt(), bg) >= 2.2) 0xFFFF4D55.toInt() else text
        return Theme(CUSTOM, "Custom", bg, surface, text, muted, accent, heart)
    }

    /** The colour with its transparency set to [percent] (0 to 100). */
    fun withAlpha(color: Int, percent: Int): Int {
        val a = (percent.coerceIn(0, 100) * 255 / 100)
        return (a shl 24) or (color and 0x00FFFFFF)
    }

    fun mix(a: Int, b: Int, t: Float): Int {
        fun ch(shift: Int): Int {
            val x = (a shr shift) and 0xFF
            val y = (b shr shift) and 0xFF
            return (x + (y - x) * t).toInt().coerceIn(0, 255)
        }
        return (0xFF shl 24) or (ch(16) shl 16) or (ch(8) shl 8) or ch(0)
    }

    /** hue 0..359, saturation and lightness 0..1 -> opaque ARGB. */
    fun hsl(h: Int, s: Float, l: Float): Int {
        val c = (1f - abs(2f * l - 1f)) * s
        val x = c * (1f - abs((h / 60f) % 2f - 1f))
        val m = l - c / 2f
        val (r, g, b) = when {
            h < 60 -> Triple(c, x, 0f)
            h < 120 -> Triple(x, c, 0f)
            h < 180 -> Triple(0f, c, x)
            h < 240 -> Triple(0f, x, c)
            h < 300 -> Triple(x, 0f, c)
            else -> Triple(c, 0f, x)
        }
        fun chn(v: Float): Int = ((v + m) * 255f + 0.5f).toInt().coerceIn(0, 255)
        return (0xFF shl 24) or (chn(r) shl 16) or (chn(g) shl 8) or chn(b)
    }

    /** WCAG relative luminance, 0 (black) to 1 (white). */
    fun luminance(color: Int): Double {
        fun lin(v: Int): Double {
            val c = v / 255.0
            return if (c <= 0.03928) c / 12.92 else ((c + 0.055) / 1.055).pow(2.4)
        }
        return 0.2126 * lin((color shr 16) and 0xFF) + 0.7152 * lin((color shr 8) and 0xFF) + 0.0722 * lin(color and 0xFF)
    }

    /** WCAG contrast ratio, 1 (none) to 21 (black on white). */
    fun contrast(a: Int, b: Int): Double {
        val la = luminance(a)
        val lb = luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
    }
}
