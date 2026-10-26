package com.starflix.app

import android.app.Application

/** 59.30: inicia `Txt` antes de qualquer tela ou serviço. */
class SfApp : Application() {
    override fun onCreate() { super.onCreate(); Txt.init(this) }
}
