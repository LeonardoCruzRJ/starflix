package com.starflix.app

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONObject

/** Dados da TV guardados criptografados (EncryptedSharedPreferences): servidor, token do aparelho e perfil escolhido. */
class TvStore(context: Context) {
    private val prefs: SharedPreferences = open(context.applicationContext)

    var server: String
        get() = prefs.getString(KEY_SERVER, "") ?: ""
        set(v) = prefs.edit().putString(KEY_SERVER, v).apply()

    var token: String
        get() = prefs.getString(KEY_TOKEN, "") ?: ""
        set(v) = prefs.edit().putString(KEY_TOKEN, v).apply()

    var profileId: Long
        get() = prefs.getLong(KEY_PROFILE, 0L)
        set(v) = prefs.edit().putLong(KEY_PROFILE, v).apply()

    var profileName: String
        get() = prefs.getString(KEY_PNAME, "") ?: ""
        set(v) = prefs.edit().putString(KEY_PNAME, v).apply()

    var profileColor: String
        get() = prefs.getString(KEY_PCOLOR, "") ?: ""
        set(v) = prefs.edit().putString(KEY_PCOLOR, v).apply()

    var profilePhoto: String
        get() = prefs.getString(KEY_PPHOTO, "") ?: ""
        set(v) = prefs.edit().putString(KEY_PPHOTO, v).apply()

    /** 52.15: `key` do item (`movie:<id>` / `episode:<id>`) -> id do WatchNextProgram publicado (-1 = o usuário removeu da linha). */
    var watchNextIds: Map<String, Long>
        get() = try {
            val o = JSONObject(prefs.getString(KEY_WN, "{}") ?: "{}")
            o.keys().asSequence().associateWith { o.getLong(it) }
        } catch (e: Exception) {
            emptyMap()
        }
        set(v) = prefs.edit().putString(KEY_WN, JSONObject(v).toString()).apply()


    /** Apaga o token e o perfil (TV desconectada ou token revogado); o servidor fica salvo. */
    fun clearLogin() {
        prefs.edit().remove(KEY_TOKEN).remove(KEY_PROFILE).remove(KEY_PNAME).remove(KEY_PCOLOR).remove(KEY_PPHOTO).apply()
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
        } catch (e: Exception) {  // keystore corrompido (acontece em algumas TVs): recomeça do zero, a TV só pareia de novo
            ctx.deleteSharedPreferences(FILE)
            create()
        }
    }

    companion object {
        private const val FILE = "starflix_tv"
        private const val KEY_SERVER = "server"
        private const val KEY_TOKEN = "token"
        private const val KEY_PROFILE = "profile"
        private const val KEY_PNAME = "profile_name"
        private const val KEY_PCOLOR = "profile_color"
        private const val KEY_PPHOTO = "profile_photo"
        private const val KEY_WN = "watchnext_ids"
    }
}
