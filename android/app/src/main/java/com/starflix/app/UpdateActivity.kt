package com.starflix.app

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.ProgressBar
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity

/**
 * 63.6: modal bloqueante de atualização do celular. Não cancelável (Voltar não faz nada); mostra versão instalada → nova, **Atualizar agora**,
 * progresso do download e, se preciso, o ajuste "Instalar apps desconhecidos" ou **Tentar de novo**. Some sozinho quando não há mais versão
 * pendente; com a instalação concluída o Android reinicia o app.
 */
class UpdateActivity : AppCompatActivity() {
    private enum class Mode { START, PERMISSION, RETRY, BUSY }

    private lateinit var base: String
    private lateinit var msg: TextView
    private lateinit var bar: ProgressBar
    private lateinit var btn: Button
    private var mode = Mode.START

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val rel = AppUpdate.pending(this)
        if (rel == null) {
            finish()
            return
        }
        showing = true
        base = intent.getStringExtra(EXTRA_BASE) ?: getSharedPreferences("starflix", MODE_PRIVATE).getString(MainActivity.KEY_URL, "").orEmpty()
        setContentView(R.layout.activity_update)
        findViewById<TextView>(R.id.upVersions).text = getString(R.string.update_versions, AppUpdate.installedName(this), rel.versionName)
        msg = findViewById(R.id.upMsg)
        bar = findViewById(R.id.upBar)
        btn = findViewById(R.id.upBtn)
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() { /* bloqueado: só a atualização */ }
        })
        btn.setOnClickListener {
            when (mode) {
                Mode.PERMISSION -> try { startActivity(AppInstaller.permissionIntent(this)) } catch (e: Exception) { }
                else -> begin()
            }
        }
    }

    override fun onResume() {
        super.onResume()
        if (mode == Mode.PERMISSION && AppInstaller.canInstall(this)) begin()  // voltou dos ajustes com a permissão liberada
    }

    private fun begin() {
        val rel = AppUpdate.pending(this) ?: run { finish(); return }
        mode = Mode.BUSY
        btn.visibility = View.GONE
        bar.visibility = View.VISIBLE
        bar.isIndeterminate = true
        msg.setText(R.string.update_downloading_unknown)
        AppInstaller.start(this, base, rel) { onState(it) }
    }

    private fun onState(s: UpdateState) {
        if (isFinishing || isDestroyed) return
        when (s) {
            is UpdateState.Downloading -> {
                mode = Mode.BUSY
                btn.visibility = View.GONE
                bar.visibility = View.VISIBLE
                if (s.percent < 0) {
                    bar.isIndeterminate = true
                    msg.setText(R.string.update_downloading_unknown)
                } else {
                    bar.isIndeterminate = false
                    bar.progress = s.percent
                    msg.text = getString(R.string.update_downloading, s.percent.toString())
                }
            }
            UpdateState.NeedPermission -> {
                mode = Mode.PERMISSION
                bar.visibility = View.GONE
                msg.setText(R.string.update_permission)
                btn.setText(R.string.update_open_settings)
                btn.visibility = View.VISIBLE
            }
            UpdateState.Installing -> {
                bar.visibility = View.VISIBLE
                bar.isIndeterminate = true
                msg.setText(R.string.update_installing)
            }
            is UpdateState.Failed -> {
                mode = Mode.RETRY
                bar.visibility = View.GONE
                msg.text = s.message
                btn.setText(R.string.retry)
                btn.visibility = View.VISIBLE
            }
        }
    }

    override fun onDestroy() {
        showing = false
        super.onDestroy()
    }

    companion object {
        const val EXTRA_BASE = "base"
        @Volatile private var showing = false

        /** Abre o modal por cima da tela atual (uma só vez). */
        fun launch(ctx: Context, base: String) {
            if (showing) return
            ctx.startActivity(Intent(ctx, UpdateActivity::class.java).putExtra(EXTRA_BASE, base))
        }
    }
}
