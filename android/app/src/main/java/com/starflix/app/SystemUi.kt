package com.starflix.app

import android.app.Activity
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

/** 54.25: esconde a barra de navegação do Android em todas as telas (volta por gesto de deslizar na borda). */
fun Activity.hideNavBar() {
    val c = WindowInsetsControllerCompat(window, window.decorView)
    c.hide(WindowInsetsCompat.Type.navigationBars())
    c.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
}
