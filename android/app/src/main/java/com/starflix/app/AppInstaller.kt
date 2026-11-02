package com.starflix.app

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/** 63.5: etapas da atualização, para a tela mostrar (celular 63.6, TV 63.7). */
sealed class UpdateState {
    /** `percent` de 0 a 100; -1 quando o tamanho é desconhecido. */
    data class Downloading(val percent: Int) : UpdateState()
    /** "Instalar apps desconhecidos" não está liberado para o StarFlix: abrir [AppInstaller.permissionIntent] e chamar [AppInstaller.start] ao voltar. */
    object NeedPermission : UpdateState()
    object Installing : UpdateState()
    /** Texto já traduzido; a tela mostra e oferece "Tentar de novo". */
    data class Failed(val message: String) : UpdateState()
}

/**
 * 63.5: baixa o APK de `<servidor>/api/app/apk`, confere tamanho, sha256, pacote e versionCode e instala por `PackageInstaller`.
 * No Android 12 ou mais novo pede `USER_ACTION_NOT_REQUIRED` (atualiza sem confirmar quando o sistema permite); nos demais casos o sistema
 * mostra a confirmação (o [UpdateReceiver] abre). Quando a instalação dá certo o Android reinicia o app. Não precisa de FileProvider:
 * a sessão recebe os bytes direto. O estado chega em `onState` na thread principal.
 */
object AppInstaller {
    const val ACTION = "com.starflix.app.UPDATE_RESULT"
    private val main = Handler(Looper.getMainLooper())
    @Volatile private var busy = false
    @Volatile private var listener: ((UpdateState) -> Unit)? = null
    private val http by lazy { OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).build() }

    private class VerifyException : Exception()

    fun canInstall(ctx: Context): Boolean =
        if (Build.VERSION.SDK_INT >= 26) ctx.applicationContext.packageManager.canRequestPackageInstalls() else true

    /** Tela do sistema onde o usuário libera "Instalar apps desconhecidos" para o StarFlix (a TV pode não ter: quem chama captura a falha). */
    fun permissionIntent(ctx: Context): Intent =
        Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + ctx.packageName)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    fun isBusy(): Boolean = busy

    /** Baixa e instala `release` do servidor `base`; ignora chamada enquanto outra está em andamento. */
    fun start(ctx: Context, base: String, release: AppRelease, onState: (UpdateState) -> Unit) {
        if (busy) return
        busy = true
        listener = onState
        val app = ctx.applicationContext
        Thread {
            try {
                if (!canInstall(app)) {
                    emit(UpdateState.NeedPermission)
                    return@Thread
                }
                val file = try {
                    download(app, base, release)
                } catch (e: VerifyException) {
                    cleanup(app)
                    emit(UpdateState.Failed(Txt.s(R.string.update_err_verify)))
                    return@Thread
                } catch (e: Exception) {
                    cleanup(app)
                    emit(UpdateState.Failed(Txt.s(R.string.update_err_download)))
                    return@Thread
                }
                emit(UpdateState.Installing)
                try {
                    install(app, file)
                } catch (e: Exception) {
                    cleanup(app)
                    emit(UpdateState.Failed(Txt.s(R.string.update_err_install, e.message.orEmpty())))
                }
            } finally {
                busy = false
            }
        }.start()
    }

    private fun emit(s: UpdateState) {
        main.post { listener?.invoke(s) }
    }

    /** Chamado pelo [UpdateReceiver] quando o sistema recusa ou o usuário cancela a instalação. */
    internal fun report(ctx: Context, reason: String) {
        cleanup(ctx)
        emit(UpdateState.Failed(Txt.s(R.string.update_err_install, reason)))
    }

    internal fun cleanup(ctx: Context) {
        File(ctx.applicationContext.cacheDir, "update").listFiles()?.forEach { it.delete() }
    }

    private fun download(ctx: Context, base: String, r: AppRelease): File {
        val dir = File(ctx.cacheDir, "update")
        dir.mkdirs()
        dir.listFiles()?.forEach { it.delete() }
        val part = File(dir, "starflix-${r.versionCode}.apk.part")
        val out = File(dir, "starflix-${r.versionCode}.apk")
        val req = Request.Builder().url(base.trimEnd('/') + "/api/app/apk").build()
        http.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) throw IOException("HTTP " + resp.code)
            val body = resp.body ?: throw IOException("no body")
            val total = if (r.size > 0) r.size else body.contentLength()
            val md = MessageDigest.getInstance("SHA-256")
            var done = 0L
            var last = -2
            body.byteStream().use { ins ->
                part.outputStream().use { os ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = ins.read(buf)
                        if (n < 0) break
                        os.write(buf, 0, n)
                        md.update(buf, 0, n)
                        done += n
                        val pct = if (total > 0) (done * 100 / total).toInt().coerceIn(0, 100) else -1
                        if (pct != last) {
                            last = pct
                            emit(UpdateState.Downloading(pct))
                        }
                    }
                }
            }
            val hex = md.digest().joinToString("") { "%02x".format(it) }
            if ((r.size > 0 && part.length() != r.size) || hex != r.sha256) {
                part.delete()
                throw VerifyException()
            }
        }
        if (!part.renameTo(out)) throw IOException("cannot write file")
        // pacote e versão do arquivo baixado têm de ser os anunciados
        val pm = ctx.packageManager
        val info = (if (Build.VERSION.SDK_INT >= 33) pm.getPackageArchiveInfo(out.path, android.content.pm.PackageManager.PackageInfoFlags.of(0))
        else @Suppress("DEPRECATION") pm.getPackageArchiveInfo(out.path, 0)) ?: throw VerifyException()
        val code = if (Build.VERSION.SDK_INT >= 28) info.longVersionCode.toInt() else @Suppress("DEPRECATION") info.versionCode
        if (info.packageName != ctx.packageName || code != r.versionCode) throw VerifyException()
        return out
    }

    private fun install(ctx: Context, file: File) {
        val pi = ctx.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        params.setAppPackageName(ctx.packageName)
        if (Build.VERSION.SDK_INT >= 31) params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
        val id = pi.createSession(params)
        pi.openSession(id).use { s ->
            file.inputStream().use { ins ->
                s.openWrite("starflix.apk", 0, file.length()).use { os ->
                    ins.copyTo(os)
                    s.fsync(os)
                }
            }
            val intent = Intent(ctx, UpdateReceiver::class.java).setAction(ACTION)
            val flags = PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)
            s.commit(PendingIntent.getBroadcast(ctx, id, intent, flags).intentSender)
        }
    }
}

/** 63.5: resultado da sessão do `PackageInstaller`: abre a confirmação do sistema quando ela é pedida e avisa a tela se falhar ou for cancelada. */
class UpdateReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                val confirm = if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
                else @Suppress("DEPRECATION") intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                if (confirm != null) {
                    confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    ctx.startActivity(confirm)
                }
            }
            PackageInstaller.STATUS_SUCCESS -> AppInstaller.cleanup(ctx)
            else -> AppInstaller.report(ctx, intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE).orEmpty())
        }
    }
}
