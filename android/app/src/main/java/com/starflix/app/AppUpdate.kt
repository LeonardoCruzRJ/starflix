package com.starflix.app

import android.content.Context
import android.content.SharedPreferences
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.os.Build
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** 63.4: versão publicada pelo servidor em `apk/version.json` (via `/api/app/version`). */
data class AppRelease(val versionCode: Int, val versionName: String, val size: Long, val sha256: String)

/** Resultado de uma consulta ao servidor: versão publicada, nada publicado ou servidor inalcançável. */
sealed class ReleaseFetch {
    data class Found(val release: AppRelease) : ReleaseFetch()
    object None : ReleaseFetch()
    object Offline : ReleaseFetch()
}

/**
 * 63.4: atualização do próprio app (celular e TV usam o mesmo APK). Consulta `GET <servidor>/api/app/version` (pública) e compara o
 * `versionCode` com o instalado. A versão **pendente** fica gravada em SharedPreferences: o aviso volta ao fechar e abrir o app,
 * mesmo sem rede, até o instalado alcançar a versão pendente (ou o servidor deixar de publicar APK). Chamadas de rede bloqueiam:
 * rodar fora da thread principal.
 */
object AppUpdate {
    private const val PREFS = "starflix_update"
    private const val K_CODE = "pending_code"
    private const val K_NAME = "pending_name"
    private const val K_SIZE = "pending_size"
    private const val K_SHA = "pending_sha"
    private const val K_LAST = "last_check"

    private fun prefs(ctx: Context): SharedPreferences = ctx.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    private fun info(ctx: Context): PackageInfo? = try {
        val pm = ctx.applicationContext.packageManager
        if (Build.VERSION.SDK_INT >= 33) pm.getPackageInfo(ctx.packageName, PackageManager.PackageInfoFlags.of(0))
        else @Suppress("DEPRECATION") pm.getPackageInfo(ctx.packageName, 0)
    } catch (e: Exception) {
        null
    }

    /** versionCode do app instalado. */
    fun installedCode(ctx: Context): Int {
        val i = info(ctx) ?: return 0
        return if (Build.VERSION.SDK_INT >= 28) i.longVersionCode.toInt() else @Suppress("DEPRECATION") i.versionCode
    }

    /** versionName do app instalado (ex.: 1.0.724). */
    fun installedName(ctx: Context): String = info(ctx)?.versionName.orEmpty()

    /** Versão pendente gravada, ou null (também apaga a gravação se o instalado já a alcançou). */
    fun pending(ctx: Context): AppRelease? {
        val p = prefs(ctx)
        val code = p.getInt(K_CODE, 0)
        if (code <= 0) return null
        if (code <= installedCode(ctx)) {
            clear(ctx)
            return null
        }
        return AppRelease(code, p.getString(K_NAME, "").orEmpty(), p.getLong(K_SIZE, 0L), p.getString(K_SHA, "").orEmpty())
    }

    fun hasPending(ctx: Context): Boolean = pending(ctx) != null

    fun clear(ctx: Context) {
        prefs(ctx).edit().remove(K_CODE).remove(K_NAME).remove(K_SIZE).remove(K_SHA).apply()
    }

    private fun save(ctx: Context, r: AppRelease) {
        prefs(ctx).edit().putInt(K_CODE, r.versionCode).putString(K_NAME, r.versionName).putLong(K_SIZE, r.size).putString(K_SHA, r.sha256).apply()
    }

    /** Pergunta ao servidor (`base` = endereço, ex.: http://192.168.0.10:32000). */
    fun fetch(base: String, timeoutMs: Int = 5000): ReleaseFetch {
        return try {
            val c = URL(base.trimEnd('/') + "/api/app/version").openConnection() as HttpURLConnection
            c.connectTimeout = timeoutMs
            c.readTimeout = timeoutMs
            c.requestMethod = "GET"
            try {
                if (c.responseCode != 200) return ReleaseFetch.Offline
                val j = JSONObject(c.inputStream.bufferedReader().use { it.readText() })
                if (!j.optBoolean("available", false)) return ReleaseFetch.None
                val code = j.optInt("versionCode", 0)
                val sha = j.optString("sha256").lowercase()
                if (code <= 0 || sha.length != 64) ReleaseFetch.None
                else ReleaseFetch.Found(AppRelease(code, j.optString("versionName"), j.optLong("size", 0L), sha))
            } finally {
                c.disconnect()
            }
        } catch (e: Exception) {
            ReleaseFetch.Offline
        }
    }

    /**
     * Consulta e atualiza a versão pendente: publicada e maior que a instalada = grava; publicada e já instalada, ou nada publicado = apaga;
     * servidor fora do ar = mantém o que estava gravado. Devolve a versão pendente (null = nada a atualizar).
     */
    fun check(ctx: Context, base: String): AppRelease? {
        when (val r = fetch(base)) {
            is ReleaseFetch.Found -> if (r.release.versionCode > installedCode(ctx)) save(ctx, r.release) else clear(ctx)
            ReleaseFetch.None -> clear(ctx)
            ReleaseFetch.Offline -> Unit
        }
        prefs(ctx).edit().putLong(K_LAST, System.currentTimeMillis()).apply()
        return pending(ctx)
    }

    /** Só consulta se a última consulta foi há mais de `minIntervalMs`; senão devolve o que está gravado. */
    fun checkIfDue(ctx: Context, base: String, minIntervalMs: Long): AppRelease? {
        val last = prefs(ctx).getLong(K_LAST, 0L)
        return if (System.currentTimeMillis() - last >= minIntervalMs) check(ctx, base) else pending(ctx)
    }
}
