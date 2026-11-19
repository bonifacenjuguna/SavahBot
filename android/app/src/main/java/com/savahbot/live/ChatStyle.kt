package com.savahbot.live

import android.graphics.Typeface
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.text.style.StyleSpan

/** How one chat line looks, shared by the panel and the tab's pop-out card so they always agree. */
object ChatStyle {
    fun levelColor(theme: Theme, level: String): Int {
        val light = Themes.luminance(theme.bg) > 0.5
        return when (level) {
            "owner" -> if (light) 0xFFB7791F.toInt() else 0xFFFFC857.toInt()
            "mod" -> if (light) 0xFF2563EB.toInt() else 0xFF6EA8FF.toInt()
            "member" -> if (light) 0xFF15803D.toInt() else 0xFF4ADE80.toInt()
            else -> theme.muted
        }
    }

    fun render(theme: Theme, line: Line): CharSequence {
        val sb = SpannableStringBuilder()
        if (line.level == "note") {
            sb.append(line.text)
            sb.setSpan(ForegroundColorSpan(theme.muted), 0, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            sb.setSpan(StyleSpan(Typeface.ITALIC), 0, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            return sb
        }
        sb.append(line.name).append("  ")
        sb.setSpan(ForegroundColorSpan(levelColor(theme, line.level)), 0, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        sb.setSpan(StyleSpan(Typeface.BOLD), 0, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        sb.append(line.text)
        return sb
    }
}
