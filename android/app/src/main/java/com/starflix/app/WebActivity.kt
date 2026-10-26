package com.starflix.app

import android.annotation.SuppressLint
import android.content.ClipData
import android.content.Intent
import android.graphics.Bitmap
import android.net.ConnectivityManager
import android.net.Network
import android.net.Uri
import android.os.Bundle
import android.provider.MediaStore
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/** Interface web do servidor (login, perfis, navegação) dentro de um WebView; cookies de sessão persistem. */
class WebActivity : AppCompatActivity() {
    private lateinit var web: WebView
    private lateinit var root: FrameLayout
    private lateinit var error: View
    private var failed = false
    private var httpFailed = false  // a página principal respondeu 4xx/5xx: o corpo cru (JSON/texto) nunca é mostrado, só o modal
    private var sessionRetried = false
    private var baseUrl = ""
    private var errorDialog: AlertDialog? = null
    private var reloadOnResume = false  // true ao abrir o player; recarrega a página ao voltar
    private var customView: View? = null
    private var customCallback: WebChromeClient.CustomViewCallback? = null

    // 54.20: <input type="file"> do site (foto do perfil): galeria/arquivos ou câmera (quando o input tem capture)
    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private var cameraUri: Uri? = null
    private val fileChooser = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        val cb = filePathCallback
        filePathCallback = null
        var out: Array<Uri>? = null
        if (res.resultCode == RESULT_OK) {
            out = WebChromeClient.FileChooserParams.parseResult(res.resultCode, res.data)
            if (out == null) cameraUri?.let { out = arrayOf(it) }  // a câmera grava no Uri combinado e não devolve dados
        }
        cameraUri = null
        cb?.onReceiveValue(out)
    }

    // 58.13/58.16: leitor do QR da TV (`starflix://tvpair?ip&port&k&n`), aberto pelo botão "Ler QR code da TV" da página /tv
    private val tvScan = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        val text = r.data?.getStringExtra(QrScanActivity.EXTRA_TEXT)
        if (r.resultCode == RESULT_OK && text != null) onTvQr(text)
    }

    private fun toast(@androidx.annotation.StringRes id: Int, vararg a: Any) = Toast.makeText(this, getString(id, *a), Toast.LENGTH_LONG).show()

    /** 58.16: valida o QR da TV (IP privado, porta, chave de 128 bits), confirma em modal e entrega o ticket direto ao IP da TV. */
    private fun onTvQr(text: String) {
        val u = try { Uri.parse(text.trim()) } catch (e: Exception) { null }
        val ip = u?.getQueryParameter("ip").orEmpty()
        val port = u?.getQueryParameter("port")?.toIntOrNull() ?: 0
        val k = u?.getQueryParameter("k").orEmpty()
        val name = u?.getQueryParameter("n").orEmpty().ifBlank { "TV" }
        if (u == null || !u.scheme.equals("starflix", true) || u.host != "tvpair" || !TvApi.isPrivateIp(ip) || port !in 1..65535 || !Regex("^[0-9a-f]{32}$").matches(k)) {
            toast(R.string.tv_qr_invalid)
            return
        }
        val st = ServerStore(this)
        val token = st.deviceToken
        val server = st.current.ifBlank { st.urls.firstOrNull().orEmpty() }
        if (token.isEmpty() || server.isEmpty()) { toast(R.string.tv_need_qr); return }
        val urls = (listOf(server) + st.urls).filter { it.isNotBlank() }.distinct()
        val serverName = st.name.ifBlank { server }
        Thread {
            val user = TvApi.phoneMe(server, token)
            runOnUiThread {
                if (user == null) { toast(R.string.tv_fail_server); return@runOnUiThread }
                AlertDialog.Builder(this)
                    .setMessage(getString(R.string.tv_confirm, name, user, serverName))
                    .setNegativeButton(R.string.next_cancel, null)
                    .setPositiveButton(R.string.connect) { _, _ ->
                        Thread {
                            val err = when (val t = TvApi.phoneTvTicket(server, token)) {
                                is ClaimResult.Err -> t.msg
                                is ClaimResult.Ok -> TvApi.sendTvPair(ip, port, k, urls, t.deviceToken)
                            }
                            runOnUiThread { if (err == null) toast(R.string.tv_connected, name) else Toast.makeText(this, err, Toast.LENGTH_LONG).show() }
                        }.start()
                    }
                    .show()
            }
        }.start()
    }

    /** Ponte do site (só páginas do servidor carregam aqui; links externos abrem no navegador). */
    private inner class Bridge {
        @JavascriptInterface
        fun scanTv() {
            runOnUiThread { tvScan.launch(Intent(this@WebActivity, QrScanActivity::class.java)) }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_web)
        hideNavBar()
        root = findViewById(R.id.root)
        web = findViewById(R.id.web)
        error = findViewById(R.id.error)

        val base = getSharedPreferences("starflix", MODE_PRIVATE).getString(MainActivity.KEY_URL, null)
        if (base == null) {
            finish()
            return
        }
        baseUrl = base
        val host = Uri.parse(base).host

        web.addJavascriptInterface(Bridge(), "StarflixApp")
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
        }
        findViewById<View>(R.id.retry).setOnClickListener { reresolve() }  // 58.12: reavalia os endereços (a rede pode ter mudado)
        try { (getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager).registerDefaultNetworkCallback(netCb) } catch (e: Exception) { }
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (request.url.host == host) {
                    val m = WATCH.matchEntire(request.url.path ?: "")
                    if (m == null) return false
                    reloadOnResume = true
                    val start = request.url.getQueryParameter("start")?.toDoubleOrNull()?.toInt()  // ?start=0 = "Do início"
                    startActivity(
                        Intent(this@WebActivity, PlayerActivity::class.java)
                            .putExtra(PlayerActivity.EXTRA_KIND, m.groupValues[1])
                            .putExtra(PlayerActivity.EXTRA_ID, m.groupValues[2].toInt())
                            .apply { if (start != null && start >= 0) putExtra(PlayerActivity.EXTRA_START, start) }
                    )
                    return true
                }
                startActivity(Intent(Intent.ACTION_VIEW, request.url))
                return true
            }

            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                failed = false  // nova carga do frame principal (voltar/navegar): o erro anterior não vale mais
                httpFailed = false
            }

            override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, errorResponse: WebResourceResponse) {
                val code = errorResponse.statusCode
                if (!request.isForMainFrame || code < 400 || request.url.host != host) return  // só a página principal; recursos soltos não contam
                // 58.12: aparelho revogado/inválido: apaga só o token e volta à conexão, mantendo o endereço
                if (request.url.path == "/api/phone/session" && code == 401) {
                    ServerStore(this@WebActivity).deviceToken = ""
                    startActivity(Intent(this@WebActivity, ConnectActivity::class.java).putExtra(ConnectActivity.EXTRA_REVOKED, true))
                    finish()
                    return
                }
                httpFailed = true
                web.visibility = View.GONE  // esconde o corpo cru da resposta (ex.: {"error": ...})
                // sessão perdida com o celular ainda conectado: refaz a sessão do aparelho uma vez, sem incomodar
                if (code == 401 && !sessionRetried && ServerStore(this@WebActivity).deviceToken.isNotEmpty()) {
                    sessionRetried = true
                    openHome()
                    return
                }
                showHttpError(code)
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, err: WebResourceError) {
                if (request.isForMainFrame) {
                    failed = true
                    web.visibility = View.GONE
                    error.visibility = View.VISIBLE
                }
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                CookieManager.getInstance().flush()
                if (!failed && !httpFailed) {
                    sessionRetried = false
                    error.visibility = View.GONE
                    web.visibility = View.VISIBLE
                }
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowCustomView(view: View, callback: CustomViewCallback) {
                customView = view
                customCallback = callback
                root.addView(view, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
                web.visibility = View.GONE
                setFullscreen(true)
            }

            override fun onShowFileChooser(view: WebView, cb: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                filePathCallback?.onReceiveValue(null)
                filePathCallback = cb
                cameraUri = null
                try {
                    val intent = if (params.isCaptureEnabled) {
                        val dir = File(cacheDir, "camera").apply { mkdirs() }
                        val uri = FileProvider.getUriForFile(this@WebActivity, "$packageName.fileprovider", File.createTempFile("foto", ".jpg", dir))
                        cameraUri = uri
                        Intent(MediaStore.ACTION_IMAGE_CAPTURE).putExtra(MediaStore.EXTRA_OUTPUT, uri).apply {
                            clipData = ClipData.newRawUri("", uri)
                            addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        }
                    } else {
                        params.createIntent()
                    }
                    fileChooser.launch(intent)
                } catch (e: Exception) {
                    filePathCallback = null
                    cameraUri = null
                    cb.onReceiveValue(null)
                    return false
                }
                return true
            }

            override fun onHideCustomView() {
                customView?.let { root.removeView(it) }
                customView = null
                customCallback?.onCustomViewHidden()
                customCallback = null
                web.visibility = View.VISIBLE
                setFullscreen(false)
            }
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                when {
                    customView != null -> web.webChromeClient?.onHideCustomView()
                    web.canGoBack() -> web.goBack()
                    else -> finish()
                }
            }
        })

        if (savedInstanceState != null) web.restoreState(savedInstanceState) else openHome()
    }

    /** 58.12: com token de aparelho, a sessão é criada nesta origem (o WebView guarda cookie por origem); sem token, abre o site.
     *  A troca do token pelo cookie é feita aqui, fora do WebView: o resultado (401, erro de rede…) é tratado pelo app e nenhuma resposta crua (JSON) chega à tela. */
    private fun openHome() {
        val t = ServerStore(this).deviceToken
        if (t.isEmpty()) { web.loadUrl(baseUrl); return }
        web.visibility = View.GONE
        Thread {
            var code: Int
            val cookies = mutableListOf<String>()
            try {
                val c = URL("$baseUrl/api/phone/session").openConnection() as HttpURLConnection
                try {
                    c.instanceFollowRedirects = false
                    c.connectTimeout = 5000
                    c.readTimeout = 15000
                    c.setRequestProperty("Authorization", "Bearer $t")
                    code = c.responseCode
                    c.headerFields.filterKeys { it != null && it.equals("Set-Cookie", true) }.values.forEach { cookies.addAll(it) }
                } finally {
                    c.disconnect()
                }
            } catch (e: Exception) {
                code = -1
            }
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                when {
                    code in 300..399 -> {
                        val cm = CookieManager.getInstance()
                        cookies.forEach { cm.setCookie(baseUrl, it) }
                        cm.flush()
                        web.loadUrl(baseUrl)
                    }
                    code == 401 -> {
                        ServerStore(this).deviceToken = ""
                        startActivity(Intent(this, ConnectActivity::class.java).putExtra(ConnectActivity.EXTRA_REVOKED, true))
                        finish()
                    }
                    code == -1 -> {
                        failed = true
                        web.visibility = View.GONE
                        error.visibility = View.VISIBLE
                    }
                    else -> { httpFailed = true; showHttpError(code) }
                }
            }
        }.start()
    }

    /** Erro HTTP da página principal (404, 429, 5xx, sessão negada…): modal em vez da resposta crua. */
    private fun showHttpError(code: Int) {
        if (isFinishing || isDestroyed) return
        errorDialog?.dismiss()
        val msg = when (code) {
            401, 403 -> getString(R.string.http_denied)
            404 -> getString(R.string.http_not_found)
            429 -> getString(R.string.http_too_many)
            in 500..599 -> getString(R.string.http_server_error)
            else -> getString(R.string.http_generic, code)
        }
        val back = {
            httpFailed = false
            if (web.canGoBack()) web.goBack() else openHome()
        }
        errorDialog = AlertDialog.Builder(this)
            .setTitle(R.string.http_error_title)
            .setMessage(msg)
            .setPositiveButton(R.string.retry) { _, _ -> httpFailed = false; openHome() }
            .setNegativeButton(R.string.http_back) { _, _ -> back() }
            .setOnCancelListener { back() }
            .show()
    }

    /** 58.12: troca de rede com a página em erro (ou "Tentar de novo"): volta à porta de entrada, que testa os endereços de novo. */
    private fun reresolve() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }

    private val netCb = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            runOnUiThread { if (failed) reresolve() }
        }
    }

    private fun setFullscreen(on: Boolean) {
        WindowCompat.setDecorFitsSystemWindows(window, !on)
        val c = WindowInsetsControllerCompat(window, window.decorView)
        if (on) {
            c.hide(WindowInsetsCompat.Type.systemBars())
            c.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        } else {
            c.show(WindowInsetsCompat.Type.statusBars())
            hideNavBar()
        }
        fullscreen = on
    }

    private var fullscreen = false

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus && !fullscreen) hideNavBar()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onPause() {
        super.onPause()
        web.onPause()
        CookieManager.getInstance().flush()
    }

    override fun onResume() {
        super.onResume()
        web.onResume()
        if (reloadOnResume) {
            reloadOnResume = false
            if (!failed) web.reload()
        }
    }

    override fun onDestroy() {
        errorDialog?.dismiss()
        try { (getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager).unregisterNetworkCallback(netCb) } catch (e: Exception) { }
        web.destroy()
        super.onDestroy()
    }

    companion object {
        private val WATCH = Regex("/watch/(movie|episode)/(\\d+)")
    }
}
