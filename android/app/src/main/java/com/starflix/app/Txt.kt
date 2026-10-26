package com.starflix.app

import android.content.Context

/** 59.30: textos do app fora de Compose/Activity (TvApi, TvBridgeServer, listas) e atalho dentro dele; vem do `strings.xml` gerado (i18n/*.json).
 *  `init` guarda só o contexto da aplicação; a 59.31 chama de novo com o contexto do idioma escolhido. */
object Txt {
    @Volatile private var ctx: Context? = null
    fun init(c: Context) { ctx = c.applicationContext ?: c }
    private fun c(): Context = ctx ?: throw IllegalStateException("Txt.init não chamado")
    fun s(id: Int, vararg a: Any): String = c().getString(id, *a)
    fun n(id: Int, n: Int): String = c().resources.getQuantityString(id, n, n)
}
