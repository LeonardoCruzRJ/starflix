package com.starflix.app

import androidx.compose.foundation.focusGroup
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.border
import androidx.compose.animation.Crossfade
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.tv.material3.Border
import androidx.tv.material3.Card
import androidx.tv.material3.CardDefaults
import androidx.tv.material3.ExperimentalTvMaterial3Api
import androidx.tv.material3.NavigationDrawer
import androidx.tv.material3.NavigationDrawerItem
import androidx.tv.material3.Text
import coil.compose.AsyncImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONObject

data class TvCard(
    val type: String, val id: Long, val title: String, val sub: String, val image: String,
    val pct: Int, val watched: Boolean, val wide: Boolean, val play: String?, val mediaId: Long, val n: Int = 0,
)

data class TvRow(val key: String, val title: String, val items: List<TvCard>)
data class TvLib(val id: Long, val name: String, val type: String)
data class TvHero(
    val overview: String, val backdrop: String?, val logo: String? = null, val subtitle: String = "", val meta: String = "", val rating: String = "",
)

sealed class HomeResult {
    data class Ok(val rows: List<TvRow>, val libs: List<TvLib>) : HomeResult()
    object Unauthorized : HomeResult()
    data class Err(val msg: String) : HomeResult()
}

/** Início da TV (40.10): `/api/tv/home`, `/api/tv/libraries` e detalhes do item em foco. */
object TvHomeApi {
    private fun JSONObject.str(k: String): String = if (isNull(k)) "" else optString(k, "")

    fun parseCard(o: JSONObject): TvCard {
        var sub = o.str("sub")
        if (!o.isNull("season") && o.has("episode") && !o.isNull("episode")) {
            val ep = "T${o.optInt("season")} · E${o.optInt("episode")}"
            sub = if (sub.isEmpty()) ep else "$ep — $sub"
        }
        return TvCard(
            type = o.optString("type", "movie"), id = o.optLong("id"), title = o.str("title"), sub = sub, image = o.str("image"),
            pct = o.optInt("pct"), watched = o.optBoolean("watched"), wide = o.optBoolean("wide"),
            play = o.str("play").ifEmpty { null }, mediaId = o.optLong("media_id"),
        )
    }

    /** Bibliotecas fixadas do menu lateral; null se falhar (o menu mantém a lista anterior). */
    fun libraries(server: String, token: String, profile: Long): List<TvLib>? = try {
        val (c, j) = TvApi.authed("GET", server, "/api/tv/libraries", token, profile)
        val la = if (c == 200) j?.optJSONArray("libraries") else null
        if (la == null) null else (0 until la.length()).map { i ->
            val l = la.getJSONObject(i)
            TvLib(l.optLong("id"), l.optString("name"), l.optString("type"))
        }
    } catch (e: Exception) {
        null
    }

    fun home(server: String, token: String, profile: Long): HomeResult = try {
        val (code, j) = TvApi.authed("GET", server, "/api/tv/home", token, profile)
        if (code != 200 || j == null) HomeResult.Err("Erro do servidor ($code).") else {
            val ra = j.optJSONArray("rows")
            val rows = (0 until (ra?.length() ?: 0)).mapNotNull { i ->
                val r = ra!!.getJSONObject(i)
                val ia = r.optJSONArray("items")
                val items = (0 until (ia?.length() ?: 0)).map { parseCard(ia!!.getJSONObject(it)) }
                if (items.isEmpty()) null else TvRow(r.optString("key"), r.optString("title"), items)
            }
            val (c2, j2) = TvApi.authed("GET", server, "/api/tv/libraries", token, profile)
            val la = if (c2 == 200) j2?.optJSONArray("libraries") else null
            val libs = (0 until (la?.length() ?: 0)).map { i ->
                val l = la!!.getJSONObject(i)
                TvLib(l.optLong("id"), l.optString("name"), l.optString("type"))
            }
            HomeResult.Ok(rows, libs)
        }
    } catch (e: TvUnauthorized) {
        HomeResult.Unauthorized
    } catch (e: Exception) {
        HomeResult.Err("Servidor inacessível.")
    }

