package com.starflix.app

import android.content.ContentUris
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.tvprovider.media.tv.TvContractCompat
import androidx.tvprovider.media.tv.WatchNextProgram
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 52.15: linha "Reproduzir a seguir" do launcher da Android TV (WatchNextProgram). Publica o que o servidor devolve em
 * GET /api/tv/watchnext (em andamento e próximo episódio), atualiza os já publicados e remove os que saíram da lista.
 * Bloqueante: rodar fora da thread principal. Só age em TV (leanback) com Android 8+; o resto vira no-op.
 * 52.17: [refresh] e [clearAsync] rodam numa única fila em segundo plano (nunca ao mesmo tempo) e leem o estado (token, perfil,
 * interruptor) na hora de executar, então uma limpeza nunca é desfeita por uma sincronização atrasada.
 */
object TvWatchNext {
    const val AUTHORITY = "com.starflix.app.watchnext"  // StarflixImageProvider (52.16)
    const val DIR = "watchnext"
    private const val REMOVED = -1L  // o usuário tirou este item da linha: não republicar até ele sair da lista do servidor

    fun supported(context: Context): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && context.packageManager.hasSystemFeature(PackageManager.FEATURE_LEANBACK)

    /** Link direto do item (52.16): `starflix://item?type=movie|episode&id=…&play=1`. */
    fun itemLink(type: String, id: Long): Uri = Uri.parse("starflix://item?type=$type&id=$id&play=1")

    /**
     * Sincroniza a linha com o servidor. Devolve false se nada foi feito (sem suporte, sem login, sem permissão ou servidor inacessível).
     * Lança [TvUnauthorized] em 401/403 (token revogado ou perfil apagado) para quem chamou decidir (52.17: apagar tudo).
     */
    fun sync(context: Context, store: TvStore): Boolean {
        if (!supported(context) || store.token.isBlank() || store.profileId <= 0L) return false
        val (code, j) = try {
            TvApi.authed("GET", store.server, "/api/tv/watchnext", store.token, store.profileId)
        } catch (e: TvUnauthorized) {
            throw e
        } catch (e: Exception) {
            return false
        }
        if (code != 200 || j == null) return false
        val arr = j.optJSONArray("items") ?: return false
        return try {
            val resolver = context.contentResolver
            val ids = store.watchNextIds.toMutableMap()
            val seen = HashSet<String>()
            for (n in 0 until arr.length()) {
                val o = arr.getJSONObject(n)
                val key = o.getString("key")
                seen.add(key)
                val known = ids[key]
                if (known == REMOVED) continue
                val poster = downloadImage(context, store, key, o.optString("image"))
                val program = build(o, poster)
                if (known != null) {
                    val rows = resolver.update(TvContractCompat.buildWatchNextProgramUri(known), program.toContentValues(), null, null)
                    if (rows == 0) ids[key] = REMOVED  // sumiu da linha por ação do usuário (ou do sistema)
                } else {
                    val uri = resolver.insert(TvContractCompat.WatchNextPrograms.CONTENT_URI, program.toContentValues())
                    if (uri != null) ids[key] = ContentUris.parseId(uri)
                }
            }
            for ((key, id) in ids.toMap()) {  // saiu da lista (assistido, outro perfil, sem acesso): remove
                if (key in seen) continue
                if (id != REMOVED) resolver.delete(TvContractCompat.buildWatchNextProgramUri(id), null, null)
                ids.remove(key)
            }
            store.watchNextIds = ids
            File(context.cacheDir, DIR).listFiles()?.forEach { f ->  // imagens órfãs
                if (seen.none { fileName(it) == f.name }) f.delete()
            }
            true
        } catch (e: SecurityException) {  // sem WRITE_EPG_DATA (TV que não libera a linha)
            false
        } catch (e: Exception) {
            false
        }
    }

    private val exec = Executors.newSingleThreadScheduledExecutor { r -> Thread(r, "watchnext").apply { isDaemon = true } }
    private val queued = AtomicBoolean(false)

