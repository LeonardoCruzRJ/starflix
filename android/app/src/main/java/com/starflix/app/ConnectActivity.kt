package com.starflix.app

import android.app.UiModeManager
import android.content.Intent
import android.content.res.Configuration
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.text.Editable
import android.text.TextWatcher
import android.transition.TransitionManager
import android.view.ViewGroup
import android.view.inputmethod.InputMethodManager
import android.widget.ProgressBar
import android.net.Uri
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

/**
 * 58.11: tela de conexão do celular. 1) procura o servidor na rede por NSD (`_starflix._tcp`, ~5 s); 2) lê o QR do site (CameraX);
 * 3) aceita o link colado ou o `starflix://connect?u=<origem>&t=<token>`. Tudo termina no modal "Conectar a <nome> (<endereço>)?"
 * antes do `claim`. O campo de endereço da 58.10 continua como último recurso. A TV não usa NSD/QR aqui (58.14–58.17).
 */
class ConnectActivity : AppCompatActivity() {
    private lateinit var input: EditText
    private lateinit var go: Button
    private lateinit var status: TextView
    private lateinit var nsdText: TextView
    private lateinit var foundBox: LinearLayout
    private lateinit var nsdRow: LinearLayout
    private lateinit var nsdSpin: ProgressBar
    private lateinit var statusRow: LinearLayout
    private lateinit var manualPanel: LinearLayout
    private lateinit var manualToggle: Button
    private lateinit var scroll: ScrollView
    private val ui = Handler(Looper.getMainLooper())
    private val isTv by lazy { (getSystemService(UI_MODE_SERVICE) as UiModeManager).currentModeType == Configuration.UI_MODE_TYPE_TELEVISION }
    private var nsd: NsdManager? = null
    private var discovery: NsdManager.DiscoveryListener? = null
    private val queue = mutableListOf<NsdServiceInfo>()
    private val seen = HashSet<String>()
    private var resolving = false
    private var busy = false

    private val scan = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        val text = r.data?.getStringExtra(QrScanActivity.EXTRA_TEXT)
        if (r.resultCode == RESULT_OK && text != null) handleLink(text)
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun round(color: Int, r: Int, stroke: Int = 0) = GradientDrawable().apply {
        setColor(color)
        cornerRadius = dp(r).toFloat()
        if (stroke != 0) setStroke(dp(1), stroke)
    }

    private fun ripple(bg: GradientDrawable) = RippleDrawable(ColorStateList.valueOf(0x33FFFFFF), bg, null)