    private fun JSONObject.dateBr(k: String): String {
        val raw = str(k)
        if (raw.isEmpty()) return ""
        return try {
            val d = java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.US).parse(raw.take(10))!!
            java.text.SimpleDateFormat("d 'de' MMM 'de' yyyy", java.util.Locale("pt", "BR")).format(d)
        } catch (e: Exception) { raw }
    }

    private fun minutes(sec: Double): String {
        val m = Math.round(sec / 60.0).toInt()
        return if (m <= 0) "" else if (m >= 60) "${m / 60}h ${m % 60} min" else "$m min"
    }

    /** Destaque do item em foco (43.2): backdrop, logo, subtítulo, linha de metadados, classificação e sinopse. Episódio usa a série + o próprio episódio. Falha = sem destaque. */
    fun hero(server: String, token: String, profile: Long, c: TvCard): TvHero? = try {
        val path = when (c.type) {
            "movie" -> "/api/tv/movie/${c.id}"
            "show" -> "/api/tv/show/${c.id}"
            "episode" -> if (c.mediaId > 0) "/api/tv/show/${c.mediaId}" else null
            "collection" -> "/api/tv/collection/${c.id}"
            else -> null
        }
        if (path == null) null else {
            val (code, j) = TvApi.authed("GET", server, path, token, profile)
            if (code != 200 || j == null) null else {
                val im = j.optJSONObject("images")
                val col = c.type == "collection"  // a coleção traz backdrop/logo no topo do JSON, não em `images`
                val bd = if (col) j.str("backdrop") else im?.str("backdrop").orEmpty().ifEmpty { im?.str("poster").orEmpty() }
                val logo = if (col) j.str("logo") else im?.str("logo").orEmpty()
                val rating = j.str("content_rating")
                val parts = mutableListOf<String>()
                var overview = j.str("overview")
                var sub = ""
                if (c.type == "episode") {
                    val (c2, e) = TvApi.authed("GET", server, "/api/tv/episode/${c.id}", token, profile)
                    if (c2 == 200 && e != null) {
                        parts.add("T${e.optInt("season")} • E${e.optInt("episode")}")
                        e.dateBr("air_date").let { if (it.isNotEmpty()) parts.add(it) }
                        minutes(e.optDouble("duration", 0.0)).let { if (it.isNotEmpty()) parts.add(it) }
                        sub = e.str("title")
                        e.str("overview").let { if (it.isNotEmpty()) overview = it }
                    }
                } else if (col) {
                    val n = j.optJSONArray("items")?.length() ?: 0
                    parts.add(if (n == 1) "Coleção · 1 item" else "Coleção · $n itens")
                } else {
                    if (!j.isNull("year") && j.optInt("year") > 0) parts.add(j.optInt("year").toString())
                    if (c.type == "movie") minutes(j.optDouble("duration", 0.0)).let { if (it.isNotEmpty()) parts.add(it) }
                    sub = j.str("tagline")
                }
                TvHero(overview, bd.ifEmpty { null }, logo.ifEmpty { null }, sub, parts.joinToString("  "), rating)
            }
        }
    } catch (e: TvUnauthorized) {
        throw e
    } catch (e: Exception) {
        null
    }
}

private val BG = Color(0xFF1F2326)
private val ACCENT = Color(0xFFE5A00D)
private val TEXT = Color(0xFFEEEEEE)
private val MUTED = Color(0xFF9A9EA3)

