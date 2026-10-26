package com.starflix.app

import android.content.Context
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * 60.3: o servidor mudou de porta (ou de IP) e os endereços guardados não respondem mais: procura `_starflix._tcp` por mDNS e devolve
 * o servidor de mesmo `id` com o endereço novo (a porta vem do anúncio). Bloqueia até [ms]; rodar fora da thread principal.
 */
object ServerRefind {
    fun byId(ctx: Context, id: String, ms: Long = 5000): Pair<ServerInfo, String>? {
        if (id.isEmpty()) return null
        val hit = AtomicReference<Pair<ServerInfo, String>?>(null)
        val done = CountDownLatch(1)
        val d = ServerDiscovery(ctx) { info, url ->
            if (info.id == id && hit.compareAndSet(null, info to url)) done.countDown()
        }
        d.start(ms)
        try { done.await(ms, TimeUnit.MILLISECONDS) } catch (e: InterruptedException) { }
        d.stop()
        return hit.get()
    }
}
