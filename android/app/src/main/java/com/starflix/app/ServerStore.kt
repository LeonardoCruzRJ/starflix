package com.starflix.app

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONArray

/** 58.10: servidor do celular, guardado criptografado: endereços (externo + locais), id, nome e token do aparelho. Não há mais endereço fixo no app. */
class ServerStore(context: Context) {
    private val prefs: SharedPreferences = open(context.applicationContext)

    var id: String
        get() = prefs.getString(KEY_ID, "") ?: ""
        set(v) = prefs.edit().putString(KEY_ID, v).apply()

    var name: String
        get() = prefs.getString(KEY_NAME, "") ?: ""
        set(v) = prefs.edit().putString(KEY_NAME, v).apply()

    /** Endereços conhecidos do servidor, o externo primeiro (a 58.12 testa todos e usa o que responder). */
    var urls: List<String>
        get() = try {
            val a = JSONArray(prefs.getString(KEY_URLS, "[]") ?: "[]")
            (0 until a.length()).map { a.getString(it) }.filter { it.isNotBlank() }
        } catch (e: Exception) {
            emptyList()
        }
        set(v) = prefs.edit().putString(KEY_URLS, JSONArray(v).toString()).apply()

    /** Último endereço que respondeu. */
    var current: String
        get() = prefs.getString(KEY_CURRENT, "") ?: ""
        set(v) = prefs.edit().putString(KEY_CURRENT, v).apply()

    /** Token do aparelho (58.5/58.6); vazio quando o app ainda entra pela tela de login do site. */
    var deviceToken: String
        get() = prefs.getString(KEY_TOKEN, "") ?: ""
        set(v) = prefs.edit().putString(KEY_TOKEN, v).apply()

    fun hasServer(): Boolean = urls.isNotEmpty()

    /** Guarda o servidor encontrado; `reached` é o endereço que respondeu. O token só é apagado se for outro servidor.
     *  `preferExternal` (celular): o endereço gravado como atual é o externo do servidor, mesmo que o servidor tenha sido achado na rede local; sem externo configurado, vale `reached`. */
    fun save(info: ServerInfo, reached: String, preferExternal: Boolean = false) {
        if (id.isNotEmpty() && info.id.isNotEmpty() && id != info.id) deviceToken = ""
        id = info.id
        name = info.name
        urls = info.urls
        current = if (preferExternal && info.external.isNotBlank()) info.external else reached
    }

    fun clear() {
        prefs.edit().clear().apply()
    }

    /** Instalação antiga: o endereço salvo em `starflix/server_url` (texto simples) vira o servidor conhecido, sem pedir nada ao usuário. */
    fun migrateLegacy(ctx: Context) {
        if (urls.isNotEmpty()) return
        val old = ctx.getSharedPreferences("starflix", Context.MODE_PRIVATE).getString(MainActivity.KEY_URL, null)?.trim()?.trimEnd('/').orEmpty()
        if (old.isNotEmpty()) {
            urls = listOf(old)
            current = old
        }
    }

    private fun open(ctx: Context): SharedPreferences {
        fun create(): SharedPreferences {
            val key = MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
            return EncryptedSharedPreferences.create(
                ctx, FILE, key,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            )
        }
        return try {
            create()
        } catch (e: Exception) {  // keystore corrompido: recomeça do zero, o app só pede o servidor de novo
            ctx.deleteSharedPreferences(FILE)
            create()
        }
    }

    companion object {
        private const val FILE = "starflix_server"
        private const val KEY_ID = "id"
        private const val KEY_NAME = "name"
        private const val KEY_URLS = "urls"
        private const val KEY_CURRENT = "current"
        private const val KEY_TOKEN = "device_token"
    }
}