@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
internal fun PosterCard(server: String, c: TvCard, onFocus: (TvCard) -> Unit, onOpen: (TvCard) -> Unit, modifier: Modifier = Modifier, width: androidx.compose.ui.unit.Dp? = null) {
    // `width` (grade do Explorar): cartão menor e texto centralizado; sem ele, os tamanhos das fileiras
    val w = width ?: if (c.wide) 260.dp else 140.dp
    val h = if (width != null) (if (c.wide) w * 0.5625f else w * 1.5f) else if (c.wide) 146.dp else 210.dp
    val al = if (width != null) androidx.compose.ui.text.style.TextAlign.Center else androidx.compose.ui.text.style.TextAlign.Start
    Column(modifier.width(w)) {
        Card(
            onClick = { onOpen(c) },
            modifier = Modifier.size(w, h).onFocusChanged { if (it.isFocused) onFocus(c) },
            shape = CardDefaults.shape(RoundedCornerShape(8.dp)),
            scale = CardDefaults.scale(focusedScale = 1.08f),
            border = CardDefaults.border(focusedBorder = Border(BorderStroke(3.dp, ACCENT))),
        ) {
            Box(Modifier.fillMaxSize().background(Color(0xFF2F3236))) {
                if (c.image.isNotEmpty()) {
                    RetryAsyncImage(model = server + c.image, contentDescription = c.title, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                }
                if (c.watched) Text("✓", color = Color.Black, fontSize = 14.sp, fontWeight = FontWeight.Bold,
                    modifier = Modifier.align(Alignment.TopEnd).padding(6.dp).background(ACCENT, RoundedCornerShape(4.dp)).padding(horizontal = 6.dp))
                if (c.pct in 1..99) Box(Modifier.align(Alignment.BottomStart).fillMaxWidth(c.pct / 100f).height(4.dp).background(ACCENT))
            }
        }
        Text(c.title, color = TEXT, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, textAlign = al, modifier = Modifier.fillMaxWidth().padding(top = 6.dp))
        if (c.sub.isNotEmpty()) Text(c.sub, color = MUTED, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, textAlign = al, modifier = Modifier.fillMaxWidth())
    }
}

/**
 * Início nativo (40.10): menu lateral recolhível (Início, bibliotecas, Busca, Minha Lista, Trocar perfil, Sair), fileiras de `/api/tv/home`
 * com foco visível e destaque (backdrop, título e sinopse) do item focado. 401 → `onUnauthorized`. Bibliotecas, busca, Minha Lista e
 * detalhes chamam `onNavigate`/`onOpen` (telas das etapas 40.11 a 40.13).
 */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun HomeScreen(
    server: String, token: String, profileId: Long,
    onOpen: (TvCard) -> Unit, onNavigate: (String) -> Unit,
    onSwitchProfile: () -> Unit, onDisconnect: () -> Unit, onUnauthorized: () -> Unit,
    restoreKey: String? = null, onFocusKey: (String) -> Unit = {}, onExit: () -> Unit = {}, refresh: Int = 0,
    profileName: String = "", profileColor: String = "", profilePhoto: String = "", onLibs: (List<TvLib>) -> Unit = {},
) {
    var result by remember { mutableStateOf<HomeResult?>(null) }
    var reload by remember { mutableStateOf(0) }
    var focused by remember { mutableStateOf<TvCard?>(null) }
    var hero by remember { mutableStateOf<TvHero?>(null) }
    val first = remember { FocusRequester() }
    var tab by remember { mutableStateOf(0) }                                    // 0 = Recomendado, 1 = Explorar, 2 = Coleções
    var tabRows by remember { mutableStateOf<Map<Int, List<TvRow>>>(emptyMap()) }
    BackHandler { onExit() }  // Voltar no Início fecha o app; desconectar é o item do menu

    LaunchedEffect(reload, refresh) {
        result = null
        when (val r = withContext(Dispatchers.IO) { TvHomeApi.home(server, token, profileId) }) {
            is HomeResult.Unauthorized -> onUnauthorized()
            else -> { result = r; (r as? HomeResult.Ok)?.let { onLibs(it.libs) } }
        }
    }
    // Foco inicial: o último card focado (ao voltar de outra tela) ou o primeiro; o requester fica só em um card (1ª fileira que o contém)
    // `resetFocus` sobe ao trocar de aba ou ao clicar em Início na barra: o foco vai ao 1º item da aba (e o fundo acompanha); restoreKey vale só na entrada
    var resetFocus by remember { mutableStateOf(0) }
    val target: Pair<String, String>? = remember(result, tab, tabRows[tab], resetFocus) {
        val rows = if (tab == 0) (result as? HomeResult.Ok)?.rows.orEmpty() else tabRows[tab].orEmpty()
        val hit = if (tab == 0 && resetFocus == 0) restoreKey?.let { k -> rows.firstOrNull { r -> r.items.any { it.type + it.id == k } }?.let { it.key to k } } else null
        hit ?: rows.firstOrNull()?.takeIf { it.items.isNotEmpty() }?.let { it.key to (it.items.first().type + it.items.first().id) }
    }
    LaunchedEffect(target, resetFocus) {
        if (target != null) { delay(60); runCatching { first.requestFocus() } }
    }
    LaunchedEffect(focused) {
        val c = focused ?: return@LaunchedEffect
        delay(350)  // só busca quando o foco para
        hero = try { withContext(Dispatchers.IO) { TvHomeApi.hero(server, token, profileId, c) } } catch (e: TvUnauthorized) { onUnauthorized(); null }
    }

    val ok = result as? HomeResult.Ok
    // Explorar = uma fileira por biblioteca; Coleções = coleções de cada biblioteca (carregadas ao abrir a aba)
    LaunchedEffect(tab, ok?.libs) {
        val libsNow = ok?.libs ?: return@LaunchedEffect
        if (tab == 0 || tabRows.containsKey(tab)) return@LaunchedEffect
        try {
            val rows = withContext(Dispatchers.IO) {
                libsNow.mapNotNull { l ->
                    if (tab == 1) {
                        val r = TvLibraryApi.page(server, token, profileId, l.id, 0, null)
                        (r as? LibResult.Ok)?.items?.takeIf { it.isNotEmpty() }?.let { TvRow("x:${l.id}", l.name, it.take(40)) }
                    } else {
                        TvLibraryApi.collections(server, token, profileId, l.id).takeIf { it.isNotEmpty() }?.let { TvRow("c:${l.id}", "Coleções em ${l.name}", it) }
                    }
                }
            }
            tabRows = tabRows + (tab to rows)
        } catch (e: TvUnauthorized) { onUnauthorized() }
    }
    val shownRows = if (tab == 0) ok?.rows.orEmpty() else tabRows[tab]
    TvDrawer(
        libs = ok?.libs.orEmpty(), selected = "home", server = server, profileName = profileName, profileColor = profileColor, profilePhoto = profilePhoto,
        onNavigate = { dest -> if (dest != "home") onNavigate(dest) else { tab = 0; resetFocus++ } }, onSwitchProfile = onSwitchProfile, onDisconnect = onDisconnect,
    ) {
        Box(Modifier.fillMaxSize().background(BG)) {
            HeroBackdrop(server, hero?.backdrop)
            when {
                result == null -> Text("Carregando…", color = MUTED, fontSize = 20.sp, modifier = Modifier.align(Alignment.Center))
                result is HomeResult.Err -> Column(Modifier.align(Alignment.Center), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text((result as HomeResult.Err).msg, color = Color(0xFFE57373), fontSize = 20.sp)
                    Spacer(Modifier.height(16.dp))
                    Card(onClick = { reload++ }, modifier = Modifier.width(260.dp).focusRequester(first)) {
                        Text("Tentar de novo", color = TEXT, fontSize = 20.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(16.dp))
                    }
                }
                ok != null && ok.rows.isEmpty() && tab == 0 -> Text("Nada por aqui ainda. Adicione uma biblioteca no site.", color = MUTED, fontSize = 20.sp, modifier = Modifier.align(Alignment.Center))
                ok != null -> Column(Modifier.fillMaxSize().padding(start = 24.dp + DRAWER_INSET, top = 16.dp)) {
                    val c = focused
                    HomeTabs(tab) { tab = it; resetFocus++ }
                    Column(Modifier.height(190.dp).width(640.dp).padding(top = 8.dp)) {
                        val logo = hero?.logo
                        if (logo != null) RetryAsyncImage(model = server + logo, contentDescription = c?.title, contentScale = ContentScale.Fit,
                            alignment = Alignment.CenterStart, modifier = Modifier.height(72.dp).width(320.dp))
                        else Text(c?.title ?: "StarFlix", color = TEXT, fontSize = 36.sp, fontWeight = FontWeight.Black, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        val sub = hero?.subtitle.orEmpty().ifEmpty { if (logo != null) "" else c?.sub.orEmpty() }
                        if (sub.isNotEmpty()) Text(sub, color = TEXT, fontSize = 18.sp, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 4.dp)) {
                            Text(hero?.meta.orEmpty(), color = MUTED, fontSize = 12.sp, maxLines = 1)
                            if (!hero?.rating.isNullOrEmpty()) Text(hero!!.rating, color = TEXT, fontSize = 11.sp, fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(start = 8.dp).background(Color(0xFF000000), RoundedCornerShape(3.dp)).padding(horizontal = 5.dp, vertical = 1.dp))
                        }
                        Text(hero?.overview.orEmpty(), color = TEXT, fontSize = 13.sp, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 8.dp))
                    }
                    if (shownRows == null) Text("Carregando…", color = MUTED, fontSize = 18.sp, modifier = Modifier.padding(top = 24.dp, start = 12.dp))
                    else if (shownRows.isEmpty()) Text(if (tab == 2) "Nenhuma coleção ainda." else "Nada por aqui ainda.", color = MUTED, fontSize = 18.sp, modifier = Modifier.padding(top = 24.dp, start = 12.dp))
                    else LazyColumn(verticalArrangement = Arrangement.spacedBy(18.dp), modifier = Modifier.fillMaxSize()) {
                        items(shownRows, key = { it.key }) { row ->
                            Column {
                                Text(row.title, color = TEXT, fontSize = 20.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(bottom = 8.dp))
                                                                val rs = androidx.compose.foundation.lazy.rememberLazyListState()
                                val fr = remember { FocusRequester() }
                                RowEnter(fr, rs) { LazyRow(state = rs, horizontalArrangement = Arrangement.spacedBy(14.dp), contentPadding = androidx.compose.foundation.layout.PaddingValues(start = 12.dp, end = 48.dp, top = 12.dp, bottom = 14.dp)) {
                                    items(row.items, key = { it.type + it.id }) { card ->
                                        val isTarget = target?.first == row.key && target.second == card.type + card.id
                                        PosterCard(server, card, onFocus = { focused = it; onFocusKey(it.type + it.id) }, onOpen = onOpen,
                                            modifier = (if (isTarget) Modifier.focusRequester(first) else Modifier).let { if (card === row.items.first()) it.focusRequester(fr) else it })
                                    }
                                } }
                            }
                        }
                    }
                }
            }
        }
    }
}

