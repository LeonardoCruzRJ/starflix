package com.starflix.app

import android.app.UiModeManager
import android.content.Intent
import android.content.res.Configuration
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Porta de entrada sem tela: a TV abre a interface nativa; o celular escolhe o endereço do servidor guardado em [ServerStore]
 * (58.12: testa todos em paralelo em /api/server-info, confere o `id` e usa o primeiro que responde; a lista é atualizada com o que o
 * servidor devolve) e abre o site. Sem servidor, vai para a [ConnectActivity]. O app não traz endereço fixo (58.10).
 */
class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val tv = (getSystemService(UI_MODE_SERVICE) as UiModeManager).currentModeType == Configuration.UI_MODE_TYPE_TELEVISION
        if (tv) {
            startActivity(Intent(this, TvActivity::class.java))
            finish()
            return
        }
        val store = ServerStore(this)
        store.migrateLegacy(this)
        if (!store.hasServer()) {
            startActivity(Intent(this, ConnectActivity::class.java))
            finish()
            return
        }
        Thread {
            // 60.3: ninguém respondeu (porta ou IP do servidor mudou): procura por mDNS o servidor de mesmo id e grava o endereço novo
            val hit = pick(store) ?: ServerRefind.byId(this, store.id)
            if (hit != null) store.save(hit.first, hit.second, preferExternal = true)  // celular grava o externo; aprende endereços novos (mudança de domínio)
            val base = hit?.second ?: store.current.ifBlank { store.urls.first() }  // ninguém respondeu: a página de erro oferece "Tentar de novo"
            runOnUiThread {
                getSharedPreferences("starflix", MODE_PRIVATE).edit().putString(KEY_URL, base).apply()  // WebActivity e PlayerActivity leem daqui
                startActivity(Intent(this, WebActivity::class.java))
                finish()
            }
        }.start()
    }

    /** Testa o último endereço e a lista em paralelo (3 s cada); vale o primeiro que responde com o mesmo `id`. */
    private fun pick(store: ServerStore): Pair<ServerInfo, String>? {
        val urls = (listOf(store.current) + store.urls).filter { it.isNotBlank() }.distinct()
        if (urls.isEmpty()) return null
        val pool = Executors.newFixedThreadPool(urls.size)
        return try {
            val id = store.id
            pool.invokeAny(urls.map { u ->
                Callable<Pair<ServerInfo, String>> {
                    val i = TvApi.serverInfo(u, 3000) ?: throw IllegalStateException("sem resposta")
                    if (id.isNotEmpty() && i.id.isNotEmpty() && i.id != id) throw IllegalStateException("outro servidor")
                    i to u
                }
            }, 5, TimeUnit.SECONDS)
        } catch (e: Exception) {
            null
        } finally {
            pool.shutdownNow()
        }
    }

    companion object {
        const val KEY_URL = "server_url"
    }
}
