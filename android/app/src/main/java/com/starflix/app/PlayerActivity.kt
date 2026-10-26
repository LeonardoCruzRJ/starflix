package com.starflix.app

import android.media.MediaCodecInfo
import android.media.MediaCodecList
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Display
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.CookieManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.widget.ImageView
import android.widget.SeekBar
import android.widget.TextView
import androidx.annotation.OptIn
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.audio.AudioCapabilities
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URLEncoder
import java.net.URL
import kotlin.concurrent.thread

private class Cue(val start: Double, val end: Double, val text: String)

/** Player nativo (ExoPlayer) com troca de faixa de áudio (nova sessão no servidor) e legendas .vtt desenhadas por cima. */
@OptIn(UnstableApi::class)
class PlayerActivity : AppCompatActivity() {
    private lateinit var view: PlayerView
    private lateinit var error: TextView
    private lateinit var subtitle: TextView
    private lateinit var mOverlay: View           // 55.2: controles do celular
    private lateinit var mTitle: TextView
    private lateinit var mSub: TextView
    private lateinit var mElapsed: TextView
    private lateinit var mRemain: TextView
    private lateinit var mSeek: SeekBar
    private lateinit var mBtnPlay: ImageView
    private lateinit var mBtnPrev: ImageView
    private lateinit var mBtnNext: ImageView
    private lateinit var mBtnQueue: ImageView
    private var lockLand = true                   // 55.7: bloquear em paisagem (padrão ligado; guardado no aparelho)
    private var fitMode = 0                       // 55.7: 0 Letterbox (FIT), 1 Preencher (ZOOM), 2 Esticar (FILL)
    private var timerMin = 0                      // 55.7: temporizador: 0 desativado, N min, -1 ao fim do episódio (só desta sessão)
    private var backCbRef: OnBackPressedCallback? = null
    private var sheet: PlayerSheet? = null         // 55.3: folha inferior (celular)
    private var prevId = 0                        // 55.1: episódio anterior/seguinte da série (0 = não há)
    private var nextId = 0
    private var player: ExoPlayer? = null
    private val handler = Handler(Looper.getMainLooper())

    private lateinit var base: String
    private lateinit var kind: String
    private var itemId = -1
    private var hlsRetried = false               // sessão HLS expirou no servidor (TTL): recarrega uma vez; zera ao voltar a tocar
    private var forceHls = false                 // direct play falhou: usa HLS (?mode=hls) daqui em diante neste item
    private var safe = false                     // 52.4: direct/remux por `caps` falhou: repete uma vez com transcode completo (?mode=safe)
    private var capsUsed = false
    private var startOverride = -1                // segundo inicial vindo da página (?start=); -1 = retomar da posição salva
    private var cookie = ""
    private var tv = false                        // aberto pela TV: Bearer + X-Profile no lugar do cookie, controle remoto (40.14)
    private var tvToken = ""
    private var tvProfile = 0L
    // 57.22: marcadores do episódio (/api/tv/markers): botões Pular abertura e Próximo Episódio no canto inferior direito
    private lateinit var btnSkipIntro: TextView
    private lateinit var btnNextEp: TextView
    private lateinit var btnNextCancel: TextView
    private var autoNext = true       // preferência do perfil: contagem de 10 s no Próximo Episódio
    private var ncLeft = 10_000L
    private var ncAt = 0L
    private var introS = -1.0
    private var introE = -1.0
    private var creditsS = -1.0
    private var skipPref = "ask"
    private var introDone = false
    private var introHidden = false
    private var nextHidden = false
    private lateinit var tvOverlay: View           // 42.3: tela de controles da TV
    private lateinit var tvTitle: TextView
    private lateinit var tvSub: TextView
    private lateinit var tvClock: TextView
    private lateinit var tvElapsed: TextView
    private lateinit var tvRemain: TextView
    private lateinit var tvSeek: TvSeekView
    private lateinit var tvBtnPlay: android.widget.ImageView
    private lateinit var tvBtnSubs: View
    private lateinit var tvBtnSettings: View
    private lateinit var tvQueueHint: TextView      // 57.13: "▼ Próximos episódios" sob a barra de tempo
    private var tvFocus = 0                       // 0 = fora (padrão), 1 = ícone de legenda, 2 = ícone de ajustes, 3 = barra de tempo (bolinha visível)
    private var tvBarPending = false              // 43.7: bolinha movida na barra, ainda não aplicada com OK
    private var tvSeekTarget: Double? = null      // soma das setas ←/→ ainda não aplicada (aplica 600 ms depois da última tecla)

    private var sid: String? = null
    private var loadToken = 0                     // identifica a última carga; respostas de cargas antigas são descartadas
    private var offset = 0.0                      // segundo absoluto onde a sessão atual começa
    private var audioIndex: Int? = null           // índice ffprobe pedido ao servidor
    private var audioTracks = listOf<Pair<Int, String>>()
    private var audioChecked = 0
    private var quality: String? = null           // 55.6: null = Original; senão 1080p/720p/480p (?quality=)
    private var qualityList = listOf<Triple<String, String, String>>()  // id, rótulo, "N Mbps (Cerca de X MB por hora)"
    private var subTracks = listOf<Pair<String, String>>()  // rótulo, url
    private var subChecked = -1                   // -1 = desativadas
    private var cues = listOf<Cue>()
    private var tracksLoaded = false

    private fun updateTrackButtons() {
        val v = if (tracksLoaded) View.VISIBLE else View.INVISIBLE
        findViewById<View>(R.id.mBtnSubs).visibility = v
        findViewById<View>(R.id.mBtnSettings).visibility = v
    }

