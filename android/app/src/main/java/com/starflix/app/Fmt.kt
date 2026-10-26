package com.starflix.app

import android.text.format.DateFormat
import java.text.SimpleDateFormat
import java.util.Locale

/** 59.32: duração, data e números no idioma do aparelho (nada de pt-BR fixo). */
object Fmt {
    /** "1 h 30 min" / "45 min"; segundos <= 0 = vazio. */
    fun minutes(sec: Int): String {
        if (sec <= 0) return ""
        return if (sec >= 3600) Txt.s(R.string.dur_h_m, sec / 3600, sec % 3600 / 60) else Txt.s(R.string.dur_m, maxOf(1, sec / 60))
    }

    fun mins(m: Int): String = Txt.s(R.string.dur_m, m)

    /** `yyyy-MM-dd` → data por extenso do idioma (mês abreviado ou inteiro); fora do formato devolve o texto. */
    fun date(raw: String, fullMonth: Boolean = false): String = try {
        val loc = Locale.getDefault()
        val pat = DateFormat.getBestDateTimePattern(loc, if (fullMonth) "dMMMMyyyy" else "dMMMyyyy")
        SimpleDateFormat(pat, loc).format(SimpleDateFormat("yyyy-MM-dd", Locale.US).parse(raw.take(10))!!)
    } catch (e: Exception) { raw }

    fun decimal(v: Double): String = if (v == Math.floor(v)) v.toInt().toString() else "%.1f".format(Locale.getDefault(), v)

    fun ep(season: Int, episode: Int, bullet: Boolean = false): String = Txt.s(if (bullet) R.string.ep_bullet else R.string.ep_short, season, episode)
}
