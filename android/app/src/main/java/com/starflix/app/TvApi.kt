package com.starflix.app

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Token revogado ou sessão inválida (401): a TV volta ao pareamento. */
class TvUnauthorized : Exception("Token inválido")

/** 58.10: o que o servidor diz de si mesmo em /api/server-info. */
data class ServerInfo(val id: String, val name: String, val urls: List<String>, val external: String = "", val mdns: Boolean = true)

/** 58.11: resposta de POST /api/phone/claim. */
sealed class ClaimResult {
    data class Ok(val deviceToken: String) : ClaimResult()
    data class Err(val msg: String) : ClaimResult()
}

data class TvProfile(val id: Long, val name: String, val color: String, val photo: String = "")

sealed class ProfilesResult {
    data class Ok(val profiles: List<TvProfile>) : ProfilesResult()
    object Unauthorized : ProfilesResult()
    data class Err(val msg: String) : ProfilesResult()
}

sealed class CodeResult {
    data class Ok(val code: String, val poll: String, val url: String, val expiresIn: Int) : CodeResult()
    data class Err(val msg: String) : CodeResult()
}

sealed class PollResult {
    object Pending : PollResult()
    data class Authorized(val token: String, val deviceId: Long, val name: String) : PollResult()
    object Expired : PollResult()  // vencido, já usado ou desconhecido: pedir outro código
    data class Err(val msg: String) : PollResult()
}

/** Chamadas bloqueantes ao servidor (rodar fora da thread principal). Pareamento da TV: /api/tv/code (40.2). */
object TvApi {
    /** 58.10: dados públicos do servidor (`/api/server-info`): id, nome e endereços (externo primeiro, depois os locais, depois o que respondeu). null se não for um StarFlix. */
    fun serverInfo(server: String, timeoutMs: Int = 5000): ServerInfo? = try {
        val (code, j) = call("GET", "$server/api/server-info", null, timeoutMs, timeoutMs)
        if (code == 200 && j != null && j.optString("app") == "starflix") {
            val list = mutableListOf<String>()
            fun add(s: String?) {
                val t = s?.trim()?.trimEnd('/').orEmpty()
                if (t.isNotEmpty() && t !in list) list.add(t)
            }
            val u = j.optJSONObject("urls")
            add(u?.optString("external"))
            u?.optJSONArray("local")?.let { a -> for (i in 0 until a.length()) add(a.optString(i)) }
            add(server)
            ServerInfo(j.optString("id"), j.optString("name", "StarFlix").ifBlank { "StarFlix" }, list, u?.optString("external")?.trim()?.trimEnd('/').orEmpty(), j.optBoolean("mdns", true))
        } else {
            null
        }
    } catch (e: Exception) {
        null
    }

    /** 58.11: troca o token do QR/link (uso único) pelo token do aparelho. */
    fun phoneClaim(server: String, token: String, name: String): ClaimResult = try {
        val (code, j) = call("POST", "$server/api/phone/claim", JSONObject().put("token", token).put("name", name).toString())
        val dev = j?.optString("device_token").orEmpty()
        if (code == 200 && dev.isNotEmpty()) ClaimResult.Ok(dev)
        else ClaimResult.Err(j?.optString("error").orEmpty().ifBlank { Txt.s(R.string.tv_claim_qr_fail, code) })
    } catch (e: Exception) {
        ClaimResult.Err(Txt.s(R.string.tv_server_unreachable))
    }

    /** 58.15: troca o ticket (dado pelo celular) pelo token da TV em `POST /api/tv/claim`. */
    fun tvClaim(server: String, ticket: String, name: String): ClaimResult = try {
        val (code, j) = call("POST", "$server/api/tv/claim", JSONObject().put("ticket", ticket).put("name", name).toString())
        val t = j?.optString("token").orEmpty()
        if (code == 200 && t.isNotEmpty()) ClaimResult.Ok(t)
        else ClaimResult.Err(j?.optString("error").orEmpty().ifBlank { Txt.s(R.string.tv_claim_ticket_fail, code) })
    } catch (e: Exception) {
        ClaimResult.Err(Txt.s(R.string.tv_server_unreachable))
    }

    /** 58.16: IPv4 de rede privada (10/8, 172.16/12, 192.168/16, link-local); o app só fala em texto claro com a TV nesses endereços. */
    fun isPrivateIp(ip: String): Boolean {
        val p = ip.split(".").mapNotNull { it.toIntOrNull() }
        if (p.size != 4 || ip.split(".").size != 4 || p.any { it !in 0..255 }) return false
        return p[0] == 10 || (p[0] == 172 && p[1] in 16..31) || (p[0] == 192 && p[1] == 168) || (p[0] == 169 && p[1] == 254)
    }

