package com.starflix.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.util.AttributeSet
import android.view.View

/** Barra de progresso do player da TV (42.3): trilha lavanda, trecho assistido mais forte e bolinha branca. */
class TvSeekView @JvmOverloads constructor(ctx: Context, attrs: AttributeSet? = null) : View(ctx, attrs) {
    var fraction = 0f
        set(v) { field = v.coerceIn(0f, 1f); invalidate() }
    var knob = false  // 43.7: bolinha só aparece no estado "barra"
        set(v) { field = v; invalidate() }
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)
    private val d = resources.displayMetrics.density

    override fun onDraw(c: Canvas) {
        val r = 6 * d
        val w = width - 2 * r
        val y = height / 2f
        val x = r + w * fraction
        p.strokeCap = Paint.Cap.ROUND
        p.strokeWidth = 4 * d
        p.color = 0x66B9B9F5
        c.drawLine(r, y, r + w, y, p)
        p.color = 0xFFB9B9F5.toInt()
        c.drawLine(r, y, x, y, p)
        p.color = 0xFFFFFFFF.toInt()
        if (knob) c.drawCircle(x, y, r, p)
    }
}