    /**
     * 52.17: atualiza a linha em segundo plano (ao abrir o app, ao voltar do player, ao escolher perfil, ao ligar o interruptor).
     * Interruptor desligado = limpa; 401/403 = apaga tudo. `delayMs` dá tempo de o player gravar a posição antes de ler o servidor.
     * Se já há uma atualização na fila, esta é descartada (a da fila lê o estado mais novo quando rodar).
     */
    fun refresh(context: Context, store: TvStore, delayMs: Long = 0L) {
        if (!supported(context) || !queued.compareAndSet(false, true)) return
        val app = context.applicationContext
        exec.schedule({
            queued.set(false)
            try {
                sync(app, store)
            } catch (e: TvUnauthorized) {
                clear(app, store)
            } catch (e: Exception) {
            }
        }, delayMs, TimeUnit.MILLISECONDS)
    }

    /** 52.17: apaga tudo em segundo plano (trocar de perfil, desconectar a TV, 401/403). */
    fun clearAsync(context: Context, store: TvStore) {
        val app = context.applicationContext
        exec.execute { try { clear(app, store) } catch (e: Exception) { } }
    }

    /** Remove todos os itens do app da linha, apaga as imagens e esquece os ids (bloqueante; use [clearAsync] na interface). */
    fun clear(context: Context, store: TvStore) {
        try {
            if (supported(context)) context.contentResolver.delete(TvContractCompat.WatchNextPrograms.CONTENT_URI, null, null)
        } catch (e: Exception) {
        }
        File(context.cacheDir, DIR).deleteRecursively()
        store.watchNextIds = emptyMap()
    }

    private fun build(o: org.json.JSONObject, poster: Uri?): WatchNextProgram {
        val episode = o.optString("type") == "episode"
        val image = o.optString("image")
        val wide = image.startsWith("/still/") || image.startsWith("/thumb/")
        val b = WatchNextProgram.Builder()
            .setType(if (episode) TvContractCompat.WatchNextPrograms.TYPE_TV_EPISODE else TvContractCompat.WatchNextPrograms.TYPE_MOVIE)
            .setWatchNextType(
                if (o.optString("kind") == "continue") TvContractCompat.WatchNextPrograms.WATCH_NEXT_TYPE_CONTINUE
                else TvContractCompat.WatchNextPrograms.WATCH_NEXT_TYPE_NEXT
            )
            .setLastEngagementTimeUtcMillis(o.optLong("last_played"))
            .setInternalProviderId(o.getString("key"))
            .setIntentUri(itemLink(o.optString("type"), o.getLong("id")))
            .setPosterArtAspectRatio(
                if (wide) TvContractCompat.WatchNextPrograms.ASPECT_RATIO_16_9 else TvContractCompat.WatchNextPrograms.ASPECT_RATIO_2_3
            )
        if (episode) {
            val s = o.optInt("season")
            val e = o.optInt("episode")
            b.setTitle(o.optString("series")).setEpisodeTitle(o.optString("title")).setSeasonNumber(s).setEpisodeNumber(e)
                .setDescription("S$s • E$e")
        } else {
            b.setTitle(o.optString("title"))
        }
        val dur = o.optLong("duration_ms")
        if (dur > 0) {
            b.setDurationMillis(dur.toInt())
            b.setLastPlaybackPositionMillis(o.optLong("position_ms").coerceIn(0L, dur).toInt())
        }
        if (poster != null) b.setPosterArtUri(poster)
        return b.build()
    }

    private fun fileName(key: String) = key.replace(Regex("[^A-Za-z0-9]"), "_") + ".jpg"

    /** Baixa a imagem (com Bearer e X-Profile) para `cacheDir/watchnext/` e devolve a URI do provider; null se falhar (a linha sai sem imagem). */
    private fun downloadImage(context: Context, store: TvStore, key: String, path: String): Uri? {
        if (path.isBlank()) return null
        val dir = File(context.cacheDir, DIR).apply { mkdirs() }
        val name = fileName(key)
        val file = File(dir, name)
        if (!file.exists() || file.length() == 0L) {
            val tmp = File(dir, "$name.tmp")
            val c = URL(store.server + path).openConnection() as HttpURLConnection
            try {
                c.connectTimeout = 5000
                c.readTimeout = 15000
                c.setRequestProperty("Authorization", "Bearer ${store.token}")
                c.setRequestProperty("X-Profile", store.profileId.toString())
                if (c.responseCode != 200) return null
                c.inputStream.use { i -> tmp.outputStream().use { out -> i.copyTo(out) } }
                if (!tmp.renameTo(file)) return null
            } catch (e: Exception) {
                tmp.delete()
                return null
            } finally {
                c.disconnect()
            }
        }
        return Uri.parse("content://$AUTHORITY/$name")
    }
}