    private fun lp(top: Int = 16, h: Int = LinearLayout.LayoutParams.WRAP_CONTENT) =
        LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, h).apply { topMargin = dp(top) }

    private fun button(label: String, filled: Boolean) = Button(this).apply {
        text = label
        isAllCaps = false
        textSize = 16f
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        stateListAnimator = null
        minHeight = 0
        minimumHeight = 0
        setPadding(dp(16), 0, dp(16), 0)
        setTextColor(if (filled) Color.BLACK else Color.WHITE)
        background = ripple(round(if (filled) ACCENT else Color.TRANSPARENT, 14, if (filled) 0 else STROKE_STRONG))
    }

    private fun enable(v: View, on: Boolean) {
        v.isEnabled = on
        v.alpha = if (on) 1f else 0.5f
    }

    private fun label(t: String, sp: Float, color: Int, bold: Boolean = false) = TextView(this).apply {
        text = t
        textSize = sp
        setTextColor(color)
        gravity = Gravity.CENTER
        if (bold) typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = BG_TOP
        window.navigationBarColor = BG_BOTTOM
        val contentW = minOf(resources.displayMetrics.widthPixels - dp(48), dp(420))
        val content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

        val logo = StarflixLogoView(this)
        content.addView(logo, LinearLayout.LayoutParams((contentW * 0.8f).toInt(), LinearLayout.LayoutParams.WRAP_CONTENT).apply { gravity = Gravity.CENTER_HORIZONTAL })
        content.addView(label(getString(R.string.connect_welcome), 24f, Color.WHITE, true), lp(28))
        content.addView(label(getString(R.string.connect_sub), 14f, MUTED), lp(8))

        val banner = label(getString(R.string.connect_revoked), 14f, Color.parseColor("#F3D28A")).apply {
            setPadding(dp(16), dp(14), dp(16), dp(14))
            background = round(0x26E5A00D, 12, 0x66E5A00D)
            visibility = if (intent.getBooleanExtra(EXTRA_REVOKED, false)) View.VISIBLE else View.GONE
        }
        content.addView(banner, lp(20))

        nsdSpin = ProgressBar(this, null, android.R.attr.progressBarStyleSmall).apply { indeterminateTintList = ColorStateList.valueOf(ACCENT) }
        nsdText = label("", 14f, MUTED).apply { setPadding(dp(10), 0, 0, 0) }
        nsdRow = LinearLayout(this).apply {
            gravity = Gravity.CENTER
            addView(nsdSpin, LinearLayout.LayoutParams(dp(18), dp(18)))
            addView(nsdText)
        }
        foundBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

        val scanBtn = button(getString(R.string.connect_scan_cta), true).apply {
            ContextCompat.getDrawable(this@ConnectActivity, R.drawable.ic_qr)?.mutate()?.let {
                it.setTint(Color.BLACK)
                setCompoundDrawablesRelativeWithIntrinsicBounds(it, null, null, null)
                compoundDrawablePadding = dp(10)
            }
            setOnClickListener { scan.launch(Intent(this@ConnectActivity, QrScanActivity::class.java)) }
        }
        val scanHint = label(getString(R.string.connect_scan_where), 12f, MUTED)

        manualToggle = button(getString(R.string.connect_manual), false)
        input = EditText(this).apply {
            hint = getString(R.string.connect_manual_hint)
            setHintTextColor(MUTED)
            setTextColor(Color.WHITE)
            textSize = 16f
            setPadding(dp(16), 0, dp(16), 0)
            background = round(CARD, 12, STROKE)
            setOnFocusChangeListener { v, f -> v.background = round(CARD, 12, if (f) ACCENT else STROKE) }
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            imeOptions = EditorInfo.IME_ACTION_GO
            setSingleLine(true)
            setOnEditorActionListener { _, _, _ -> submitManual(); true }
        }
        go = button(getString(R.string.connect), true).apply { setOnClickListener { submitManual() } }
        manualPanel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            visibility = if (isTv) View.VISIBLE else View.GONE
            addView(label(getString(R.string.connect_manual_help), 12f, MUTED), lp(0))
            addView(input, lp(12, dp(54)))
            addView(go, lp(12, dp(54)))
        }

        status = TextView(this).apply {
            setTextColor(ACCENT)
            textSize = 14f
            setPadding(dp(10), 0, 0, 0)
        }
        statusRow = LinearLayout(this).apply {
            gravity = Gravity.CENTER
            visibility = View.GONE
            addView(ProgressBar(this@ConnectActivity, null, android.R.attr.progressBarStyleSmall).apply { indeterminateTintList = ColorStateList.valueOf(ACCENT) }, LinearLayout.LayoutParams(dp(18), dp(18)))
            addView(status)
        }
        status.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, st: Int, c: Int, a: Int) {}
            override fun onTextChanged(s: CharSequence?, st: Int, b: Int, c: Int) {}
            override fun afterTextChanged(s: Editable?) {
                TransitionManager.beginDelayedTransition(content)
                statusRow.visibility = if (s.isNullOrBlank()) View.GONE else View.VISIBLE
            }
        })

        if (!isTv) {
            content.addView(nsdRow, lp(24))
            content.addView(foundBox, lp(0))
            content.addView(scanBtn, lp(16, dp(54)))
            content.addView(scanHint, lp(10))
            content.addView(manualToggle, lp(20, dp(54)))
            manualToggle.setOnClickListener { toggleManual() }
        }
        content.addView(manualPanel, lp(if (isTv) 24 else 12))
        content.addView(statusRow, lp(16))

        val root = LinearLayout(this).apply {
            gravity = Gravity.CENTER
            setPadding(dp(24), dp(32), dp(24), dp(32))
            addView(content, LinearLayout.LayoutParams(contentW, LinearLayout.LayoutParams.WRAP_CONTENT))
        }
        scroll = ScrollView(this).apply {
            background = GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, intArrayOf(BG_TOP, BG_BOTTOM))
            isFillViewport = true
            addView(root, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        }
        setContentView(scroll)

        val st = ServerStore(this)
        if (st.current.isNotBlank()) input.setText(st.current)  // 58.12: mantém o endereço
        if (savedInstanceState == null) {
            logo.play()
            for (i in 0 until content.childCount) {
                val v = content.getChildAt(i)
                if (v === logo) continue
                v.alpha = 0f
                v.translationY = dp(16).toFloat()
                v.animate().alpha(1f).translationY(0f).setStartDelay(250L + 70L * i).setDuration(380).start()
            }
        }
        if (!isTv) {
            startDiscovery()
            handleIntent(intent)
        }
    }

    /** Mostra/esconde o campo de link ou endereço (só o que o usuário pediu fica na tela). */
    private fun toggleManual() {
        val open = manualPanel.visibility != View.VISIBLE
        TransitionManager.beginDelayedTransition(manualPanel.parent as ViewGroup)
        manualPanel.visibility = if (open) View.VISIBLE else View.GONE
        manualToggle.text = getString(if (open) R.string.connect_manual_hide else R.string.connect_manual)
        if (open) {
            input.requestFocus()
            scroll.postDelayed({ scroll.fullScroll(View.FOCUS_DOWN) }, 250)
            (getSystemService(INPUT_METHOD_SERVICE) as? InputMethodManager)?.showSoftInput(input, InputMethodManager.SHOW_IMPLICIT)
        }
    }

    /** Campo único: link do site/`starflix://connect` vira conexão por token; qualquer outra coisa é tratada como endereço do servidor. */
    private fun submitManual() {
        val raw = input.text.toString().trim()
        if (raw.isEmpty()) return
        if (parseLink(raw) != null) handleLink(raw) else connect()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (!isTv) handleIntent(intent)
    }

    override fun onDestroy() {
        ui.removeCallbacksAndMessages(null)
        stopDiscovery()
        super.onDestroy()
    }

    private fun handleIntent(i: Intent?) {
        if (i?.action == Intent.ACTION_VIEW) i.data?.let { handleLink(it.toString()) }
    }

    /** Link do site (`https://servidor/c/<token>`) ou `starflix://connect?u=…&t=…`; o resto é recusado. */
    private fun parseLink(s: String): Pair<String, String>? {
        val u = try { Uri.parse(s.trim()) } catch (e: Exception) { return null }
        if (u.scheme.equals("starflix", true) && u.host == "connect") {
            val o = u.getQueryParameter("u")?.trim()?.trimEnd('/').orEmpty()
            val t = u.getQueryParameter("t")?.trim().orEmpty()
            val web = o.startsWith("http://", true) || o.startsWith("https://", true)
            return if (web && t.isNotEmpty()) o to t else null
        }
        if (u.scheme.equals("http", true) || u.scheme.equals("https", true)) {
            val seg = u.pathSegments
            val auth = u.authority
            if (auth != null && seg.size == 2 && seg[0] == "c" && seg[1].isNotEmpty()) return "${u.scheme!!.lowercase()}://$auth" to seg[1]
        }
        return null
    }

    /** Erros de conexão sempre em modal (nunca só uma linha de texto na tela). */
    private fun showError(msg: String) {
        if (isFinishing || isDestroyed) return
        status.text = ""
        AlertDialog.Builder(this).setTitle(R.string.connect_error_title).setMessage(msg).setPositiveButton(android.R.string.ok, null).show()
    }

    private fun handleLink(text: String) {
        val p = parseLink(text)
        if (p == null) { showError(getString(R.string.connect_bad_link)); return }
        confirm(p.first, p.second)
    }

    /** Confere o servidor em /api/server-info e abre o modal; `token` nulo = servidor achado na rede (sem claim, segue o login normal). */
    private fun confirm(origin: String, token: String?) {
        if (busy) return
        busy = true
        status.text = getString(R.string.connect_busy)
        Thread {
            val info = TvApi.serverInfo(origin)
            runOnUiThread {
                if (info == null) {
                    busy = false
                    showError(getString(R.string.connect_fail_find))
                    return@runOnUiThread
                }
                status.text = ""
                AlertDialog.Builder(this)
                    .setMessage(getString(R.string.connect_confirm, info.name, origin))
                    .setNegativeButton(R.string.next_cancel) { _, _ -> busy = false }
                    .setPositiveButton(R.string.connect) { _, _ -> claim(info, origin, token) }
                    .setOnCancelListener { busy = false }
                    .show()
            }
        }.start()
    }

    private fun claim(info: ServerInfo, origin: String, token: String?) {
        status.text = getString(R.string.connect_busy)
        Thread {
            var device = ""
            if (token != null) {
                when (val r = TvApi.phoneClaim(origin, token, Build.MODEL ?: "Celular")) {
                    is ClaimResult.Ok -> device = r.deviceToken
                    is ClaimResult.Err -> {
                        runOnUiThread { busy = false; showError(r.msg) }
                        return@Thread
                    }
                }
            }
            runOnUiThread { saveAndOpen(info, origin, device) }
        }.start()
    }

    private fun saveAndOpen(info: ServerInfo, reached: String, device: String) {
        val store = ServerStore(this)
        store.save(info, reached, preferExternal = !isTv)  // celular: grava o endereço externo, não o da rede local por onde foi achado
        if (device.isNotEmpty()) store.deviceToken = device
        if (isTv) {
            val ts = TvStore(this)
            if (ts.server != reached) { ts.clearLogin(); ts.server = reached }
        }
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }

    /** Último recurso (58.10): endereço digitado. */
    private fun connect() {
        val raw = input.text.toString().trim()
        if (raw.isEmpty()) return
        enable(go, false)
        status.text = getString(R.string.connect_busy)
        Thread {
            var found: ServerInfo? = null
            var reached = ""
            for (c in TvApi.candidates(raw)) {
                val info = TvApi.serverInfo(c)
                if (info != null) { found = info; reached = c; break }
            }
            runOnUiThread {
                val info = found
                if (info == null) {
                    showError(getString(R.string.connect_fail_find))
                    enable(go, true)
                } else {
                    saveAndOpen(info, reached, "")
                }
            }
        }.start()
    }

    // ---- NSD (58.11): procura `_starflix._tcp` por ~5 s; cada achado é conferido em /api/server-info antes de aparecer ----

    private fun startDiscovery() {
        val m = getSystemService(NSD_SERVICE) as? NsdManager ?: return
        nsd = m
        nsdText.text = getString(R.string.connect_searching)
        val l = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {}
            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                runOnUiThread { queue.add(serviceInfo); resolveNext() }
            }
            override fun onServiceLost(serviceInfo: NsdServiceInfo) {}
            override fun onDiscoveryStopped(serviceType: String) {}
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {}
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {}
        }
        discovery = l
        try {
            m.discoverServices("_starflix._tcp", NsdManager.PROTOCOL_DNS_SD, l)
        } catch (e: Exception) {
            discovery = null
            searchDone()
            return
        }
        ui.postDelayed({
            stopDiscovery()
            if (foundBox.childCount == 0) searchDone()
        }, 5000)
    }

    private fun searchDone() {
        nsdSpin.visibility = View.GONE
        nsdText.setPadding(0, 0, 0, 0)
        nsdText.text = getString(R.string.connect_none)
    }

    private fun stopDiscovery() {
        val l = discovery ?: return
        discovery = null
        try { nsd?.stopServiceDiscovery(l) } catch (e: Exception) { }
    }

    @Suppress("DEPRECATION")
    private fun resolveNext() {
        if (resolving || queue.isEmpty()) return
        val m = nsd ?: return
        val s = queue.removeAt(0)
        resolving = true
        try {
            m.resolveService(s, object : NsdManager.ResolveListener {
                override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                    runOnUiThread { resolving = false; resolveNext() }
                }
                override fun onServiceResolved(serviceInfo: NsdServiceInfo) {
                    val host = serviceInfo.host?.hostAddress
                    val url = if (host == null) null else "http://${if (host.contains(':')) "[$host]" else host}:${serviceInfo.port}"
                    runOnUiThread { resolving = false; resolveNext() }
                    if (url != null) Thread {
                        val info = TvApi.serverInfo(url)
                        if (info != null && info.mdns) runOnUiThread { addFound(info, url) }
                    }.start()
                }
            })
        } catch (e: Exception) {
            resolving = false
        }
    }

    private fun addFound(info: ServerInfo, url: String) {
        if (!seen.add(info.id.ifEmpty { url })) return
        TransitionManager.beginDelayedTransition(foundBox.parent as ViewGroup)
        nsdRow.visibility = View.GONE
        val dot = View(this).apply { background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(Color.parseColor("#3DDC84")) } }
        val texts = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), 0, dp(12), 0)
            addView(TextView(this@ConnectActivity).apply {
                text = info.name.ifBlank { url }
                setTextColor(Color.WHITE)
                textSize = 16f
                typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
                setSingleLine(true)
                ellipsize = android.text.TextUtils.TruncateAt.END
            })
            addView(TextView(this@ConnectActivity).apply {
                text = getString(R.string.connect_found_sub)
                setTextColor(MUTED)
                textSize = 13f
            })
        }
        val btn = button(getString(R.string.connect), true).apply {
            textSize = 14f
            setOnClickListener { confirm(url, null) }
        }
        val card = LinearLayout(this).apply {
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(16), dp(14), dp(14), dp(14))
            background = ripple(round(CARD, 16, STROKE))
            addView(dot, LinearLayout.LayoutParams(dp(10), dp(10)))
            addView(texts, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            addView(btn, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(40)))
            setOnClickListener { confirm(url, null) }
            alpha = 0f
            animate().alpha(1f).setDuration(300).start()
        }
        foundBox.addView(card, lp(if (foundBox.childCount == 0) 0 else 10))
    }

    companion object {
        const val EXTRA_REVOKED = "revoked"
        private val ACCENT = Color.parseColor("#E5A00D")
        private val BG_TOP = Color.parseColor("#000000")
        private val BG_BOTTOM = Color.parseColor("#15181B")
        private val CARD = Color.parseColor("#1B1E21")
        private val STROKE = Color.parseColor("#2E3236")
        private val STROKE_STRONG = Color.parseColor("#4A4F55")
        private val MUTED = Color.parseColor("#9A9EA3")
    }
}
