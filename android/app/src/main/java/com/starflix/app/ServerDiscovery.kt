package com.starflix.app

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Handler
import android.os.Looper

/**
 * 58.14: procura `_starflix._tcp` por NSD durante [start] (ms). Cada achado é resolvido (um por vez), conferido em /api/server-info
 * e entregue em [onFound] na thread principal (`info` + endereço `http://ip:porta`). Falha em silêncio (sem NSD, sem rede).
 */
class ServerDiscovery(ctx: Context, private val onFound: (ServerInfo, String) -> Unit) {
    private val nsd = ctx.applicationContext.getSystemService(Context.NSD_SERVICE) as? NsdManager
    private val ui = Handler(Looper.getMainLooper())
    private val queue = mutableListOf<NsdServiceInfo>()
    private var resolving = false
    private var listener: NsdManager.DiscoveryListener? = null
    private var dead = false

    fun start(ms: Long) {
        val m = nsd ?: return
        val l = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {}
            override fun onServiceFound(serviceInfo: NsdServiceInfo) { ui.post { queue.add(serviceInfo); next() } }
            override fun onServiceLost(serviceInfo: NsdServiceInfo) {}
            override fun onDiscoveryStopped(serviceType: String) {}
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {}
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {}
        }
        listener = l
        try {
            m.discoverServices("_starflix._tcp", NsdManager.PROTOCOL_DNS_SD, l)
        } catch (e: Exception) {
            listener = null
            return
        }
        ui.postDelayed({ stopListener() }, ms)
    }

    fun stop() {
        dead = true
        ui.removeCallbacksAndMessages(null)
        stopListener()
    }

    private fun stopListener() {
        val l = listener ?: return
        listener = null
        try { nsd?.stopServiceDiscovery(l) } catch (e: Exception) { }
    }

    @Suppress("DEPRECATION")
    private fun next() {
        if (dead || resolving || queue.isEmpty()) return
        val m = nsd ?: return
        val s = queue.removeAt(0)
        resolving = true
        try {
            m.resolveService(s, object : NsdManager.ResolveListener {
                override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                    ui.post { resolving = false; next() }
                }
                override fun onServiceResolved(serviceInfo: NsdServiceInfo) {
                    val host = serviceInfo.host?.hostAddress
                    val url = if (host == null) null else "http://${if (host.contains(':')) "[$host]" else host}:${serviceInfo.port}"
                    ui.post { resolving = false; next() }
                    if (url != null) Thread {
                        val info = TvApi.serverInfo(url)
                        if (info != null && info.mdns) ui.post { if (!dead) onFound(info, url) }
                    }.start()
                }
            })
        } catch (e: Exception) {
            resolving = false
        }
    }
}
