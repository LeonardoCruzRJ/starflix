package com.starflix.app

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathMeasure
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.graphics.vector.PathParser
import kotlin.math.min

/** Pré-loading da TV: o mesmo logo animado do site (`_preload.html`), 5 s, só ao abrir o app. */
private const val STAR_D = "M64.95 190.29V198.31Q61.82 196.91 58.85 196.2Q55.88 195.49 53.24 195.49Q49.74 195.49 48.06 196.46Q46.39 197.42 46.39 199.45Q46.39 200.97 47.52 201.83Q48.65 202.68 51.62 203.29L55.78 204.12Q62.1 205.39 64.77 207.98Q67.44 210.57 67.44 215.35Q67.44 221.62 63.72 224.68Q60 227.74 52.35 227.74Q48.75 227.74 45.12 227.05Q41.49 226.37 37.86 225.02V216.77Q41.49 218.7 44.88 219.67Q48.27 220.65 51.41 220.65Q54.61 220.65 56.31 219.59Q58.02 218.52 58.02 216.54Q58.02 214.76 56.86 213.8Q55.71 212.83 52.25 212.07L48.47 211.23Q42.78 210.01 40.15 207.35Q37.53 204.68 37.53 200.16Q37.53 194.5 41.18 191.45Q44.84 188.41 51.69 188.41Q54.82 188.41 58.12 188.88Q61.42 189.35 64.95 190.29Z M81.5 189.09H116.44V196.48H103.87V227H94.09V196.48H81.5Z M154.49 220.09H139.21L136.79 227H126.97L141.01 189.09H152.66L166.71 227H156.88ZM141.64 213.06H152.03L146.85 197.98Z M195.62 205.9Q198.69 205.9 200.03 204.76Q201.36 203.62 201.36 201Q201.36 198.41 200.03 197.29Q198.69 196.18 195.62 196.18H191.51V205.9ZM191.51 212.65V227H181.73V189.09H196.66Q204.15 189.09 207.64 191.61Q211.13 194.12 211.13 199.55Q211.13 203.31 209.32 205.72Q207.5 208.13 203.85 209.28Q205.85 209.73 207.44 211.35Q209.03 212.96 210.65 216.23L215.96 227H205.55L200.93 217.58Q199.53 214.74 198.1 213.7Q196.66 212.65 194.28 212.65Z"
private const val FLIX_D = "M234.77 220.09H261.15V227.48H244.55V234.54H260.16V241.93H244.55V258H234.77Z M280.29 220.09H290.07V250.61H307.23V258H280.29Z M323.43 220.09H333.21V258H323.43Z M373.9 238.65 387.05 258H376.87L368.01 245.05L359.23 258H348.99L362.15 238.65L349.5 220.09H359.71L368.01 232.3L376.29 220.09H386.55Z"
private const val RING_D = "M 108.4 264 A 122 122 0 1 0 112.9 172"
private val EASE_OPEN = CubicBezierEasing(0.22f, 0.61f, 0.36f, 1f)
private val EASE_RING = CubicBezierEasing(0.45f, 0f, 0.2f, 1f)

private fun prog(t: Float, begin: Float, dur: Float, e: CubicBezierEasing) = e.transform(((t - begin) / dur).coerceIn(0f, 1f))

@Composable
fun SplashScreen(onDone: () -> Unit) {
    val t = remember { Animatable(0f) }
    LaunchedEffect(Unit) {
        t.animateTo(5f, tween(5000, easing = LinearEasing))
        onDone()
    }
    val star = remember { PathParser().parsePathString(STAR_D).toPath() }
    val flix = remember { PathParser().parsePathString(FLIX_D).toPath() }
    val ring = remember { PathParser().parsePathString(RING_D).toPath() }
    val measure = remember { PathMeasure().also { it.setPath(ring, false) } }
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        Canvas(Modifier.fillMaxSize()) {
            val now = t.value
            val s = min(size.width, size.height) * 0.62f / 447f
            val ox = (size.width - 447f * s) / 2f
            val oy = (size.height - 447f * s) / 2f
            withTransform({ translate(ox, oy); scale(s, s, Offset.Zero) }) {
                val rp = prog(now, 1.7f, 1.8f, EASE_RING)
                if (rp > 0f) {
                    val seg = Path()
                    measure.getSegment(0f, measure.length * rp, seg, true)
                    drawPath(
                        seg,
                        Brush.linearGradient(
                            0f to Color(0xFF2F62FF), 0.45f to Color(0xFF6B3FC9), 1f to Color(0xFFEE3A2A),
                            start = Offset(101f, 330f), end = Offset(346f, 170f),
                        ),
                        style = Stroke(width = 3.5f, cap = StrokeCap.Round),
                    )
                }
                val p = prog(now, 0.4f, 1.2f, EASE_OPEN)
                if (p > 0f) {
                    clipRect(223.5f - 200f * p, 160f, 223.5f, 290f) {
                        translate(70f * (1f - p), 0f) {
                            drawPath(star, Color(0xFFCC1212))
                            drawRect(
                                Brush.horizontalGradient(listOf(Color(0xFFE5251D), Color(0xFFE6D530)), startX = 33.8f, endX = 217f),
                                topLeft = Offset(33.8f, 246f), size = Size(183.2f, 8f),
                            )
                        }
                    }
                    clipRect(223.5f, 160f, 223.5f + 200f * p, 290f) {
                        translate(-70f * (1f - p), 0f) {
                            drawRect(
                                Brush.horizontalGradient(listOf(Color(0xFFE8301F), Color(0xFFB9E22E)), startX = 230f, endX = 388.1f),
                                topLeft = Offset(230f, 192.1f), size = Size(158.1f, 8f),
                            )
                            drawPath(flix, Color(0xFFFBE27C))
                        }
                    }
                }
            }
        }
    }
}