    /** 58.16: nome da conta do aparelho (`GET /api/phone/me`); null se o servidor não respondeu ou o aparelho foi revogado. */
    fun phoneMe(server: String, deviceToken: String): String? = try {
        val (code, j) = authed("GET", server, "/api/phone/me", deviceToken)
        if (code == 200) j?.optString("user")?.takeIf { it.isNotBlank() } else null
    } catch (e: Exception) {
        null
    }

    /** 58.16: ticket de 5 min para entregar à TV (`POST /api/phone/tv-ticket`). */
    fun phoneTvTicket(server: String, deviceToken: String): ClaimResult = try {
        val (code, j) = authed("POST", server, "/api/phone/tv-ticket", deviceToken)
        val t = j?.optString("ticket").orEmpty()
        if (code == 200 && t.isNotEmpty()) ClaimResult.Ok(t) else ClaimResult.Err(j?.optString("error").orEmpty().ifBlank { Txt.s(R.string.tv_ticket_fail, code) })
    } catch (e: TvUnauthorized) {
        ClaimResult.Err(Txt.s(R.string.tv_phone_revoked))
    } catch (e: Exception) {
        ClaimResult.Err(Txt.s(R.string.tv_server_unreachable))
    }

    /** 58.16: entrega o ticket ao mini servidor da TV (`POST http://ip:porta/pair`, 5 s para conectar). null = a TV aceitou; senão, a mensagem de erro. */
    fun sendTvPair(ip: String, port: Int, key: String, serverUrls: List<String>, ticket: String): String? = try {
        val body = JSONObject().put("k", key).put("ticket", ticket).put("server_urls", org.json.JSONArray(serverUrls)).toString()
        val (code, j) = call("POST", "http://$ip:$port/pair", body, 5000, 20000)
        if (code == 200) null else j?.optString("error").orEmpty().ifBlank { Txt.s(R.string.tv_refused, code) }
    } catch (e: Exception) {
        Txt.s(R.string.tv_talk_fail)
    }

    /** true quando o último [TvUnauthorized] foi perfil inválido (403) e não token revogado (401). */
    @Volatile var badProfile = false

    /** Desconecta esta TV no servidor (apaga o aparelho do token); falha é ignorada, o token local é apagado de qualquer jeito. */
    fun logout(server: String, token: String) {
        try {
            authed("POST", server, "/api/tv/logout", token, 0L)
        } catch (e: Exception) {
        }
    }

    private fun call(method: String, url: String, body: String? = null, connectMs: Int = 5000, readMs: Int = 8000): Pair<Int, JSONObject?> {
        val c = URL(url).openConnection() as HttpURLConnection
        try {
            c.requestMethod = method
            c.connectTimeout = connectMs
            c.readTimeout = readMs
            if (body != null) {
                c.doOutput = true
                c.setRequestProperty("Content-Type", "application/json")
                c.outputStream.use { it.write(body.toByteArray()) }
            }
            val code = c.responseCode
            val text = (if (code >= 400) c.errorStream else c.inputStream)?.bufferedReader()?.readText().orEmpty()
            return code to try { JSONObject(text) } catch (e: Exception) { null }
        } finally {
            c.disconnect()
        }
    }

    /**
     * 57.9: endereços a testar para o que foi digitado. Com `http://` ou `https://` vale só ele; sem esquema, nome de domínio tenta
     * `https` e depois `http`, e IP, `localhost`, `.local`/`.lan` ou endereço com porta tentam `http` e depois `https`.
     */
    fun candidates(raw: String): List<String> {
        val t = raw.trim().replace(" ", "").trimEnd('/')
        val m = Regex("^(https?)://(.*)$", RegexOption.IGNORE_CASE).find(t)
        if (m != null) return listOf(m.groupValues[1].lowercase() + "://" + m.groupValues[2].trimEnd('/'))
        val hostPort = t.substringBefore('/')
        val host = hostPort.substringBefore(':')
        val local = Regex("^\\d{1,3}(\\.\\d{1,3}){3}$").matches(host) || host == "localhost" ||
            host.endsWith(".local") || host.endsWith(".lan") || hostPort.contains(':')
        return if (local) listOf("http://$t", "https://$t") else listOf("https://$t", "http://$t")
    }

