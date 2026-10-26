package com.starflix.app

import android.os.Build
import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.Socket
import java.security.MessageDigest
import java.security.SecureRandom

/**
 * 58.15: mini servidor HTTP da TV para "Conectar pelo celular". Porta aleatória, só com a tela aberta; fecha ao concluir, ao sair ou em 10 min.
 * `POST /pair {k, server_urls, ticket}` só vale com a chave certa (128 bits; 3 erros = chave nova). Chave certa: confere o servidor em
 * /api/server-info, troca o ticket por token em `POST /api/tv/claim` e entrega tudo em [onPaired] (thread principal).
 */
class TvBridgeServer(
    private val onPaired: (ServerInfo, String, String) -> Unit,
    private val onKey: (String) -> Unit,
    private val onExpired: () -> Unit,
) {
    @Volatile var key: String = newKey()
        private set
    @Volatile var port: Int = 0
        private set
    private var ss: ServerSocket? = null
    @Volatile private var closed = false
    private var bad = 0
    private val ui = Handler(Looper.getMainLooper())

    fun start(): Boolean {
        val s = try { ServerSocket(0) } catch (e: Exception) { return false }
        ss = s
        port = s.localPort
        Thread {
            while (!closed) {
                val c = try { s.accept() } catch (e: Exception) { break }
                try { handle(c) } catch (e: Exception) { } finally { try { c.close() } catch (e: Exception) { } }
            }
        }.start()
        ui.postDelayed({ if (!closed) { stop(); onExpired() } }, 10 * 60 * 1000L)
        return true
    }

    fun stop() {
        closed = true
        ui.removeCallbacksAndMessages(null)
        try { ss?.close() } catch (e: Exception) { }
    }

    private fun handle(s: Socket) {
        s.soTimeout = 5000
        val inp = s.getInputStream().buffered()
        fun line(): String? {
            val sb = StringBuilder()
            while (true) {
                val c = inp.read()
                if (c < 0) return if (sb.isEmpty()) null else sb.toString()
                if (c == '\n'.code) return sb.toString().trimEnd('\r')
                if (sb.length > 2048) return null
                sb.append(c.toChar())
            }
        }
        val req = line() ?: return
        var len = 0
        while (true) {
            val h = line() ?: return
            if (h.isEmpty()) break
            if (h.startsWith("content-length:", true)) len = h.substringAfter(':').trim().toIntOrNull() ?: 0
        }
        if (!req.startsWith("POST /pair") || len <= 0 || len > 8192) { reply(s, 400, Txt.s(R.string.tv_bad_request)); return }
        val buf = ByteArray(len)
        var n = 0
        while (n < len) {
            val r = inp.read(buf, n, len - n)
            if (r < 0) break
            n += r
        }
        val j = try { JSONObject(String(buf, 0, n)) } catch (e: Exception) { reply(s, 400, Txt.s(R.string.tv_bad_request)); return }
        if (!MessageDigest.isEqual(j.optString("k").toByteArray(), key.toByteArray())) {
            bad++
            if (bad >= 3) { bad = 0; key = newKey(); ui.post { if (!closed) onKey(key) } }
            reply(s, 403, Txt.s(R.string.tv_bad_key))
            return
        }
        val ticket = j.optString("ticket")
        val arr = j.optJSONArray("server_urls")
        val urls = (0 until (arr?.length() ?: 0)).map { arr!!.optString(it).trim().trimEnd('/') }.filter { it.isNotEmpty() }.distinct()
        var info: ServerInfo? = null
        var url = ""
        for (u in urls) {
            val i = TvApi.serverInfo(u, 3000)
            if (i != null) { info = i; url = u; break }
        }
        if (info == null || ticket.isEmpty()) { reply(s, 502, Txt.s(R.string.tv_no_server)); return }
        when (val r = TvApi.tvClaim(url, ticket, Build.MODEL ?: "TV")) {
            is ClaimResult.Err -> reply(s, 410, r.msg)
            is ClaimResult.Ok -> {
                reply(s, 200, null)
                val done = info
                stop()
                ui.post { onPaired(done, url, r.deviceToken) }
            }
        }
    }

    private fun reply(s: Socket, code: Int, error: String?) {
        val body = (if (error == null) JSONObject().put("ok", true) else JSONObject().put("error", error)).toString().toByteArray()
        val head = "HTTP/1.1 $code ${if (code == 200) "OK" else "Error"}\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n"
        s.getOutputStream().apply { write(head.toByteArray()); write(body); flush() }
    }

    companion object {
        fun newKey(): String = ByteArray(16).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }

        /** IPv4 de rede local (Wi-Fi/Ethernet) da TV; null se estiver sem rede. */
        fun localIp(): String? = try {
            NetworkInterface.getNetworkInterfaces().toList().filter { it.isUp && !it.isLoopback }
                .flatMap { it.inetAddresses.toList() }.firstOrNull { it is Inet4Address && it.isSiteLocalAddress }?.hostAddress
        } catch (e: Exception) {
            null
        }
    }
}