/** Abas do topo (43.2, revisão): focáveis (↑ a partir da 1ª fileira) e com função; a atual tem borda clara. Relógio do aparelho no canto direito. */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
internal fun HomeTabs(tab: Int, onTab: (Int) -> Unit) {
    val reqs = remember { List(3) { FocusRequester() } }
    Row(Modifier.fillMaxWidth().padding(end = 32.dp), verticalAlignment = Alignment.CenterVertically) {
        PillGroup(reqs[tab.coerceIn(0, 2)]) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                LibTab("Recomendado", tab == 0, { onTab(0) }, Modifier.focusRequester(reqs[0]))
                LibTab("Explorar", tab == 1, { onTab(1) }, Modifier.focusRequester(reqs[1]))
                LibTab("Coleções", tab == 2, { onTab(2) }, Modifier.focusRequester(reqs[2]))
            }
        }
        Spacer(Modifier.weight(1f))
        TvClock()
    }
}

@Composable
internal fun TvClock() {
    var now by remember { mutableStateOf(java.util.Date()) }
    LaunchedEffect(Unit) { while (true) { now = java.util.Date(); delay(20_000) } }
    Text(java.text.SimpleDateFormat("HH:mm", java.util.Locale.getDefault()).format(now), color = TEXT, fontSize = 13.sp,
        modifier = Modifier.background(Color(0x66000000), RoundedCornerShape(50)).padding(horizontal = 12.dp, vertical = 4.dp))
}