    private var duration = 0.0                    // duração total (s), vinda do ffprobe do servidor
    private var lastSave = 0L
    private var loading = true                    // true enquanto uma sessão nova está sendo pedida
    private var ending = false
    private var hls = false                       // sessão HLS: o ExoPlayer só enxerga o trecho já gerado
    private var dragging = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_player)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
        view = findViewById(R.id.playerView)
        error = findViewById(R.id.error)
        subtitle = findViewById(R.id.subtitle)
        applySubStyle("m", "white", "shadow", "mid")
        mOverlay = findViewById(R.id.mOverlay)
        mTitle = findViewById(R.id.mTitle)
        mSub = findViewById(R.id.mSub)
        mElapsed = findViewById(R.id.mElapsed)
        mRemain = findViewById(R.id.mRemain)
        mSeek = findViewById(R.id.mSeek)
        mBtnPlay = findViewById(R.id.mBtnPlay)
        mBtnPrev = findViewById(R.id.mBtnPrev)
        mBtnNext = findViewById(R.id.mBtnNext)
        mBtnQueue = findViewById(R.id.mBtnQueue)
        tvOverlay = findViewById(R.id.tvOverlay)
        btnSkipIntro = findViewById(R.id.btnSkipIntro)
        btnNextEp = findViewById(R.id.btnNextEp)
        btnNextCancel = findViewById(R.id.btnNextCancel)
        btnNextCancel.setOnClickListener { nextHidden = true; showMark(false, false) }
        btnSkipIntro.setOnClickListener { doSkipIntro() }
        btnNextEp.setOnClickListener { doNextEp() }
        tvTitle = findViewById(R.id.tvTitle)
        tvSub = findViewById(R.id.tvSub)
        tvClock = findViewById(R.id.tvClock)
        tvElapsed = findViewById(R.id.tvElapsed)
        tvRemain = findViewById(R.id.tvRemain)
        tvSeek = findViewById(R.id.tvSeek)
        tvBtnPlay = findViewById(R.id.tvBtnPlay)
        tvBtnSubs = findViewById(R.id.tvBtnSubs)
        tvBtnSettings = findViewById(R.id.tvBtnSettings)
        tvQueueHint = findViewById(R.id.tvQueueHint)

        val k = intent.getStringExtra(EXTRA_KIND)
        itemId = intent.getIntExtra(EXTRA_ID, -1)
        startOverride = intent.getIntExtra(EXTRA_START, -1)
        tv = intent.getBooleanExtra(EXTRA_TV, false)
        tvToken = intent.getStringExtra(EXTRA_TOKEN).orEmpty()
        tvProfile = intent.getLongExtra(EXTRA_PROFILE, 0L)
        val saved = if (tv) intent.getStringExtra(EXTRA_SERVER) else getSharedPreferences("starflix", MODE_PRIVATE).getString(MainActivity.KEY_URL, null)
        if (k == null || itemId < 0 || saved == null) {
            finish()
            return
        }
        kind = k
        base = saved
        cookie = if (tv) "" else CookieManager.getInstance().getCookie(base) ?: ""
        loadSubStyle()  // 57.29
        view.useController = false  // 55.2: celular com controles próprios (mOverlay); TV com as teclas do controle remoto
        if (!tv) {
            val sp = getSharedPreferences("starflix", MODE_PRIVATE)
            lockLand = sp.getBoolean("pl_lock", true)
            fitMode = sp.getInt("pl_fit", 0).coerceIn(0, 2)
            applyOrientation()
            applyFit()
            view.setOnClickListener { if (mOverlay.visibility == View.VISIBLE) hideM() else showM() }
            mOverlay.setOnClickListener { hideM() }
            mSeek.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(sb: SeekBar, progress: Int, fromUser: Boolean) {
                    if (fromUser && duration > 0) {
                        val t = progress / 1000.0 * duration
                        mElapsed.text = fmt(t)
                        mRemain.text = "-" + fmt(duration - t)
                    }
                }

                override fun onStartTrackingTouch(sb: SeekBar) {
                    dragging = true
                    handler.removeCallbacks(hideMRun)
                }

                override fun onStopTrackingTouch(sb: SeekBar) {
                    dragging = false
                    if (duration > 0) seekTo(sb.progress / 1000.0 * duration)
                    showM()
                }
            })
            mBtnPlay.setOnClickListener { val p = player; if (p != null) { if (p.isPlaying) p.pause() else p.play() }; updateMPlay(); showM() }
            mBtnPrev.setOnClickListener { if (prevId > 0) { save(); switchTo(prevId) } }
            mBtnNext.setOnClickListener { if (nextId > 0) { save(); switchTo(nextId) } }
            findViewById<View>(R.id.mBtnClose).setOnClickListener { finish() }
            if (pipSupported()) findViewById<View>(R.id.mBtnPip).apply { visibility = View.VISIBLE; setOnClickListener { enterPip() } }
            findViewById<View>(R.id.mBtnSubs).setOnClickListener { openSubsSheet() }
            findViewById<View>(R.id.mBtnSettings).setOnClickListener { openSettingsSheet() }
            updateTrackButtons()
            val backCb = object : OnBackPressedCallback(false) { override fun handleOnBackPressed() { if (queueIsOpen()) closeQueue() else sheet?.back() } }
            backCbRef = backCb
            onBackPressedDispatcher.addCallback(this, backCb)
            findViewById<View>(R.id.queueRoot).setOnClickListener { closeQueue() }
            findViewById<View>(R.id.queueClose).setOnClickListener { closeQueue() }
            mBtnQueue.setOnClickListener { openQueue() }
            sheet = PlayerSheet(findViewById(R.id.sheetRoot)) { open ->
                updateBack()
                if (open) hideM() else showM()
            }
        } else {
            // 57.13: o player da TV ganha as folhas do celular (Configurações, Qualidade, Áudio, Legendas com busca, Temporizador) e a fila de episódios, tudo pelo controle remoto
            fitMode = getSharedPreferences("starflix", MODE_PRIVATE).getInt("pl_fit", 0).coerceIn(0, 2)
            applyFit()
            sheet = PlayerSheet(findViewById(R.id.sheetRoot), tvMode = true) { open ->
                if (open) { handler.removeCallbacks(hideOverlay); tvOverlay.visibility = View.GONE; setTvFocus(0) } else showInfo()
            }
        }

        begin()
        handler.post(tick)
    }

    // ---------- rede ----------
    private fun request(method: String, path: String, body: String? = null, readTimeoutMs: Int = 60000): Pair<Int, String> {
        val c = URL(base + path).openConnection() as HttpURLConnection
        c.requestMethod = method
        if (method == "POST") c.doOutput = true
        c.connectTimeout = 10000
        c.readTimeout = readTimeoutMs
        authHeaders().forEach { (k, v) -> c.setRequestProperty(k, v) }
        if (method == "POST") {
            if (body != null) c.setRequestProperty("Content-Type", "application/json")
            c.outputStream.use { if (body != null) it.write(body.toByteArray()) }
        }
        val code = c.responseCode
        val text = (if (code < 400) c.inputStream else c.errorStream)?.bufferedReader()?.readText() ?: ""
        c.disconnect()
        return code to text
    }

    /** Cookie (celular) ou Bearer + X-Profile (TV). */
    private fun authHeaders(): Map<String, String> =
        if (tv) mapOf("Authorization" to "Bearer $tvToken", "X-Profile" to tvProfile.toString()) else mapOf("Cookie" to cookie)

    private fun stopSession(s: String?) {
        if (s == null) return
        thread {
            try {
                request("POST", "/stream/session/$s/stop")
            } catch (_: Exception) {
            }
        }
    }

    /** Retoma de onde o perfil parou (posição salva no servidor, se não assistido). */
    private fun begin() {
        loading = true
        if (tv) { loadMeta(); loadQueue() } else loadMetaM()
        loadMarkers()
        if (startOverride >= 0) {  // "Do início": ignora o progresso salvo (só na primeira carga)
            val s = startOverride
            startOverride = -1
            load(null, s)
            return
        }
        thread {
            var startSec = 0
            try {
                val j = JSONObject(request("GET", "/progress/$kind/$itemId").second)
                if (!j.optBoolean("watched") && j.optDouble("position", 0.0) > 5) startSec = j.getDouble("position").toInt()
            } catch (_: Exception) {
            }
            runOnUiThread { if (!isDestroyed) load(null, startSec) }
        }
    }

    /** 50.5: a tela da TV lista HDR10 ou HLG em `Display.hdrCapabilities`. */
    private val tvHdr: Boolean by lazy {
        try {
            @Suppress("DEPRECATION")
            val types = windowManager.defaultDisplay.hdrCapabilities?.supportedHdrTypes ?: IntArray(0)
            types.any { it == Display.HdrCapabilities.HDR_TYPE_HDR10 || it == Display.HdrCapabilities.HDR_TYPE_HLG }
        } catch (e: Exception) {
            false
        }
    }

    /** 52.4: perfil de capacidades (`?caps=`): decodificadores de hardware (MediaCodecList sem `OMX.google.*`/`c2.android.*`; H.264 sempre entra), HDR da tela, passthrough AC3/EAC3 e contêineres fixos do ExoPlayer. */
    @OptIn(UnstableApi::class)
    private val caps: String by lazy {
        val v = linkedSetOf("h264")
        var b10 = false
        try {
            for (info in MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos) {
                if (info.isEncoder || info.name.startsWith("OMX.google.") || info.name.startsWith("c2.android.")) continue
                for (type in info.supportedTypes) {
                    val c = try { info.getCapabilitiesForType(type) } catch (_: Exception) { continue }
                    val levels = c.profileLevels.map { it.profile }
                    when (type.lowercase()) {
                        "video/hevc" -> { v.add("hevc"); if (MediaCodecInfo.CodecProfileLevel.HEVCProfileMain10 in levels) b10 = true }
                        "video/av01" -> { v.add("av1"); if (Build.VERSION.SDK_INT >= 29 && MediaCodecInfo.CodecProfileLevel.AV1ProfileMain10 in levels) b10 = true }
                        "video/x-vnd.on2.vp9" -> v.add("vp9")
                    }
                }
            }
        } catch (_: Exception) {
        }
        val a = mutableListOf("aac", "mp3", "opus", "vorbis", "flac")
        var ch = if (tv) 2 else 8  // TV sem passthrough: áudio estéreo (como o antigo `tv_audio_ok`); celular decodifica e faz downmix
        try {
            @Suppress("DEPRECATION")  // 54.6: sem substituto no media3 1.3.1 (a sobrecarga nova vem no 1.4)
            val ac = AudioCapabilities.getCapabilities(this)
            if (ac.supportsEncoding(C.ENCODING_AC3)) { a.add("ac3"); if (tv) ch = 6 }
            if (ac.supportsEncoding(C.ENCODING_E_AC3)) { a.add("eac3"); if (tv) ch = 6 }
        } catch (_: Exception) {
        }
        "v=${v.joinToString(".")}&a=${a.joinToString(".")}&c=mp4.mkv.webm.ts&b10=${if (b10) 1 else 0}&hdr=${if (tvHdr) 1 else 0}&ch=$ch"
    }

    /** Pede /play (áudio e posição inicial) e toca o resultado; descarta a sessão anterior. */
    private fun load(audio: Int?, startSec: Int) {
        error.visibility = View.GONE
        loading = true
        val token = ++loadToken
        val old = sid
        sid = null
        stopSession(old)
        thread {
            try {
                val q = buildString {
                    append("?start=").append(startSec)
                    if (audio != null) append("&audio=").append(audio)
                    quality?.let { append("&quality=").append(it) }  // 55.6
                    capsUsed = !safe
                    if (safe) append("&mode=safe") else {
                        if (forceHls) append("&mode=hls")
                        append("&caps=").append(URLEncoder.encode(caps, "UTF-8"))  // 52.4
                    }
                    if (tv) append("&tv=1")  // TV: só toca direto AAC/MP3 em até 2 canais; o resto vai por HLS com áudio AAC estéreo
                    if (tv) append(if (tvHdr) "&hdr=1" else "&hdr=0")  // 50.5: TV com HDR10/HLG reproduz HDR sozinha; senão o servidor converte para SDR
                }
                val (code, text) = request("POST", "/stream/$kind/$itemId/play$q")
                if (code == 401 && tv) {  // token revogado: volta ao pareamento
                    runOnUiThread { setResult(RESULT_UNAUTHORIZED); finish() }
                    return@thread
                }
                val json = try {
                    JSONObject(text)
                } catch (_: Exception) {  // HTML (sessão expirada) ou corpo vazio
                    throw Exception(getString(R.string.player_bad_response, code))
                }
                if (code != 200) throw Exception(json.optString("error", getString(R.string.player_start_fail)) + json.optString("detail").let { if (it.isBlank()) "" else "\n" + it.take(300) })
                runOnUiThread {
                    if (token != loadToken || isDestroyed) {
                        stopSession(json.optString("sid").ifBlank { null })  // carga antiga: encerra a sessão para não vazar
                    } else {
                        start(json, startSec)
                    }
                }
                if (token == loadToken && !tracksLoaded) loadTracks()
            } catch (e: Exception) {
                runOnUiThread { if (token == loadToken) fail(e.message ?: getString(R.string.player_start_fail)) }
            }
        }
    }

    private fun loadTracks() {
        val id = itemId  // item deste pedido; se mudar (próximo episódio), a resposta é descartada
        try {
            val root = JSONObject(request("GET", "/stream/$kind/$id/info").second)
            val info = root.optJSONObject("info")
            val ql = mutableListOf<Triple<String, String, String>>()
            root.optJSONArray("quality_info")?.let { a ->
                for (i in 0 until a.length()) {
                    val q = a.getJSONObject(i)
                    val kbps = q.optInt("kbps", 0)
                    val mbps = kbps / 1000.0
                    val mbpsTxt = Fmt.decimal(mbps)
                    ql.add(Triple(q.getString("id"), q.getString("id"), getString(R.string.quality_info, mbpsTxt, Math.round(kbps * 0.45))))
                }
            }
            val audio = mutableListOf<Pair<Int, String>>()
            val dur = info?.optDouble("duration", 0.0) ?: 0.0
            val arr = info?.optJSONArray("audio")
            if (arr != null) for (i in 0 until arr.length()) {
                val a = arr.getJSONObject(i)
                val name = a.optString("title").ifBlank { a.optString("lang").ifBlank { "Faixa ${i + 1}" }.uppercase() }
                val label = listOf(name, a.optString("codec").uppercase(), if (a.optInt("channels") > 0) "${a.optInt("channels")}ch" else "")
                    .filter { it.isNotBlank() }.joinToString(" · ")
                audio.add(a.getInt("index") to label)
            }
            val subs = JSONObject(request("GET", "/stream/$kind/$id/subs", readTimeoutMs = 300000).second)
            val list = mutableListOf<Pair<String, String>>()
            subs.optJSONArray("external")?.let { e ->
                for (i in 0 until e.length()) {
                    val s = e.getJSONObject(i)
                    list.add(getString(R.string.subs_ext, s.optString("lang").ifBlank { s.optString("title") }) to s.getString("url"))
                }
            }
            subs.optJSONArray("embedded")?.let { e ->
                for (i in 0 until e.length()) {
                    val s = e.getJSONObject(i)
                    val name = s.optString("title").ifBlank { s.optString("lang").ifBlank { "Faixa ${s.optInt("index")}" } }
                    list.add(name.uppercase() to s.getString("url"))
                }
            }
            runOnUiThread {
                if (id != itemId) return@runOnUiThread
                duration = dur
                audioTracks = audio
                qualityList = ql
                subTracks = list
                tracksLoaded = true
                updateTrackButtons()
            }
        } catch (_: Exception) {
        }
    }

    // ---------- player ----------
    private fun start(j: JSONObject, startSec: Int) {
        if (isDestroyed) return
        loading = false
        tvSeekTarget = null
        lastSave = System.currentTimeMillis()
        sid = if (j.has("sid")) j.getString("sid") else null
        val direct = j.getString("mode") == "direct"
        hls = !direct
        offset = if (direct) 0.0 else j.optDouble("offset", 0.0)
        val item = MediaItem.Builder()
            .setUri(base + j.getString("url"))
            .apply { if (!direct) setMimeType(MimeTypes.APPLICATION_M3U8) }
            .build()
        val p = player ?: createPlayer().also { player = it; view.player = it }
        if (direct) p.setMediaItem(item, startSec * 1000L) else p.setMediaItem(item)
        p.prepare()
        p.playWhenReady = true
    }

    private fun createPlayer(): ExoPlayer {
        val http = DefaultHttpDataSource.Factory().setDefaultRequestProperties(authHeaders())
        // cache: começa a tocar com 5 s carregados (também após travar) e mantém 10 s à frente durante a reprodução
        val load = DefaultLoadControl.Builder()
            .setBufferDurationsMs(10_000, 10_000, 5_000, 5_000)
            .build()
        return ExoPlayer.Builder(this).setLoadControl(load).setMediaSourceFactory(DefaultMediaSourceFactory(http)).build().also {
            // 57.29: as legendas são só as da lista (.vtt desenhadas por nós); sem isto o ExoPlayer ligava sozinho a faixa forçada/padrão embutida do arquivo (direct play)
            it.trackSelectionParameters = it.trackSelectionParameters.buildUpon().setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true).build()
            it.addListener(object : Player.Listener {
                override fun onPlayerError(e: PlaybackException) {
                    if (capsUsed && !safe && !loading) {  // 52.4: direct/remux pelo `caps` falhou: uma repetição com transcode completo
                        safe = true
                        load(audioIndex, absPos().toInt())
                    } else if (!hls && !forceHls && !loading) {  // falha no direct play: tenta uma vez via HLS na posição atual
                        forceHls = true
                        load(audioIndex, absPos().toInt())
                    } else if (hls && !hlsRetried && !loading) {  // pausa/tela apagada > TTL: o servidor apagou a sessão (como player.js)
                        hlsRetried = true
                        load(audioIndex, absPos().toInt())
                    } else fail(getString(R.string.player_stream_error, e.errorCodeName))
                }
                override fun onPlaybackStateChanged(state: Int) {
                    if (state == Player.STATE_ENDED) onEnded()
                }

                override fun onIsPlayingChanged(isPlaying: Boolean) {
                    if (isPlaying) hlsRetried = false else save()
                    if (tv) {
                        updatePlayIcon()
                        // 57.24: só cancela o "sumir" se o usuário pausou; durante o buffer após pular 10 s segue tentando, e ao voltar a tocar agenda de novo (antes o cancelamento deixava os controles presos)
                        if (tvOverlay.visibility == View.VISIBLE) {
                            handler.removeCallbacks(hideOverlay)
                            if (isPlaying) handler.postDelayed(hideOverlay, 4000)
                            else if (player?.playWhenReady == true) handler.postDelayed(hideOverlay, 1000)
                        }
                    }
                    else { updateMPlay(); updatePipParams(); if (mOverlay.visibility == View.VISIBLE) { handler.removeCallbacks(hideMRun); if (isPlaying) handler.postDelayed(hideMRun, 3000) } }
                }

                override fun onVideoSizeChanged(size: androidx.media3.common.VideoSize) {
                    if (!tv) updatePipParams()
                }
            })
        }
    }

    // ---------- progresso ----------
    private fun progressBody(pos: Double) =
        JSONObject().put("position", pos).apply { if (duration > 0) put("duration", duration) }.toString()

    /** Salva a posição atual do perfil (a cada 10 s, ao pausar e ao sair). */
    private fun save() {
        if (loading || ending) return
        val pos = absPos()
        if (pos < 1) return
        val k = kind
        val id = itemId
        val body = progressBody(pos)
        lastSave = System.currentTimeMillis()
        thread {
            try {
                request("POST", "/progress/$k/$id", body)
            } catch (_: Exception) {
            }
        }
    }

    /** Fim do item: marca como assistido e, se for episódio, segue para o próximo automaticamente. */
    private fun onEnded() {
        if (ending) return
        ending = true
        val k = kind
        val id = itemId
        val end = if (duration > 0) duration else absPos()
        thread {
            var next = 0
            try {
                val body = JSONObject().put("position", end).put("duration", end).toString()
                val j = JSONObject(request("POST", "/progress/$k/$id", body).second)
                next = j.optJSONObject("next")?.optInt("id", 0) ?: 0
            } catch (_: Exception) {
            }
            runOnUiThread { if (next > 0 && !isDestroyed && timerMin != -1) switchTo(next) else finish() }
        }
    }

    private fun switchTo(id: Int) {
        itemId = id
        ending = false
        audioIndex = null
        audioTracks = emptyList()
        audioChecked = 0
        quality = null
        qualityList = emptyList()
        subTracks = emptyList()
        subChecked = -1
        findState = 0
        findCands = emptyList()
        cues = emptyList()
        subtitle.visibility = View.GONE
        tracksLoaded = false
        updateTrackButtons()
        duration = 0.0
        hls = false
        forceHls = false
        safe = false
        hlsRetried = false
        sheet?.close()
        mOverlay.visibility = View.GONE
        tvOverlay.visibility = View.GONE
        prevId = 0
        nextId = 0
        queueItems = emptyList()
        findViewById<View>(R.id.queueRoot).visibility = View.GONE
        updateBack()
        begin()
    }

    private fun fmt(t: Double): String {
        val s = t.toLong().coerceAtLeast(0)
        val h = s / 3600
        val m = s / 60 % 60
        val sec = s % 60
        return if (h > 0) "%d:%02d:%02d".format(h, m, sec) else "%d:%02d".format(m, sec)
    }

    // ---------- Picture-in-Picture (55.9) ----------
    private var inPip = false
    private val pipReceiver = object : android.content.BroadcastReceiver() {
        override fun onReceive(c: android.content.Context?, i: android.content.Intent?) {
            val p = player ?: return
            if (p.isPlaying) p.pause() else p.play()
            updatePipParams()
        }
    }

    private fun pipSupported() = !tv && packageManager.hasSystemFeature(android.content.pm.PackageManager.FEATURE_PICTURE_IN_PICTURE)

    private fun pipParams(): android.app.PictureInPictureParams {
        val b = android.app.PictureInPictureParams.Builder()
        val vs = player?.videoSize
        if (vs != null && vs.width > 0 && vs.height > 0) {
            val r = (vs.width * vs.pixelWidthHeightRatio / vs.height).coerceIn(0.42f, 2.38f)
            b.setAspectRatio(android.util.Rational((r * 1000).toInt(), 1000))
        }
        val playing = player?.isPlaying == true
        val pi = android.app.PendingIntent.getBroadcast(this, 0, android.content.Intent(ACTION_PIP_TOGGLE).setPackage(packageName),
            android.app.PendingIntent.FLAG_UPDATE_CURRENT or android.app.PendingIntent.FLAG_IMMUTABLE)
        val label = if (playing) "Pausar" else "Reproduzir"
        b.setActions(listOf(android.app.RemoteAction(
            android.graphics.drawable.Icon.createWithResource(this, if (playing) R.drawable.ic_m_pause else R.drawable.ic_m_play), label, label, pi)))
        if (Build.VERSION.SDK_INT >= 31) { b.setAutoEnterEnabled(playing); b.setSeamlessResizeEnabled(false) }
        return b.build()
    }

    private fun updatePipParams() {
        if (!pipSupported() || isDestroyed) return
        try { setPictureInPictureParams(pipParams()) } catch (_: Exception) { }
    }

    private fun enterPip() {
        if (!pipSupported() || isDestroyed) return
        try { enterPictureInPictureMode(pipParams()) } catch (_: Exception) { }
    }

    override fun onUserLeaveHint() {
        super.onUserLeaveHint()
        // Android 8–11: sai do app tocando → entra em PiP (no 12+ o `setAutoEnterEnabled` já faz isso)
        if (Build.VERSION.SDK_INT < 31 && pipSupported() && player?.isPlaying == true && !isFinishing) enterPip()
    }

    override fun onPictureInPictureModeChanged(isInPictureInPictureMode: Boolean, newConfig: android.content.res.Configuration) {
        super.onPictureInPictureModeChanged(isInPictureInPictureMode, newConfig)
        inPip = isInPictureInPictureMode
        if (isInPictureInPictureMode) {
            hideM()
            sheet?.close()
            closeQueue(false)
            subtitle.textSize = 9f
            val f = android.content.IntentFilter(ACTION_PIP_TOGGLE)
            if (Build.VERSION.SDK_INT >= 33) registerReceiver(pipReceiver, f, android.content.Context.RECEIVER_NOT_EXPORTED) else registerReceiver(pipReceiver, f)
        } else {
            subtitle.textSize = subSizeSp
            try { unregisterReceiver(pipReceiver) } catch (_: Exception) { }
            showM()
        }
    }

    // ---------- Fila de Reprodução (55.8) ----------
    private class QItem(val id: Int, val title: String, val line: String, val image: String)

    private var queueItems = listOf<QItem>()
    private val imgCache = android.util.LruCache<String, Bitmap>(40)

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun queueIsOpen() = findViewById<View>(R.id.queueRoot).visibility == View.VISIBLE

    private fun updateBack() { backCbRef?.isEnabled = queueIsOpen() || sheet?.isOpen == true }

    private fun openQueue() {
        if (queueItems.isEmpty()) return
        hideM()
        if (tv) { handler.removeCallbacks(hideOverlay); tvOverlay.visibility = View.GONE; setTvFocus(0) }
        val list = findViewById<android.widget.LinearLayout>(R.id.queueList)
        list.removeAllViews()
        for (q in queueItems) list.addView(queueCard(q, q.id == itemId))
        findViewById<View>(R.id.queueRoot).visibility = View.VISIBLE
        findViewById<View>(R.id.queueScroll).scrollTo(0, 0)
        updateBack()
        if (tv) {  // foco no episódio seguinte (ou no atual se for o último)
            val cur = queueItems.indexOfFirst { it.id == itemId }
            val i = (if (cur >= 0) cur + 1 else 0).coerceAtMost(queueItems.size - 1)
            list.post { list.getChildAt(i)?.requestFocus() }
        }
    }

    private fun closeQueue(showControls: Boolean = true) {
        if (!queueIsOpen()) return
        findViewById<View>(R.id.queueRoot).visibility = View.GONE
        updateBack()
        if (showControls) { if (tv) showInfo() else showM() }
    }

    private fun queueCard(q: QItem, current: Boolean): View {
        val card = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            layoutParams = android.widget.LinearLayout.LayoutParams(dp(200), ViewGroup.LayoutParams.WRAP_CONTENT).apply { marginEnd = dp(12) }
            setOnClickListener {
                closeQueue(false)
                if (!current) { save(); switchTo(q.id) }
            }
            if (tv) {  // 57.13: card focável pelo controle remoto, com a borda laranja do foco
                isFocusable = true
                setPadding(dp(4), dp(4), dp(4), dp(6))
                background = android.graphics.drawable.StateListDrawable().apply {
                    addState(intArrayOf(android.R.attr.state_focused), android.graphics.drawable.GradientDrawable().apply {
                        cornerRadius = dp(12).toFloat(); setColor(android.graphics.Color.parseColor("#26FFFFFF")); setStroke(dp(2), android.graphics.Color.parseColor("#E5A00D"))
                    })
                }
            }
        }
        val box = android.widget.FrameLayout(this)
        val iv = ImageView(this).apply {
            scaleType = ImageView.ScaleType.CENTER_CROP
            setBackgroundColor(android.graphics.Color.parseColor("#202020"))
            outlineProvider = object : android.view.ViewOutlineProvider() {
                override fun getOutline(v: View, o: android.graphics.Outline) { o.setRoundRect(0, 0, v.width, v.height, dp(10).toFloat()) }
            }
            clipToOutline = true
        }
        box.addView(iv, android.widget.FrameLayout.LayoutParams(dp(200), dp(113)))
        if (current) box.addView(ImageView(this).apply {
            setImageResource(R.drawable.ic_m_play)
            setBackgroundResource(R.drawable.m_play_bg)
            setPadding(dp(9), dp(9), dp(9), dp(9))
        }, android.widget.FrameLayout.LayoutParams(dp(40), dp(40), android.view.Gravity.CENTER))
        card.addView(box)
        card.addView(TextView(this).apply {
            text = q.title
            setTextColor(android.graphics.Color.WHITE)
            textSize = 14f
            setTypeface(typeface, android.graphics.Typeface.BOLD)
            maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END
            setPadding(0, dp(6), 0, 0)
        })
        card.addView(TextView(this).apply {
            text = q.line
            setTextColor(android.graphics.Color.parseColor("#B3B3B3"))
            textSize = 12f
            maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END
        })
        loadImage(q.image, iv)
        return card
    }

    private fun loadImage(path: String, iv: ImageView) {
        imgCache.get(path)?.let { iv.setImageBitmap(it); return }
        iv.tag = path
        thread {
            try {
                val bmp = fetchBitmap(path) ?: return@thread
                imgCache.put(path, bmp)
                runOnUiThread { if (iv.tag == path) iv.setImageBitmap(bmp) }
            } catch (_: Exception) {
            }
        }
    }

    private fun fetchBitmap(path: String): Bitmap? {
        val c = URL(base + path).openConnection() as HttpURLConnection
        c.connectTimeout = 10000
        c.readTimeout = 30000
        authHeaders().forEach { (k, v) -> c.setRequestProperty(k, v) }
        try {
            if (c.responseCode != 200) return null
            val bytes = c.inputStream.use { it.readBytes() }
            val o = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size, o)
            var sample = 1
            while (o.outWidth / (sample * 2) >= 480) sample *= 2
            return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = sample })
        } finally {
            c.disconnect()
        }
    }

    // ---------- Opções de Reprodução (55.7) ----------
    private fun applyOrientation() {
        requestedOrientation = if (lockLand) android.content.pm.ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        else android.content.pm.ActivityInfo.SCREEN_ORIENTATION_SENSOR
    }

    private fun applyFit() {
        view.resizeMode = when (fitMode) {
            1 -> AspectRatioFrameLayout.RESIZE_MODE_ZOOM
            2 -> AspectRatioFrameLayout.RESIZE_MODE_FILL
            else -> AspectRatioFrameLayout.RESIZE_MODE_FIT
        }
    }

    private fun fitName(m: Int) = getString(when (m) { 1 -> R.string.fit_fill; 2 -> R.string.fit_stretch; else -> R.string.fit_letterbox })

    private fun timerName(m: Int) = when (m) {
        0 -> getString(R.string.timer_off)
        -1 -> getString(R.string.timer_end)
        else -> Fmt.mins(m)
    }

    private val timerRun = Runnable {
        timerMin = 0
        player?.pause()
        save()
        finish()
    }

    private fun setTimer(m: Int) {
        timerMin = m
        handler.removeCallbacks(timerRun)
        if (m > 0) handler.postDelayed(timerRun, m * 60_000L)
    }

    private fun openPlayOptionsSheet() {
        val sh = sheet ?: return
        sh.open(getString(R.string.play_options)) {
            listOfNotNull(
                if (tv) null else PlayerSheet.Row(getString(R.string.lock_land), toggle = lockLand) {
                    lockLand = !lockLand
                    getSharedPreferences("starflix", MODE_PRIVATE).edit().putBoolean("pl_lock", lockLand).apply()
                    applyOrientation()
                    sheet?.refresh()
                },
                PlayerSheet.Row(getString(R.string.timer), value = timerName(timerMin)) { openTimerSheet() },
                PlayerSheet.Row(getString(R.string.display_mode), value = fitName(fitMode)) { openFitSheet() },
            )
        }
    }

    private fun openTimerSheet() {
        val sh = sheet ?: return
        sh.open(getString(R.string.timer)) {
            listOf(0, 15, 30, 45, 60, -1).map { m -> PlayerSheet.Row(timerName(m), selected = timerMin == m) { setTimer(m); sheet?.back() } }
        }
    }

    private fun openFitSheet() {
        val sh = sheet ?: return
        sh.open(getString(R.string.display_mode)) {
            listOf(0, 1, 2).map { m ->
                PlayerSheet.Row(fitName(m), selected = fitMode == m) {
                    fitMode = m
                    getSharedPreferences("starflix", MODE_PRIVATE).edit().putInt("pl_fit", m).apply()
                    applyFit()
                    sheet?.back()
                }
            }
        }
    }

    // ---------- folha Configurações (55.5) ----------
    private fun curSubsText() = if (subChecked in subTracks.indices) subLabel(subChecked) else getString(R.string.subs_none)

    private fun curAudioText() = audioTracks.getOrNull(audioChecked)?.second ?: ""

    private fun openSettingsSheet() {
        val sh = sheet ?: return
        sh.open(getString(R.string.settings_title)) {
            listOf(
                PlayerSheet.Row(getString(R.string.quality), value = quality ?: getString(R.string.quality_original)) { openQualitySheet() },
                PlayerSheet.Row(getString(R.string.subtitles), value = curSubsText()) { openSubsSheet() },
                PlayerSheet.Row(getString(R.string.audio), value = curAudioText().ifBlank { null }) { openAudioSheet() },
                PlayerSheet.Row(getString(R.string.play_options)) { openPlayOptionsSheet() },
            )
        }
    }

    /** 55.6: Original + qualidades do servidor (sem upscale); escolher recarrega o `play` com `&quality=` na posição atual. */
    private fun openQualitySheet() {
        val sh = sheet ?: return
        sh.open(getString(R.string.quality)) {
            val rows = mutableListOf<PlayerSheet.Row>()
            rows.add(PlayerSheet.Row(getString(R.string.quality_original), selected = quality == null) { setQuality(null) })
            for ((id, label, sub) in qualityList) rows.add(PlayerSheet.Row(label, sub = sub, selected = quality == id) { setQuality(id) })
            rows
        }
    }

    private fun setQuality(q: String?) {
        sheet?.close()
        if (q == quality) return
        quality = q
        forceHls = false
        safe = false
        hlsRetried = false
        load(audioIndex, absPos().toInt())
    }

    /** Lista de faixas de áudio; escolher outra recarrega o `play` com `&audio=` na posição atual (mesma lógica do `pickAudio`). */
    private fun openAudioSheet() {
        val sh = sheet ?: return
        sh.open(getString(R.string.audio)) {
            audioTracks.mapIndexed { i, a ->
                PlayerSheet.Row(a.second, selected = i == audioChecked) {
                    sheet?.close()
                    if (i != audioChecked) {
                        audioChecked = i
                        audioIndex = a.first
                        load(audioIndex, absPos().toInt())
                    }
                }
            }
        }
    }

    // ---------- folha Legendas (55.4) ----------
    private class Cand(val id: Int, val release: String, val sub: String)
    private var findLang: String? = null          // idioma da busca (chave do SubDL); null = o do servidor
    private var findLangs = listOf<Pair<String, String>>()
    private var findCands = listOf<Cand>()
    private var findState = 0                     // 0 = não buscou, 1 = buscando, 2 = pronto, 3 = erro
    private var findMsg = ""
    private var findBudget = ""

    private fun subLabel(i: Int): String = subTracks[i].first

    private fun openSubsSheet() {
        val sh = sheet ?: return
        sh.open(getString(R.string.subtitles)) {
            val rows = mutableListOf<PlayerSheet.Row>()
            rows.add(PlayerSheet.Row(getString(R.string.subs_none), selected = subChecked < 0) { subChecked = -1; setSubs(null); sheet?.close() })
            for (i in subTracks.indices) rows.add(PlayerSheet.Row(subLabel(i), selected = subChecked == i) { subChecked = i; setSubs(subTracks[i].second); sheet?.close() })
            rows.add(PlayerSheet.Row(getString(R.string.subs_find)) { openFindSheet() })
            rows
        }
    }

    private fun openFindSheet() {
        val sh = sheet ?: return
        if (findState != 2 || findCands.isEmpty()) searchSubs(false)
        sh.open(getString(R.string.subs_find)) {
            val rows = mutableListOf<PlayerSheet.Row>()
            val cur = findLangs.firstOrNull { it.first == findLang }?.second
            // TV: sem escolha de idioma; usa o das configurações (servidor) e já busca
            if (!tv && findLangs.isNotEmpty()) rows.add(PlayerSheet.Row(getString(R.string.subs_lang), value = cur) { openLangSheet() })
            when (findState) {
                1 -> rows.add(PlayerSheet.Row(getString(R.string.subs_searching)) {})
                3 -> {
                    rows.add(PlayerSheet.Row(findMsg) {})
                    rows.add(PlayerSheet.Row(getString(R.string.subs_again)) { searchSubs(true) })
                }
                else -> {
                    if (findCands.isEmpty()) rows.add(PlayerSheet.Row(getString(R.string.subs_none_found)) {})
                    for (c in findCands) rows.add(PlayerSheet.Row(c.release, sub = c.sub) { pickCand(c) })
                    rows.add(PlayerSheet.Row(getString(R.string.subs_again), value = findBudget.ifBlank { null }) { searchSubs(true) })
                }
            }
            rows
        }
    }

    private fun openLangSheet() {
        val sh = sheet ?: return
        sh.open(getString(R.string.subs_lang)) {
            findLangs.map { (code, label) -> PlayerSheet.Row(label, selected = code == findLang) { findLang = code; sheet?.back(); searchSubs(false) } }
        }
    }

    /** Busca no SubDL pelo servidor (cache de 24 h; `refresh` refaz). */
    private fun searchSubs(refresh: Boolean) {
        val id = itemId
        val k = kind
        findState = 1
        findCands = emptyList()
        sheet?.refresh()
        val body = JSONObject().apply { if (findLang != null) put("lang", findLang); if (refresh) put("refresh", true) }.toString()
        thread {
            try {
                val (code, text) = request("POST", "/stream/$k/$id/subs/search", body, readTimeoutMs = 120000)
                val j = JSONObject(text)
                if (code != 200) throw Exception(j.optString("error", getString(R.string.subs_search_fail_http, code)))
                val langs = mutableListOf<Pair<String, String>>()
                j.optJSONArray("langs")?.let { a -> for (i in 0 until a.length()) langs.add(a.getJSONObject(i).let { it.getString("code") to it.getString("label") }) }
                val cands = mutableListOf<Cand>()
                j.optJSONArray("candidates")?.let { a ->
                    for (i in 0 until a.length()) {
                        val c = a.getJSONObject(i)
                        val parts = mutableListOf<String>()
                        c.optString("author").takeIf { it.isNotBlank() && it != "null" }?.let { parts.add(it) }
                        if (c.optBoolean("forced")) parts.add(getString(R.string.subs_forced))
                        if (c.optBoolean("hi")) parts.add("SDH")
                        if (c.optBoolean("pack")) parts.add(getString(R.string.subs_pack))
                        c.optInt("downloads", 0).takeIf { it > 0 }?.let { parts.add("$it downloads") }
                        cands.add(Cand(c.getInt("id"), c.optString("release").ifBlank { "Legenda ${i + 1}" }, parts.joinToString(" • ")))
                    }
                }
                val b = j.optJSONObject("budget")
                val bud = if (b != null) "${b.optInt("used")}/${b.optInt("max")} buscas hoje" else ""
                val lang = j.optString("lang")
                runOnUiThread {
                    if (id != itemId || isDestroyed) return@runOnUiThread
                    findLangs = langs; findLang = lang; findCands = cands; findBudget = bud; findState = 2
                    sheet?.refresh()
                }
            } catch (e: Exception) {
                runOnUiThread {
                    if (id != itemId || isDestroyed) return@runOnUiThread
                    findMsg = e.message ?: getString(R.string.subs_search_fail); findState = 3
                    sheet?.refresh()
                }
            }
        }
    }

    /** Baixa a candidata (servidor grava ao lado do vídeo), recarrega a lista de legendas e ativa a nova. */
    private fun pickCand(c: Cand) {
        val id = itemId
        val k = kind
        val lang = findLang ?: return
        findState = 1
        sheet?.refresh()
        thread {
            try {
                val (code, text) = request("POST", "/stream/$k/$id/subs/pick", JSONObject().put("lang", lang).put("id", c.id).toString(), readTimeoutMs = 120000)
                val j = JSONObject(text)
                if (code != 200) throw Exception(j.optString("error", getString(R.string.subs_download_fail_http, code)))
                val file = j.optString("file")
                val subs = JSONObject(request("GET", "/stream/$k/$id/subs", readTimeoutMs = 300000).second)
                val list = mutableListOf<Pair<String, String>>()
                var pos = -1
                subs.optJSONArray("external")?.let { e ->
                    for (i in 0 until e.length()) {
                        val s = e.getJSONObject(i)
                        if (s.optString("title") == file) pos = list.size
                        list.add(getString(R.string.subs_ext, s.optString("lang").ifBlank { s.optString("title") }) to s.getString("url"))
                    }
                }
                subs.optJSONArray("embedded")?.let { e ->
                    for (i in 0 until e.length()) {
                        val s = e.getJSONObject(i)
                        val name = s.optString("title").ifBlank { s.optString("lang").ifBlank { "Faixa ${s.optInt("index")}" } }
                        list.add(name.uppercase() to s.getString("url"))
                    }
                }
                runOnUiThread {
                    if (id != itemId || isDestroyed) return@runOnUiThread
                    subTracks = list
                    findState = 2
                    if (pos >= 0) { subChecked = pos; setSubs(list[pos].second) }
                    sheet?.close()
                }
            } catch (e: Exception) {
                runOnUiThread {
                    if (id != itemId || isDestroyed) return@runOnUiThread
                    findMsg = e.message ?: getString(R.string.subs_download_fail); findState = 3
                    sheet?.refresh()
                }
            }
        }
    }

    // ---------- controles do celular (55.2) ----------
    private val hideMRun = Runnable { if (player?.isPlaying == true && !dragging) mOverlay.visibility = View.GONE }

    /** Mostra os controles; somem sozinhos em 3 s se estiver tocando. */
    private fun showM() {
        if (tv) return
        refreshM()
        mOverlay.visibility = View.VISIBLE
        handler.removeCallbacks(hideMRun)
        handler.postDelayed(hideMRun, 3000)
    }

    private fun hideM() {
        handler.removeCallbacks(hideMRun)
        mOverlay.visibility = View.GONE
    }

    private fun updateMPlay() {
        mBtnPlay.setImageResource(if (player?.isPlaying == true) R.drawable.ic_m_pause else R.drawable.ic_m_play)
    }

    private fun refreshM() {
        updateMPlay()
        mBtnPrev.visibility = if (prevId > 0) View.VISIBLE else View.GONE
        mBtnNext.visibility = if (nextId > 0) View.VISIBLE else View.GONE
        mBtnQueue.visibility = if (queueItems.isNotEmpty()) View.VISIBLE else View.GONE
        if (dragging) return
        val t = absPos()
        mElapsed.text = fmt(t)
        if (duration > 0) {
            mSeek.progress = (t / duration * 1000).toInt().coerceIn(0, 1000)
            val buf = offset + (player?.bufferedPosition ?: 0L) / 1000.0
            mSeek.secondaryProgress = (buf / duration * 1000).toInt().coerceIn(0, 1000)
            mRemain.text = "-" + fmt(duration - t)
        } else {
            mSeek.progress = 0
            mRemain.text = ""
        }
    }

    /** Título e linha cinza do cabeçalho + episódio anterior/seguinte, de /api/tv/next (55.1). */
    private fun loadMetaM() {
        val id = itemId
        val k = kind
        mTitle.text = ""
        mSub.text = ""
        if (k != "episode" && k != "movie" && k != "video") return
        thread {
            try {
                val j = JSONObject(request("GET", "/api/tv/next/$k/$id").second)
                val cur = j.optJSONObject("current")
                val title = cur?.optString("title").orEmpty()
                val line = cur?.optString("line").orEmpty()
                val pv = if (j.isNull("prev_id")) 0 else j.optInt("prev_id", 0)
                val nx = if (j.isNull("next_id")) 0 else j.optInt("next_id", 0)
                val qi = mutableListOf<QItem>()
                j.optJSONArray("items")?.let { a ->
                    for (i in 0 until a.length()) a.getJSONObject(i).let { q -> qi.add(QItem(q.getInt("id"), q.optString("title"), q.optString("line"), q.optString("image"))) }
                }
                runOnUiThread {
                    if (id == itemId && !isDestroyed) {
                        mTitle.text = title
                        mSub.text = line
                        prevId = pv
                        nextId = nx
                        queueItems = qi
                        refreshM()
                    }
                }
            } catch (_: Exception) {
            }
        }
    }

    /** Busca para o segundo absoluto t: dentro do trecho já gerado usa o player; fora dele reinicia a sessão em t. */
    private fun seekTo(t: Double) {
        val p = player ?: return
        val target = t.coerceIn(0.0, if (duration > 0) duration else t)
        if (!hls) {
            p.seekTo((target * 1000).toLong())
            return
        }
        val local = target - offset
        val d = p.duration
        val generated = (if (d != C.TIME_UNSET) d else p.bufferedPosition) / 1000.0
        if (local >= 0 && local < generated - 6) p.seekTo((local * 1000).toLong())
        else load(audioIndex, target.toInt())
    }

    private fun absPos() = offset + (player?.currentPosition ?: 0L) / 1000.0

    private fun fail(msg: String) {
        error.text = msg
        error.visibility = View.VISIBLE
    }

    // ---------- estilo da legenda do perfil (57.29) ----------
    private var subSizeSp = 18f

    private fun applySubStyle(size: String, color: String, bg: String, pos: String) {
        subSizeSp = when (size) { "p" -> 14f; "g" -> 24f; "gg" -> 32f; else -> 18f }
        if (!inPip) subtitle.textSize = subSizeSp
        subtitle.setTextColor(when (color) { "yellow" -> 0xFFFFE14D.toInt(); "cyan" -> 0xFF6FE3FF.toInt(); "green" -> 0xFF7DFF8A.toInt(); else -> 0xFFFFFFFF.toInt() })
        val dm = resources.displayMetrics
        val h = android.util.TypedValue.applyDimension(android.util.TypedValue.COMPLEX_UNIT_SP, subSizeSp * 0.5f, dm).toInt()
        when (bg) {
            "none" -> { subtitle.setBackgroundColor(0); subtitle.setShadowLayer(0f, 0f, 0f, 0); subtitle.setPadding(0, 0, 0, 0) }
            "box" -> { subtitle.setBackgroundColor(0x9E000000.toInt()); subtitle.setShadowLayer(0f, 0f, 0f, 0); subtitle.setPadding(h, h / 4, h, h / 4) }
            else -> { subtitle.setBackgroundColor(0); subtitle.setShadowLayer(6f, 1f, 1f, 0xFF000000.toInt()); subtitle.setPadding(0, 0, 0, 0) }
        }
        subtitle.maxWidth = (dm.widthPixels * 0.8f).toInt()
        val lp = subtitle.layoutParams as android.widget.FrameLayout.LayoutParams
        lp.bottomMargin = (dm.heightPixels * when (pos) { "low" -> 0.08f; "high" -> 0.26f; else -> 0.16f }).toInt()
        subtitle.layoutParams = lp
    }

    /** Busca o estilo salvo no perfil (Conta → Legenda) e aplica na legenda do player. */
    private fun loadSubStyle() {
        thread {
            try {
                val j = JSONObject(request("GET", "/api/tv/sub-style").second)
                runOnUiThread {
                    if (!isDestroyed) applySubStyle(j.optString("sub_size", "m"), j.optString("sub_color", "white"), j.optString("sub_bg", "shadow"), j.optString("sub_pos", "mid"))
                }
            } catch (_: Exception) {
            }
        }
    }

    // ---------- áudio e legendas ----------
    private fun setSubs(url: String?) {
        cues = emptyList()
        subtitle.visibility = View.GONE
        if (url == null) return
        thread {
            try {
                val parsed = parseVtt(request("GET", url, readTimeoutMs = 300000).second)
                runOnUiThread { if (subChecked >= 0 && subTracks[subChecked].second == url) cues = parsed }
            } catch (_: Exception) {
            }
        }
    }

    private fun tsec(s: String): Double {
        val p = s.replace(',', '.').split(':').map { it.toDouble() }
        return if (p.size == 3) p[0] * 3600 + p[1] * 60 + p[2] else p[0] * 60 + p[1]
    }

    private fun parseVtt(text: String): List<Cue> {
        val re = Regex("([\\d:.,]+)\\s*-->\\s*([\\d:.,]+)")
        val tag = Regex("<[^>]+>")
        val out = mutableListOf<Cue>()
        for (block in text.replace("\r", "").split(Regex("\n\n+"))) {
            val lines = block.split("\n")
            val i = lines.indexOfFirst { it.contains("-->") }
            if (i < 0) continue
            val m = re.find(lines[i]) ?: continue
            out.add(Cue(tsec(m.groupValues[1]), tsec(m.groupValues[2]), lines.drop(i + 1).joinToString("\n").replace(tag, "")))
        }
        return out
    }

    // ---------- controle remoto (TV) ----------
    private val applySeek = Runnable {
        val t = tvSeekTarget ?: return@Runnable
        seekTo(t)  // reinício de sessão: tvSeekTarget fica até start() para a bolinha não voltar
    }
    /** 57.22: marcadores do episódio e preferência do perfil (Pular abertura: perguntar/sempre/nunca); sem marcador de créditos o servidor manda os últimos 45 s. */
    private fun loadMarkers() {
        val id = itemId
        introS = -1.0; introE = -1.0; creditsS = -1.0; skipPref = "ask"; autoNext = true
        introDone = false; introHidden = false; nextHidden = false
        showMark(false, false)
        if (kind != "episode") return
        thread {
            try {
                val j = JSONObject(request("GET", "/api/tv/markers/$id").second)
                var a = -1.0; var b = -1.0; var c = -1.0
                j.optJSONArray("markers")?.let { arr ->
                    for (i in 0 until arr.length()) arr.getJSONObject(i).let { m ->
                        when (m.optString("kind")) {
                            "intro" -> { a = m.optDouble("start", -1.0); b = m.optDouble("end", -1.0) }
                            "credits" -> c = m.optDouble("start", -1.0)
                        }
                    }
                }
                if (c < 0 && !j.isNull("credits_fallback")) c = j.optDouble("credits_fallback", -1.0)
                val pref = j.optString("skip_intro", "ask")
                val auto = j.optString("auto_next", "on") != "off"
                runOnUiThread {
                    if (id == itemId && !isDestroyed) {
                        skipPref = pref
                        autoNext = auto
                        if (pref != "never") { introS = a; introE = b }
                        creditsS = c
                    }
                }
            } catch (_: Exception) {
            }
        }
    }

    /** A cada 250 ms: abertura (janela do marcador) → Pular abertura (ou salta sozinho em "Pular sempre"); créditos → Próximo Episódio. */
    private fun updateMarkers() {
        if (player == null || loading || kind != "episode" || sheet?.isOpen == true || queueIsOpen()) { showMark(false, false); return }
        val t = absPos()
        val inIntro = introS >= 0 && introE > introS && t >= introS - 0.3 && t < introE - 1
        if (introHidden && (t < introS - 1 || t >= introE)) introHidden = false  // saiu da janela: volta a aparecer ao reentrar
        val inCredits = creditsS > 0 && nextId > 0 && t >= creditsS - 0.3
        if (nextHidden && t < creditsS - 1) nextHidden = false
        if (inIntro && skipPref == "always" && !introDone) { introDone = true; seekTo(introE); return }
        val showNext = inCredits && !nextHidden
        if (showNext && autoNext) {  // 57.23: contagem de 10 s (espera com o vídeo pausado); Voltar (TV) ou Cancelar (celular) interrompe
            val now = System.currentTimeMillis()
            if (btnNextEp.visibility != View.VISIBLE) { ncLeft = 10_000L; ncAt = now }
            if (player?.isPlaying == true) ncLeft -= now - ncAt
            ncAt = now
            if (ncLeft <= 0) { doNextEp(); return }
            btnNextEp.text = getString(R.string.next_episode) + " (" + ((ncLeft + 999) / 1000) + ")"
        } else if (showNext) btnNextEp.text = getString(R.string.next_episode)
        showMark(inIntro && !introHidden && !inCredits, showNext)
    }

    private fun showMark(intro: Boolean, next: Boolean) {
        btnSkipIntro.visibility = if (intro) View.VISIBLE else View.GONE
        btnNextEp.visibility = if (next) View.VISIBLE else View.GONE
        btnNextCancel.visibility = if (next && !tv && autoNext) View.VISIBLE else View.GONE
        val ov = (if (tv) tvOverlay else mOverlay).visibility == View.VISIBLE
        val dy = if (ov) -dp(if (tv) 150 else 100).toFloat() else 0f  // sobe para não ficar sobre a barra de tempo
        btnSkipIntro.translationY = dy
        btnNextEp.translationY = dy
        btnNextCancel.translationY = dy
        btnNextCancel.translationX = -(btnNextEp.width + dp(12)).toFloat()  // à esquerda do Próximo Episódio
    }

    private fun markVisible() = btnSkipIntro.visibility == View.VISIBLE || btnNextEp.visibility == View.VISIBLE

    private fun doSkipIntro() {
        if (introE <= 0) return
        introHidden = true
        showMark(false, btnNextEp.visibility == View.VISIBLE)
        seekTo(introE)
    }

    /** Marca o episódio como assistido (como o fim da reprodução) e passa ao seguinte. */
    private fun doNextEp() {
        val nx = nextId
        if (nx <= 0 || ending) return
        ending = true
        nextHidden = true
        showMark(false, false)
        val k = kind
        val id = itemId
        val end = if (duration > 0) duration else absPos()
        thread {
            try {
                request("POST", "/progress/$k/$id", JSONObject().put("position", end).put("duration", end).toString())
            } catch (_: Exception) {
            }
            runOnUiThread { if (!isDestroyed) switchTo(nx) }
        }
    }

    /** 57.20: some depois de ~4 s. Em pausa (pedida pelo usuário) fica; carregando/buffer após pular (isPlaying ainda falso) tenta de novo a cada 1 s em vez de desistir. */
    private val hideOverlay: Runnable = object : Runnable {
        override fun run() {
            val p = player
            if (p == null) {
                handler.postDelayed(this, 1000)
                return
            }
            if (!p.playWhenReady && !loading) return
            if (p.playbackState == androidx.media3.common.Player.STATE_ENDED) return
            if (p.isPlaying) hideTvOverlay() else handler.postDelayed(this, 1000)
        }
    }

    private fun hideTvOverlay() {
        handler.removeCallbacks(hideOverlay)
        tvOverlay.visibility = View.GONE
        setTvFocus(0)
    }

    /** 57.13: episódio anterior/seguinte e fila de episódios da TV, de /api/tv/next (a mesma do celular). */
    private fun loadQueue() {
        val id = itemId
        val k = kind
        if (k != "episode" && k != "movie" && k != "video") return
        thread {
            try {
                val j = JSONObject(request("GET", "/api/tv/next/$k/$id").second)
                val pv = if (j.isNull("prev_id")) 0 else j.optInt("prev_id", 0)
                val nx = if (j.isNull("next_id")) 0 else j.optInt("next_id", 0)
                val qi = mutableListOf<QItem>()
                j.optJSONArray("items")?.let { a ->
                    for (i in 0 until a.length()) a.getJSONObject(i).let { q -> qi.add(QItem(q.getInt("id"), q.optString("title"), q.optString("line"), q.optString("image"))) }
                }
                runOnUiThread {
                    if (id == itemId && !isDestroyed) {
                        prevId = pv
                        nextId = nx
                        queueItems = qi
                        setTvFocus(tvFocus)
                    }
                }
            } catch (_: Exception) {
            }
        }
    }

    /** Título, linha "T · E · série · duração" e relógio: episódio vem de /api/tv/episode, filme de /api/tv/movie. */
    private fun loadMeta() {
        val id = itemId
        val k = kind
        tvTitle.text = ""
        tvSub.text = ""
        if (k != "episode" && k != "movie") return
        thread {
            try {
                val j = JSONObject(request("GET", "/api/tv/$k/$id").second)
                val parts = mutableListOf<String>()
                val title: String
                if (k == "episode") {
                    title = j.optString("title").ifBlank { j.optString("show") }
                    parts.add("S${j.optInt("season")}")
                    parts.add("E${j.optInt("episode")}")
                    parts.add(j.optString("show"))
                } else {
                    title = j.optString("title")
                    j.optInt("year", 0).let { if (it > 0) parts.add(it.toString()) }
                }
                val mins = Math.round(j.optDouble("duration", 0.0) / 60.0).toInt()
                if (mins > 0) parts.add(if (mins == 1) "1 minuto" else "$mins minutos")
                val meta = parts.filter { it.isNotBlank() }.joinToString(" • ")
                runOnUiThread { if (id == itemId && !isDestroyed) { tvTitle.text = title; tvSub.text = meta } }
            } catch (_: Exception) {
            }
        }
    }

    private fun updatePlayIcon() {
        tvBtnPlay.setImageResource(if (player?.isPlaying == true) R.drawable.ic_tv_pause else R.drawable.ic_tv_play)
    }

    private fun setTvFocus(f: Int) {
        if (tvFocus == 3 && f != 3 && tvBarPending) {  // saiu da barra sem OK: descarta a busca pendente
            tvBarPending = false
            tvSeekTarget = null
            handler.removeCallbacks(applySeek)
        }
        tvFocus = f
        tvSeek.knob = f == 3
        tvBtnSubs.isSelected = f == 1
        tvBtnSettings.isSelected = f == 2
        tvQueueHint.visibility = if (f == 3 && queueItems.size > 1) View.VISIBLE else View.INVISIBLE
    }

    /** Preenche tempos, barra (a bolinha acompanha o destino das setas) e relógio. */
    private fun refreshOverlay() {
        val t = tvSeekTarget ?: absPos()
        tvElapsed.text = fmt(t)
        if (duration > 0) {
            tvSeek.fraction = (t / duration).toFloat()
            tvRemain.text = "-" + fmt(duration - t)
        } else {
            tvSeek.fraction = 0f
            tvRemain.text = ""
        }
        tvClock.text = java.text.SimpleDateFormat("HH:mm", java.util.Locale.getDefault()).format(java.util.Date())
        updatePlayIcon()
    }

    /** Mostra os controles (qualquer tecla); somem em ~4 s se estiver tocando, ficam na tela durante a pausa. */
    private fun showInfo() {
        refreshOverlay()
        tvOverlay.visibility = View.VISIBLE
        handler.removeCallbacks(hideOverlay)
        handler.postDelayed(hideOverlay, 4000)
    }

    /** Dentro do que já existe (direct, ou trecho HLS gerado) busca na hora e a bolinha anda junto; fora dele espera 600 ms da última tecla e reinicia a sessão. */
    private fun skip(delta: Int) {
        val base = tvSeekTarget ?: absPos()
        val t = if (duration > 1) (base + delta).coerceIn(0.0, duration - 1) else maxOf(0.0, base + delta)
        showInfo()
        handler.removeCallbacks(applySeek)
        if (inRange(t)) {
            tvSeekTarget = null
            seekTo(t)
            refreshOverlay()
        } else {
            tvSeekTarget = t
            refreshOverlay()
            handler.postDelayed(applySeek, 600)
        }
    }

    /** Estado barra (43.7): ←/→ só movem a bolinha; a busca é aplicada com OK. */
    private fun moveBar(delta: Int) {
        val base = tvSeekTarget ?: absPos()
        val t = if (duration > 1) (base + delta).coerceIn(0.0, duration - 1) else maxOf(0.0, base + delta)
        tvSeekTarget = t
        tvBarPending = true
        handler.removeCallbacks(applySeek)
        showInfo()
    }

    private fun applyBar() {
        val t = tvSeekTarget
        showInfo()
        if (t == null || !tvBarPending) return
        tvBarPending = false
        handler.removeCallbacks(applySeek)
        if (inRange(t)) tvSeekTarget = null
        seekTo(t)
        refreshOverlay()
    }

    private fun inRange(t: Double): Boolean {
        val p = player ?: return false
        if (loading) return false
        if (!hls) return true
        val local = t - offset
        val d = p.duration
        val generated = (if (d != C.TIME_UNSET) d else p.bufferedPosition) / 1000.0
        return local >= 0 && local < generated - 6
    }

    private fun togglePlay() {
        val p = player ?: return
        if (p.isPlaying) p.pause() else p.play()
        showInfo()
    }

    /** Controles (43.7), três estados — fora: ←/→ pulam 10 s, OK pausa/play, ↑ ícones, ↓ barra; ícones: ←/→ trocam, OK abre, ↓ volta; barra: bolinha visível, ←/→ movem, OK aplica, ↑ volta; Voltar → fora. */
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        val e = event  // 54.6: o nome do parâmetro tem de ser `event` (igual ao da superclasse)
        if (!tv) return super.dispatchKeyEvent(e)
        if (sheet?.isOpen == true || queueIsOpen()) {  // 57.13: folha ou fila aberta: as setas/OK navegam pelos itens, Voltar desempilha/fecha
            if (e.keyCode == KeyEvent.KEYCODE_BACK || e.keyCode == KeyEvent.KEYCODE_ESCAPE) {
                if (e.action == KeyEvent.ACTION_UP) { if (queueIsOpen()) closeQueue() else sheet?.back() }
                return true
            }
            return super.dispatchKeyEvent(e)
        }
        // 57.22: com o botão Pular abertura / Próximo Episódio na tela, OK aciona o botão
        if (markVisible() && (e.keyCode == KeyEvent.KEYCODE_DPAD_CENTER || e.keyCode == KeyEvent.KEYCODE_ENTER)) {
            if (e.action == KeyEvent.ACTION_DOWN && e.repeatCount == 0) { if (btnNextEp.visibility == View.VISIBLE) doNextEp() else doSkipIntro() }
            return true
        }
        if (e.keyCode == KeyEvent.KEYCODE_BACK || e.keyCode == KeyEvent.KEYCODE_ESCAPE) {
            // 57.20: 1º Voltar esconde os controles (em qualquer estado); só com eles escondidos o Voltar sai da reprodução. 57.22: inclui os botões de abertura/próximo episódio
            if (tvOverlay.visibility == View.VISIBLE || markVisible()) {
                if (e.action == KeyEvent.ACTION_UP) {
                    if (btnNextEp.visibility == View.VISIBLE) nextHidden = true
                    if (btnSkipIntro.visibility == View.VISIBLE) introHidden = true
                    showMark(false, false)
                    hideTvOverlay()
                }
                return true
            }
            return super.dispatchKeyEvent(e)
        }
        val handled = when (e.keyCode) {
            KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE, KeyEvent.KEYCODE_MEDIA_PLAY,
            KeyEvent.KEYCODE_MEDIA_PAUSE, KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.KEYCODE_DPAD_RIGHT, KeyEvent.KEYCODE_DPAD_UP,
            KeyEvent.KEYCODE_DPAD_DOWN, KeyEvent.KEYCODE_MEDIA_REWIND, KeyEvent.KEYCODE_MEDIA_FAST_FORWARD, KeyEvent.KEYCODE_MEDIA_STOP -> true
            else -> false
        }
        if (!handled) return super.dispatchKeyEvent(e)
        if (e.action != KeyEvent.ACTION_DOWN) return true
        val long = e.repeatCount >= 3
        val hidden = tvOverlay.visibility != View.VISIBLE
        when (e.keyCode) {
            KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER -> if (e.repeatCount == 0) {
                when {
                    hidden || tvFocus == 0 -> togglePlay()
                    tvFocus == 3 -> applyBar()
                    tvFocus == 1 -> openSubsSheet()
                    else -> openSettingsSheet()
                }
            }
            KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE -> if (e.repeatCount == 0) togglePlay()
            KeyEvent.KEYCODE_MEDIA_PLAY -> { player?.play(); showInfo() }
            KeyEvent.KEYCODE_MEDIA_PAUSE -> { player?.pause(); showInfo() }
            KeyEvent.KEYCODE_DPAD_LEFT -> when {
                !hidden && (tvFocus == 1 || tvFocus == 2) -> { setTvFocus(1); showInfo() }
                !hidden && tvFocus == 3 -> moveBar(if (long) -30 else -10)
                else -> skip(if (long) -30 else -10)
            }
            KeyEvent.KEYCODE_DPAD_RIGHT -> when {
                !hidden && (tvFocus == 1 || tvFocus == 2) -> { setTvFocus(2); showInfo() }
                !hidden && tvFocus == 3 -> moveBar(if (long) 30 else 10)
                else -> skip(if (long) 30 else 10)
            }
            KeyEvent.KEYCODE_MEDIA_REWIND -> skip(-30)
            KeyEvent.KEYCODE_MEDIA_FAST_FORWARD -> skip(30)
            KeyEvent.KEYCODE_DPAD_UP -> { if (tvFocus == 0) setTvFocus(1) else if (tvFocus == 3) setTvFocus(0); showInfo() }
            KeyEvent.KEYCODE_DPAD_DOWN -> {
                if (tvFocus == 3 && queueItems.isNotEmpty()) openQueue()  // 57.13: ↓ na barra de tempo abre os próximos episódios
                else { if (tvFocus == 0) setTvFocus(3) else setTvFocus(0); showInfo() }
            }
            KeyEvent.KEYCODE_MEDIA_STOP -> finish()
        }
        return true
    }

    private val tick = object : Runnable {
        override fun run() {
            if (player?.isPlaying == true && System.currentTimeMillis() - lastSave >= 10000) save()
            if (!tv && mOverlay.visibility == View.VISIBLE) refreshM()
            if (cues.isNotEmpty()) {
                val t = absPos()
                val c = cues.firstOrNull { t >= it.start && t <= it.end }
                if (c == null) subtitle.visibility = View.GONE
                else {
                    if (subtitle.text.toString() != c.text) subtitle.text = c.text
                    subtitle.visibility = View.VISIBLE
                }
            }
            if (tv && tvOverlay.visibility == View.VISIBLE && tvSeekTarget == null) refreshOverlay()
            updateMarkers()
            handler.postDelayed(this, 250)
        }
    }

    /** 60.7: grava a posição já ao sair da tela (antes de o site/TV recarregarem o Início); o onStop repete por segurança. */
    override fun onPause() {
        super.onPause()
        save()
    }

    override fun onStop() {
        super.onStop()
        player?.pause()
        save()
        if (inPip) finish()  // 55.9: fechar a janela do PiP encerra como o ✕ (expandir de volta não passa por aqui)
    }

    override fun onDestroy() {
        if (inPip) try { unregisterReceiver(pipReceiver) } catch (_: Exception) { }
        handler.removeCallbacksAndMessages(null)
        player?.release()
        player = null
        stopSession(sid)
        super.onDestroy()
    }

    companion object {
        const val ACTION_PIP_TOGGLE = "com.starflix.app.PIP_TOGGLE"
        const val EXTRA_KIND = "kind"
        const val EXTRA_ID = "id"
        const val EXTRA_START = "start"
        const val EXTRA_TV = "tv"
        const val EXTRA_SERVER = "tv_server"
        const val EXTRA_TOKEN = "tv_token"
        const val EXTRA_PROFILE = "tv_profile"
        const val RESULT_UNAUTHORIZED = 401  // token da TV revogado: a TvActivity volta ao pareamento
    }
}
