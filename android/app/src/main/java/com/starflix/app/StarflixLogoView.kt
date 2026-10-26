package com.starflix.app

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PathMeasure
import android.graphics.Shader
import android.view.View
import android.view.animation.LinearInterpolator
import android.view.animation.PathInterpolator
import androidx.core.graphics.PathParser

/** Logo animado do StarFlix (o mesmo do pré-loading do site e da TV), desenhado em View para a tela de conexão do celular. */
class StarflixLogoView(context: Context) : View(context) {
    private val star = PathParser.createPathFromPathData(STAR_D)
    private val flix = PathParser.createPathFromPathData(FLIX_D)
    private val ring = PathParser.createPathFromPathData(RING_D)
    private val measure = PathMeasure(ring, false)
    private val seg = Path()
    private val easeOpen = PathInterpolator(0.22f, 0.61f, 0.36f, 1f)
    private val easeRing = PathInterpolator(0.45f, 0f, 0.2f, 1f)
    private var t = END
    private var anim: ValueAnimator? = null

    private val starPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.parseColor("#CC1212") }
    private val flixPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.parseColor("#FBE27C") }
    private val barBottom = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        shader = LinearGradient(33.8f, 0f, 217f, 0f, Color.parseColor("#E5251D"), Color.parseColor("#E6D530"), Shader.TileMode.CLAMP)
    }
    private val barTop = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        shader = LinearGradient(230f, 0f, 388.1f, 0f, Color.parseColor("#E8301F"), Color.parseColor("#B9E22E"), Shader.TileMode.CLAMP)
    }
    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 3.5f
        strokeCap = Paint.Cap.ROUND
        shader = LinearGradient(
            101f, 330f, 346f, 170f,
            intArrayOf(Color.parseColor("#2F62FF"), Color.parseColor("#6B3FC9"), Color.parseColor("#EE3A2A")),
            floatArrayOf(0f, 0.45f, 1f), Shader.TileMode.CLAMP,
        )
    }

    /** Anima a abertura do logo (~2,4 s); sem chamar, o logo aparece completo. */
    fun play() {
        anim?.cancel()
        t = 0f
        anim = ValueAnimator.ofFloat(0f, END).apply {
            duration = (END * 1000).toLong()
            interpolator = LinearInterpolator()
            addUpdateListener { t = it.animatedValue as Float; invalidate() }
            start()
        }
    }

    override fun onDetachedFromWindow() {
        anim?.cancel()
        super.onDetachedFromWindow()
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val w = MeasureSpec.getSize(widthMeasureSpec)
        setMeasuredDimension(w, (w * (Y1 - Y0) / (X1 - X0)).toInt())
    }

    private fun prog(now: Float, begin: Float, dur: Float, e: PathInterpolator) = e.getInterpolation(((now - begin) / dur).coerceIn(0f, 1f))

    override fun onDraw(c: Canvas) {
        val s = width / (X1 - X0)
        c.save()
        c.scale(s, s)
        c.translate(-X0, -Y0)
        val rp = prog(t, 0.9f, 1.5f, easeRing)
        if (rp > 0f) {
            seg.reset()
            measure.getSegment(0f, measure.length * rp, seg, true)
            c.drawPath(seg, ringPaint)
        }
        val p = prog(t, 0.2f, 0.9f, easeOpen)
        if (p > 0f) {
            c.save()
            c.clipRect(223.5f - 200f * p, 160f, 223.5f, 290f)
            c.translate(70f * (1f - p), 0f)
            c.drawPath(star, starPaint)
            c.drawRect(33.8f, 246f, 217f, 254f, barBottom)
            c.restore()
            c.save()
            c.clipRect(223.5f, 160f, 223.5f + 200f * p, 290f)
            c.translate(-70f * (1f - p), 0f)
            c.drawRect(230f, 192.1f, 388.1f, 200.1f, barTop)
            c.drawPath(flix, flixPaint)
            c.restore()
        }
        c.restore()
    }

    private companion object {
        const val END = 2.4f
        const val X0 = 20f
        const val X1 = 427f
        const val Y0 = 95f
        const val Y1 = 352f
        const val STAR_D = "M64.95 190.29V198.31Q61.82 196.91 58.85 196.2Q55.88 195.49 53.24 195.49Q49.74 195.49 48.06 196.46Q46.39 197.42 46.39 199.45Q46.39 200.97 47.52 201.83Q48.65 202.68 51.62 203.29L55.78 204.12Q62.1 205.39 64.77 207.98Q67.44 210.57 67.44 215.35Q67.44 221.62 63.72 224.68Q60 227.74 52.35 227.74Q48.75 227.74 45.12 227.05Q41.49 226.37 37.86 225.02V216.77Q41.49 218.7 44.88 219.67Q48.27 220.65 51.41 220.65Q54.61 220.65 56.31 219.59Q58.02 218.52 58.02 216.54Q58.02 214.76 56.86 213.8Q55.71 212.83 52.25 212.07L48.47 211.23Q42.78 210.01 40.15 207.35Q37.53 204.68 37.53 200.16Q37.53 194.5 41.18 191.45Q44.84 188.41 51.69 188.41Q54.82 188.41 58.12 188.88Q61.42 189.35 64.95 190.29Z M81.5 189.09H116.44V196.48H103.87V227H94.09V196.48H81.5Z M154.49 220.09H139.21L136.79 227H126.97L141.01 189.09H152.66L166.71 227H156.88ZM141.64 213.06H152.03L146.85 197.98Z M195.62 205.9Q198.69 205.9 200.03 204.76Q201.36 203.62 201.36 201Q201.36 198.41 200.03 197.29Q198.69 196.18 195.62 196.18H191.51V205.9ZM191.51 212.65V227H181.73V189.09H196.66Q204.15 189.09 207.64 191.61Q211.13 194.12 211.13 199.55Q211.13 203.31 209.32 205.72Q207.5 208.13 203.85 209.28Q205.85 209.73 207.44 211.35Q209.03 212.96 210.65 216.23L215.96 227H205.55L200.93 217.58Q199.53 214.74 198.1 213.7Q196.66 212.65 194.28 212.65Z"
        const val FLIX_D = "M234.77 220.09H261.15V227.48H244.55V234.54H260.16V241.93H244.55V258H234.77Z M280.29 220.09H290.07V250.61H307.23V258H280.29Z M323.43 220.09H333.21V258H323.43Z M373.9 238.65 387.05 258H376.87L368.01 245.05L359.23 258H348.99L362.15 238.65L349.5 220.09H359.71L368.01 232.3L376.29 220.09H386.55Z"
        const val RING_D = "M 108.4 264 A 122 122 0 1 0 112.9 172"
    }
}
