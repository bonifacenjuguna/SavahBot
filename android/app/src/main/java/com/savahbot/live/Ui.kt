package com.savahbot.live

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView

/** The small kit the app's screens are built from, so every screen looks like it belongs to the same app. No layout XML, no libraries. */
class Ui(private val ctx: Context) {
    companion object {
        const val BG = 0xFF0A0C11.toInt()
        const val CARD = 0xFF141821.toInt()
        const val RAISED = 0xFF1C2230.toInt()
        const val LINE = 0x1FFFFFFF
        const val INK = 0xFFF3F5F9.toInt()
        const val MUTED = 0xFF8C93A6.toInt()
        const val RED = 0xFFE5242B.toInt()
        const val GREEN = 0xFF34D399.toInt()
        const val AMBER = 0xFFF5B301.toInt()
        const val PRIMARY = 0
        const val SECONDARY = 1
        const val QUIET = 2
    }

    fun dp(v: Int): Int = dpOf(ctx, v)

    fun round(color: Int, radiusDp: Int, strokeColor: Int = 0, strokeDp: Int = 0): GradientDrawable {
        val g = GradientDrawable()
        g.setColor(color)
        g.setCornerRadius(dp(radiusDp).toFloat())
        if (strokeDp > 0) g.setStroke(dp(strokeDp), strokeColor)
        return g
    }

    fun text(s: CharSequence, sizeSp: Float, color: Int, bold: Boolean = false): TextView {
        val t = TextView(ctx)
        t.text = s
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sizeSp)
        t.setTextColor(color)
        if (bold) t.setTypeface(Typeface.DEFAULT_BOLD)
        t.setLineSpacing(0f, 1.15f)
        return t
    }

    fun icon(res: Int, color: Int, sizeDp: Int): ImageView = iconView(ctx, res, color, sizeDp)

    fun space(h: Int): View {
        val v = View(ctx)
        v.layoutParams = LinearLayout.LayoutParams(1, dp(h))
        return v
    }

    fun card(padding: Int = 20): LinearLayout {
        val c = LinearLayout(ctx)
        c.orientation = LinearLayout.VERTICAL
        c.setPadding(dp(padding), dp(padding), dp(padding), dp(padding))
        c.background = round(CARD, 24, LINE, 1)
        c.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).also { it.bottomMargin = dp(14) }
        return c
    }

    /** "SavahLive" with the Live in red. */
    fun wordmark(sizeSp: Float): TextView {
        val sb = SpannableStringBuilder("SavahLive")
        sb.setSpan(ForegroundColorSpan(RED), 5, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        return text(sb, sizeSp, INK, true)
    }

    fun button(label: String, iconRes: Int?, kind: Int, onClick: () -> Unit): LinearLayout {
        val b = LinearLayout(ctx)
        b.orientation = LinearLayout.HORIZONTAL
        b.gravity = Gravity.CENTER
        b.setPadding(dp(18), 0, dp(18), 0)
        val fill = when (kind) {
            PRIMARY -> round(RED, 16)
            SECONDARY -> round(RAISED, 16, LINE, 1)
            else -> round(0x00000000, 16)
        }
        b.background = RippleDrawable(ColorStateList.valueOf(0x33FFFFFF), fill, null)
        val ink = if (kind == QUIET) MUTED else INK
        if (iconRes != null) {
            b.addView(icon(iconRes, ink, 20), LinearLayout.LayoutParams(dp(20), dp(20)).also { it.rightMargin = dp(10) })
        }
        b.addView(text(label, 16f, ink, true))
        b.isClickable = true
        b.isFocusable = true
        b.setOnClickListener { onClick() }
        b.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(if (kind == QUIET) 46 else 54)).also { it.topMargin = dp(10) }
        return b
    }

    fun setEnabled(b: View, on: Boolean) {
        b.isEnabled = on
        b.alpha = if (on) 1f else 0.5f
    }

    fun field(hint: String, value: String, onChange: (String) -> Unit): EditText {
        val e = EditText(ctx)
        e.hint = hint
        e.setText(value)
        e.setTextColor(INK)
        e.setHintTextColor(MUTED)
        e.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
        e.setSingleLine(true)
        e.inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS or android.text.InputType.TYPE_TEXT_VARIATION_URI
        e.setPadding(dp(16), dp(14), dp(16), dp(14))
        e.background = round(RAISED, 16, LINE, 1)
        e.addTextChangedListener(object : android.text.TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: android.text.Editable?) {
                onChange(s?.toString() ?: "")
            }
        })
        return e
    }

    /** A round tinted badge holding an icon or a number. */
    fun badge(content: View, tint: Int, sizeDp: Int): LinearLayout {
        val b = LinearLayout(ctx)
        b.gravity = Gravity.CENTER
        b.background = round(tint, sizeDp / 2)
        b.addView(content)
        b.layoutParams = LinearLayout.LayoutParams(dp(sizeDp), dp(sizeDp))
        return b
    }

    fun numberBadge(n: Int): LinearLayout = badge(text(n.toString(), 13f, INK, true), RAISED, 26)

    fun iconBadge(res: Int, color: Int, sizeDp: Int = 44): LinearLayout =
        badge(icon(res, color, sizeDp / 2), (color and 0x00FFFFFF) or 0x26000000, sizeDp)

    /** icon + title + small text on one row. */
    fun infoRow(res: Int, color: Int, title: String, body: String): LinearLayout {
        val row = LinearLayout(ctx)
        row.orientation = LinearLayout.HORIZONTAL
        row.gravity = Gravity.CENTER_VERTICAL
        row.setPadding(0, dp(8), 0, dp(8))
        row.addView(iconBadge(res, color, 42))
        val col = LinearLayout(ctx)
        col.orientation = LinearLayout.VERTICAL
        col.addView(text(title, 15f, INK, true))
        col.addView(text(body, 13f, MUTED))
        row.addView(col, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).also { it.leftMargin = dp(14) })
        return row
    }

    fun numberedStep(n: Int, body: String): LinearLayout {
        val row = LinearLayout(ctx)
        row.orientation = LinearLayout.HORIZONTAL
        row.setPadding(0, dp(5), 0, dp(5))
        row.addView(numberBadge(n))
        row.addView(text(body, 14f, MUTED), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).also { it.leftMargin = dp(12) })
        return row
    }

    /** Three segments: where you are in Pair > Allow > Go. */
    fun stepBar(current: Int): LinearLayout {
        val names = listOf("Pair", "Allow", "Go")
        val row = LinearLayout(ctx)
        row.orientation = LinearLayout.HORIZONTAL
        for ((i, name) in names.withIndex()) {
            val col = LinearLayout(ctx)
            col.orientation = LinearLayout.VERTICAL
            val bar = View(ctx)
            bar.background = round(if (i <= current) RED else 0x26FFFFFF, 3)
            col.addView(bar, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(5)))
            col.addView(text(name, 12f, if (i <= current) INK else MUTED, i == current), LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).also { it.topMargin = dp(6) })
            row.addView(col, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).also { it.rightMargin = if (i < names.size - 1) dp(8) else 0 })
        }
        row.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).also { it.bottomMargin = dp(18) }
        return row
    }

    fun chip(label: String, color: Int): TextView {
        val t = text(label, 12f, color, true)
        t.setPadding(dp(10), dp(4), dp(10), dp(4))
        t.background = round((color and 0x00FFFFFF) or 0x26000000, 10)
        return t
    }
}
