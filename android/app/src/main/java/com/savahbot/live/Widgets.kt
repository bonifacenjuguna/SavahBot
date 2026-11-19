package com.savahbot.live

import android.content.Context
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Shader
import android.view.MotionEvent
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout

fun dpOf(ctx: Context, v: Int): Int = (v * ctx.resources.displayMetrics.density + 0.5f).toInt()

/** One of the SVG-derived vector icons (res/drawable/ic_*.xml, white) in any colour. Re-colour later with setColorFilter. */
fun iconView(ctx: Context, res: Int, color: Int, sizeDp: Int): ImageView {
    val v = ImageView(ctx)
    v.setImageResource(res)
    v.setColorFilter(color)
    v.scaleType = ImageView.ScaleType.FIT_CENTER
    val px = dpOf(ctx, sizeDp)
    v.layoutParams = LinearLayout.LayoutParams(px, px)
    return v
}

/**
 * A thin line with a round handle: the slider for opacity, tab fade and colour. Set [gradient] for a colour line (the hue picker).
 * Touch it anywhere along the line. It stops parents (a scroll view, the window drag) from stealing the gesture.
 */
class LineSlider(context: Context) : View(context) {
    var min = 0
    var max = 100
    var value = 0
        set(v) {
            field = v.coerceIn(min, max)
            invalidate()
        }
    var onChange: ((Int) -> Unit)? = null
    var trackColor = 0x44FFFFFF
    var fillColor = 0xFFE5242B.toInt()
    var thumbColor = 0xFFFFFFFF.toInt()
    var gradient: IntArray? = null

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val rect = RectF()
    private val thumbR = dpOf(context, 9).toFloat()

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        setMeasuredDimension(resolveSize(dpOf(context, 120), widthMeasureSpec), dpOf(context, 30))
    }

    private fun thumbX(): Float {
        val span = (width - 2 * thumbR).coerceAtLeast(1f)
        val frac = if (max > min) (value - min).toFloat() / (max - min) else 0f
        return thumbR + span * frac
    }

    override fun onDraw(canvas: Canvas) {
        val cy = height / 2f
        val g = gradient
        val trackH = if (g != null) dpOf(context, 8).toFloat() else dpOf(context, 4).toFloat()
        rect.set(thumbR, cy - trackH / 2, width - thumbR, cy + trackH / 2)
        if (g != null) {
            paint.shader = LinearGradient(rect.left, 0f, rect.right, 0f, g, null, Shader.TileMode.CLAMP)
            paint.color = 0xFFFFFFFF.toInt()
            canvas.drawRoundRect(rect, trackH / 2, trackH / 2, paint)
            paint.shader = null
        } else {
            paint.color = trackColor
            canvas.drawRoundRect(rect, trackH / 2, trackH / 2, paint)
            paint.color = fillColor
            rect.right = thumbX()
            canvas.drawRoundRect(rect, trackH / 2, trackH / 2, paint)
        }
        paint.color = 0x55000000
        canvas.drawCircle(thumbX(), cy + 1f, thumbR + 1f, paint)
        paint.color = thumbColor
        canvas.drawCircle(thumbX(), cy, thumbR, paint)
    }

    private fun setFrom(x: Float) {
        val span = (width - 2 * thumbR).coerceAtLeast(1f)
        val frac = ((x - thumbR) / span).coerceIn(0f, 1f)
        val v = (min + frac * (max - min) + 0.5f).toInt()
        if (v != value) {
            value = v
            onChange?.invoke(v)
        }
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                parent?.requestDisallowInterceptTouchEvent(true)
                setFrom(e.x)
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                setFrom(e.x)
                return true
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                parent?.requestDisallowInterceptTouchEvent(false)
                return true
            }
        }
        return super.onTouchEvent(e)
    }
}