private val bgCache = HashMap<String, Color>()
private val DEFAULT_BG = Color(0xFF1F2326)

/** Cor vibrante dominante do backdrop (como o original faz): agrupa os pixels por matiz, pesa por saturação × brilho e garante cor viva. */
private suspend fun dominantColor(ctx: android.content.Context, url: String): Color? = withContext(Dispatchers.IO) {
    val req = coil.request.ImageRequest.Builder(ctx).data(url).allowHardware(false).size(64, 36).build()
    val res = coil.Coil.imageLoader(ctx).execute(req) as? coil.request.SuccessResult ?: return@withContext null
    val bmp = (res.drawable as? android.graphics.drawable.BitmapDrawable)?.bitmap ?: return@withContext null
    val w = FloatArray(24); val r = FloatArray(24); val g = FloatArray(24); val b = FloatArray(24)
    val hsv = FloatArray(3)
    for (y in 0 until bmp.height) for (x in 0 until bmp.width) {
        val px = bmp.getPixel(x, y)
        android.graphics.Color.colorToHSV(px, hsv)
        if (hsv[1] < 0.25f || hsv[2] < 0.25f) continue
        val k = (hsv[0] / 15f).toInt().coerceIn(0, 23)
        val wt = hsv[1] * hsv[2]
        w[k] += wt
        r[k] += wt * android.graphics.Color.red(px); g[k] += wt * android.graphics.Color.green(px); b[k] += wt * android.graphics.Color.blue(px)
    }
    var best = -1
    for (k in 0 until 24) if (w[k] > 1f && (best < 0 || w[k] > w[best])) best = k
    if (best < 0) return@withContext null
    android.graphics.Color.RGBToHSV((r[best] / w[best]).toInt(), (g[best] / w[best]).toInt(), (b[best] / w[best]).toInt(), hsv)
    hsv[1] = hsv[1].coerceAtLeast(0.6f)
    hsv[2] = hsv[2].coerceIn(0.5f, 0.78f)
    Color(android.graphics.Color.HSVToColor(hsv))
}