    fun normalize(raw: String): String = candidates(raw).first()

    /** Primeiro endereço candidato em que o servidor responde em /health; null se nenhum responder. */
    fun resolve(raw: String): String? = candidates(raw).firstOrNull { health(it) }

    /** O servidor responde `{"status":"ok"}` em /health. */
    fun health(server: String): Boolean = try {
        val (code, json) = call("GET", "$server/health")
        code == 200 && json?.optString("status") == "ok"
    } catch (e: Exception) {
        false
    }

    fun requestCode(server: String, deviceName: String): CodeResult = try {
        val (code, j) = call("POST", "$server/api/tv/code", JSONObject().put("name", deviceName).toString())
        when {
            code == 200 && j != null -> CodeResult.Ok(j.getString("code"), j.getString("poll"), j.optString("url", "$server/tv"), j.optInt("expires_in", 600))
            code == 429 -> CodeResult.Err(Txt.s(R.string.tv_too_many))
            else -> CodeResult.Err(Txt.s(R.string.tv_code_fail))
        }
    } catch (e: Exception) {
        CodeResult.Err(Txt.s(R.string.tv_server_unreachable))
    }

    fun poll(server: String, poll: String): PollResult = try {
        val (code, j) = call("GET", "$server/api/tv/code/$poll")
        when {
            code == 200 && j?.optString("status") == "authorized" ->
                PollResult.Authorized(j.getString("token"), j.optLong("device_id"), j.optString("name"))
            code == 200 -> PollResult.Pending
            code == 410 || code == 404 -> PollResult.Expired
            code == 429 -> PollResult.Err(Txt.s(R.string.tv_too_many_polls))
            else -> PollResult.Err(Txt.s(R.string.tv_server_error, code))
        }
    } catch (e: Exception) {
        PollResult.Err(Txt.s(R.string.tv_server_unreachable))
    }

    /** Chamada autenticada (Bearer + X-Profile). 401 vira [TvUnauthorized]; demais erros HTTP voltam como código + JSON. */
    fun authed(method: String, server: String, path: String, token: String, profileId: Long = 0L, body: String? = null): Pair<Int, JSONObject?> {
        val c = URL(server + path).openConnection() as HttpURLConnection
        try {
            c.requestMethod = method
            c.connectTimeout = 5000
            c.readTimeout = 15000
            c.setRequestProperty("Authorization", "Bearer $token")
            if (profileId > 0) c.setRequestProperty("X-Profile", profileId.toString())
            if (body != null) {
                c.doOutput = true
                c.setRequestProperty("Content-Type", "application/json")
                c.outputStream.use { it.write(body.toByteArray()) }
            }
            val code = c.responseCode
            if (code == 401) { badProfile = false; throw TvUnauthorized() }
            if (code == 403 && profileId > 0) { badProfile = true; throw TvUnauthorized() }  // perfil apagado: volta à escolha de perfil, o token segue valendo
            val text = (if (code >= 400) c.errorStream else c.inputStream)?.bufferedReader()?.readText().orEmpty()
            return code to try { JSONObject(text) } catch (e: Exception) { null }
        } finally {
            c.disconnect()
        }
    }

    /** GET /api/tv/profiles (não exige X-Profile). */
    fun profiles(server: String, token: String): ProfilesResult = try {
        val (code, j) = authed("GET", server, "/api/tv/profiles", token)
        if (code == 200 && j != null) {
            val a = j.optJSONArray("profiles")
            val list = (0 until (a?.length() ?: 0)).map { i ->
                val o = a!!.getJSONObject(i)
                TvProfile(o.getLong("id"), o.optString("name"), o.optString("avatar", "#e5a00d"), if (o.isNull("photo")) "" else o.optString("photo"))
            }
            ProfilesResult.Ok(list)
        } else ProfilesResult.Err(Txt.s(R.string.tv_server_error, code))
    } catch (e: TvUnauthorized) {
        ProfilesResult.Unauthorized
    } catch (e: Exception) {
        ProfilesResult.Err(Txt.s(R.string.tv_server_unreachable))
    }

    /** POST /api/tv/profile/<id>: valida que o perfil é do usuário do token. */
    fun pickProfile(server: String, token: String, id: Long): Boolean? = try {
        val (code, _) = authed("POST", server, "/api/tv/profile/$id", token)
        code == 200
    } catch (e: TvUnauthorized) {
        null  // token revogado
    } catch (e: Exception) {
        false
    }
}