/** Fundo do herói (43.2, revisão 2): preenchimento com a cor vibrante pescada do backdrop (degradê vertical, troca animada) + imagem só no canto superior direito, com transparência (esmaece à esquerda e embaixo). */
@Composable
internal fun HeroBackdrop(server: String, backdrop: String?) {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    var target by remember { mutableStateOf(DEFAULT_BG) }
    LaunchedEffect(backdrop) {
        if (backdrop == null) return@LaunchedEffect
        val key = server + backdrop
        target = bgCache[key] ?: (dominantColor(ctx, key) ?: DEFAULT_BG).also { bgCache[key] = it }
    }
    val c by androidx.compose.animation.animateColorAsState(target, androidx.compose.animation.core.tween(600), label = "heroBg")
    Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(c, androidx.compose.ui.graphics.lerp(c, Color.Black, 0.4f))))) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopEnd) {
            Crossfade(
                targetState = backdrop,
                modifier = Modifier.fillMaxWidth(0.72f).fillMaxHeight(0.72f)
                    .graphicsLayer { compositingStrategy = CompositingStrategy.Offscreen }
                    .drawWithContent {
                        drawContent()
                        drawRect(Brush.horizontalGradient(0f to Color.Transparent, 0.45f to Color.Black), blendMode = BlendMode.DstIn)
                        drawRect(Brush.verticalGradient(0.5f to Color.Black, 1f to Color.Transparent), blendMode = BlendMode.DstIn)
                    },
            ) { bd ->
                if (bd != null) RetryAsyncImage(model = server + bd, contentDescription = null, contentScale = ContentScale.Crop, alignment = Alignment.TopCenter, modifier = Modifier.fillMaxSize())
            }
        }
    }
}

/** Bloco de texto do destaque: logo (ou nome), subtítulo, metadados, classificação e sinopse. */
@Composable
internal fun HeroInfo(server: String, c: TvCard?, hero: TvHero?) {
    Column(Modifier.height(190.dp).width(640.dp).padding(top = 8.dp)) {
        val logo = hero?.logo
        if (logo != null) RetryAsyncImage(model = server + logo, contentDescription = c?.title, contentScale = ContentScale.Fit,
            alignment = Alignment.CenterStart, modifier = Modifier.height(72.dp).width(320.dp))
        else Text(c?.title ?: "StarFlix", color = TEXT, fontSize = 36.sp, fontWeight = FontWeight.Black, maxLines = 1, overflow = TextOverflow.Ellipsis)
        val sub = hero?.subtitle.orEmpty().ifEmpty { if (logo != null) "" else c?.sub.orEmpty() }
        if (sub.isNotEmpty()) Text(sub, color = TEXT, fontSize = 18.sp, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 4.dp)) {
            Text(hero?.meta.orEmpty(), color = MUTED, fontSize = 12.sp, maxLines = 1)
            if (!hero?.rating.isNullOrEmpty()) Text(hero!!.rating, color = TEXT, fontSize = 11.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(start = 8.dp).background(Color(0xFF000000), RoundedCornerShape(3.dp)).padding(horizontal = 5.dp, vertical = 1.dp))
        }
        Text(hero?.overview.orEmpty(), color = TEXT, fontSize = 13.sp, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 8.dp))
    }
}
