package com.starflix.app

import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.type
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.foundation.focusGroup
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.tv.material3.Border
import androidx.tv.material3.Card
import androidx.tv.material3.CardDefaults
import androidx.tv.material3.ExperimentalTvMaterial3Api
import androidx.compose.ui.text.style.TextOverflow
import kotlinx.coroutines.delay
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.tv.material3.Text
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.URLEncoder

data class LibView(val sort: String, val dir: String, val filter: String, val genre: String)

sealed class LibResult {
    data class Ok(val name: String, val view: LibView, val genres: List<String>, val total: Int, val items: List<TvCard>) : LibResult()
    object Unauthorized : LibResult()
    data class Err(val msg: String) : LibResult()
}

/** Biblioteca da TV (40.11): `/api/tv/library/<id>` paginada, ordem e filtros salvos por perfil (mesma tabela do site). */
object TvLibraryApi {
    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    fun page(server: String, token: String, profile: Long, id: Long, offset: Int, v: LibView?): LibResult = try {
        var path = "/api/tv/library/$id?offset=$offset&limit=60"
        if (v != null) path += "&sort=${enc(v.sort)}&dir=${enc(v.dir)}&filter=${enc(v.filter)}&genre=${enc(v.genre)}"
        val (code, j) = TvApi.authed("GET", server, path, token, profile)
        if (code != 200 || j == null) LibResult.Err(if (code == 404) "Biblioteca indisponível." else "Erro do servidor ($code).") else {
            val vw = j.getJSONObject("view")
            val ga = j.optJSONArray("genres")
            val ia = j.optJSONArray("items")
            LibResult.Ok(
                name = j.optJSONObject("library")?.optString("name").orEmpty(),
                view = LibView(vw.optString("sort"), vw.optString("dir"), vw.optString("filter"), vw.optString("genre")),
                genres = (0 until (ga?.length() ?: 0)).map { ga!!.getString(it) },
                total = j.optInt("total"),
                items = (0 until (ia?.length() ?: 0)).map { TvHomeApi.parseCard(ia!!.getJSONObject(it)) },
            )
        }
    } catch (e: TvUnauthorized) {
        LibResult.Unauthorized
    } catch (e: Exception) {
        LibResult.Err("Servidor inacessível.")
    }

    /** Coleções da biblioteca (aba Coleções do Início): `/api/tv/library/<id>/collections`; falha = lista vazia (401 sobe). */
    fun collections(server: String, token: String, profile: Long, id: Long): List<TvCard> = try {
        val (code, j) = TvApi.authed("GET", server, "/api/tv/library/$id/collections", token, profile)
        val ia = if (code == 200) j?.optJSONArray("items") else null
        (0 until (ia?.length() ?: 0)).map { TvHomeApi.parseCard(ia!!.getJSONObject(it)) }
    } catch (e: TvUnauthorized) {
        throw e
    } catch (e: Exception) {
        emptyList()
    }

    /** Grava a escolha do perfil (vale também no site); falha é ignorada. */
    fun saveView(server: String, token: String, profile: Long, id: Long, v: LibView) {
        try {
            val body = JSONObject().put("sort", v.sort).put("dir", v.dir).put("filter", v.filter).put("genre", v.genre).toString()
            TvApi.authed("POST", server, "/library/$id/view-prefs", token, profile, body)
        } catch (e: Exception) {
        }
    }
}

private val BG = Color(0xFF1F2326)
private val ACCENT = Color(0xFFE5A00D)
private val TEXT = Color(0xFFEEEEEE)
private val MUTED = Color(0xFF9A9EA3)

private val SORTS = listOf(
    Triple("title", "asc", "Título"), Triple("year", "desc", "Ano"),
    Triple("added", "desc", "Adicionado em"), Triple("played", "desc", "Último assistido"),
)
private val FILTER_SHORT = listOf("Tudo", "Não assistidos", "Assistidos", "Em andamento")
private val FILTERS = listOf("all" to "Todos", "unwatched" to "Não assistidos", "watched" to "Assistidos", "progress" to "Em andamento")

/** Chip pequeno da barra do Explorar (filtro, gênero, ordem, ⋮); foco com borda laranja. */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun ToolChip(label: String, onClick: () -> Unit, modifier: Modifier = Modifier, lead: (@Composable () -> Unit)? = null) {
    Card(
        onClick = onClick, modifier = modifier, shape = CardDefaults.shape(RoundedCornerShape(50)),
        colors = CardDefaults.colors(containerColor = Color(0x40FFFFFF)),
        border = CardDefaults.border(focusedBorder = Border(BorderStroke(2.dp, ACCENT))),
    ) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 5.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            lead?.invoke()
            if (label.isNotEmpty()) Text(label, color = TEXT, fontSize = 12.sp, maxLines = 1)
        }
    }
}

/** Seta da direção da ordem (↓ crescente, ↑ decrescente), desenhada (as fontes da TV não têm a seta). */
@Composable
private fun DirIcon(down: Boolean) {
    androidx.compose.foundation.Canvas(Modifier.size(12.dp)) {
        val w = size.width
        val h = size.height
        val sw = 1.6.dp.toPx()
        val tip = if (down) h * 0.9f else h * 0.1f
        val back = if (down) h * 0.55f else h * 0.45f
        drawLine(TEXT, androidx.compose.ui.geometry.Offset(w / 2, h * 0.1f), androidx.compose.ui.geometry.Offset(w / 2, h * 0.9f), sw)
        drawLine(TEXT, androidx.compose.ui.geometry.Offset(w / 2, tip), androidx.compose.ui.geometry.Offset(w * 0.15f, back), sw)
        drawLine(TEXT, androidx.compose.ui.geometry.Offset(w / 2, tip), androidx.compose.ui.geometry.Offset(w * 0.85f, back), sw)
    }
}

@Composable
private fun DotsIcon() {
    androidx.compose.foundation.Canvas(Modifier.size(12.dp)) {
        for (i in 0..2) drawCircle(TEXT, 1.5.dp.toPx(), androidx.compose.ui.geometry.Offset(size.width / 2, size.height * (0.15f + 0.35f * i)))
    }
}

/** Letra do índice alfabético: sem acento, A–Z; o resto vira "#". */
private fun letterOf(t: String): String {
    val n = java.text.Normalizer.normalize(t.trim(), java.text.Normalizer.Form.NFD).replace(Regex("\\p{M}+"), "")
    val c = n.firstOrNull()?.uppercaseChar() ?: return "#"
    return if (c in 'A'..'Z') c.toString() else "#"
}

/** Índice alfabético na borda direita: focar uma letra rola a grade até o primeiro item dela; a letra da posição atual fica circulada. */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun AlphaIndex(letters: List<String>, current: String, onJump: (String) -> Unit, modifier: Modifier = Modifier) {
    Column(modifier.width(34.dp), verticalArrangement = Arrangement.spacedBy(2.dp, Alignment.CenterVertically), horizontalAlignment = Alignment.CenterHorizontally) {
        letters.forEach { l ->
            val cur = l == current
            Card(
                onClick = { onJump(l) },
                modifier = Modifier.size(22.dp).onFocusChanged { if (it.hasFocus) onJump(l) },
                shape = CardDefaults.shape(androidx.compose.foundation.shape.CircleShape),
                colors = CardDefaults.colors(containerColor = Color.Transparent),
                border = CardDefaults.border(border = Border(BorderStroke(if (cur) 1.dp else 0.dp, if (cur) TEXT else Color.Transparent)), focusedBorder = Border(BorderStroke(2.dp, ACCENT))),
            ) { Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text(l, color = TEXT, fontSize = 11.sp) } }
        }
    }
}

/** Aba do topo da biblioteca (43.3): pílula; a atual tem borda clara. */
/** Teclado/linhas de botões: ↑/↓ de qualquer botão vai sempre ao 1º botão da linha vizinha (`req[r]` = 1º botão da linha r). */
@OptIn(ExperimentalComposeUiApi::class)
internal fun Modifier.rowNav(req: List<FocusRequester>, r: Int, i: Int): Modifier =
    this.focusProperties {
        up = if (r > 0) req[r - 1] else FocusRequester.Default
        down = if (r < req.size - 1) req[r + 1] else FocusRequester.Default
    }.let { if (i == 0) it.focusRequester(req[r]) else it }

/** Navegação de grade: ↓/↑ vão ao 1º card da linha seguinte/anterior; a 1ª linha deixa o ↑ seguir o padrão (barra de cima). */
internal class GridNav(val state: androidx.compose.foundation.lazy.grid.LazyGridState, private val scope: kotlinx.coroutines.CoroutineScope) {
    var cols = 1
    var total = 0
    private val reqs = HashMap<Int, FocusRequester>()
    fun req(i: Int) = reqs.getOrPut(i) { FocusRequester() }
    /** Colunas da `Adaptive(minSize)`: mesma conta do Compose, `(largura útil + espaço) / (mínimo + espaço)`. */
    fun measure(widthPx: Int, density: androidx.compose.ui.unit.Density, minDp: Float, spacingDp: Float, padDp: Float) {
        val avail = widthPx - padDp * density.density
        val sp = spacingDp * density.density
        cols = maxOf(((avail + sp) / (minDp * density.density + sp)).toInt(), 1)
    }
    private fun go(t: Int) {
        if (runCatching { req(t).requestFocus() }.isSuccess) return
        scope.launch {
            state.scrollToItem(t)
            androidx.compose.runtime.withFrameNanos { }
            androidx.compose.runtime.withFrameNanos { }
            runCatching { req(t).requestFocus() }
        }
    }
    fun item(i: Int): Modifier = Modifier.focusRequester(req(i)).onPreviewKeyEvent { e ->
        if (e.type != androidx.compose.ui.input.key.KeyEventType.KeyDown) false
        else when (e.key) {
            androidx.compose.ui.input.key.Key.DirectionDown -> { val t = (i / cols + 1) * cols; if (t < total) { go(t); true } else false }
            androidx.compose.ui.input.key.Key.DirectionUp -> { val r = i / cols; if (r > 0) { go((r - 1) * cols); true } else false }
            else -> false
        }
    }
}

/** Contêiner da grade: mede a largura (colunas) e, ao receber o foco por ↓/↑ de fora, foca o 1º card (se a grade está no topo). */
@OptIn(ExperimentalComposeUiApi::class)
@Composable
internal fun GridEnter(nav: GridNav, minDp: Float, spacingDp: Float, padDp: Float, modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val density = androidx.compose.ui.platform.LocalDensity.current
    Box(modifier.onSizeChanged { nav.measure(it.width, density, minDp, spacingDp, padDp) }
        .focusProperties {
            enter = { d -> if ((d == androidx.compose.ui.focus.FocusDirection.Down || d == androidx.compose.ui.focus.FocusDirection.Up) && nav.state.firstVisibleItemIndex == 0) nav.req(0) else FocusRequester.Default }
        }
        .focusGroup()) { content() }
}

/** Fileira de cards: ao receber o foco vindo de fora (↑ ou ↓) foca sempre o card `first`; ao perder o foco volta ao item `home` (0 por padrão) para o `first` estar sempre composto (57.28: `first` fora da tela derrubava o app). */
@OptIn(ExperimentalComposeUiApi::class)
@Composable
internal fun RowEnter(first: FocusRequester, state: androidx.compose.foundation.lazy.LazyListState, home: Int = 0, content: @Composable () -> Unit) {
    val sc = androidx.compose.runtime.rememberCoroutineScope()
    var had by remember { mutableStateOf(false) }
    Box(Modifier.focusProperties { enter = { first } }.focusGroup().onFocusChanged {
        if (it.hasFocus) had = true else if (had) { had = false; sc.launch { state.scrollToItem(home) } }
    }) { content() }
}

/** Grupo de pílulas: ao receber o foco vindo de fora (↑ do conteúdo) foca a pílula atual (`req`), nunca a primeira por padrão. */
@OptIn(ExperimentalComposeUiApi::class)
@Composable
internal fun PillGroup(req: FocusRequester?, modifier: Modifier = Modifier, onLeave: () -> Unit = {}, content: @Composable () -> Unit) {
    val m = if (req != null) Modifier.focusProperties { enter = { req } } else Modifier
    Box(modifier.then(m).focusGroup().onFocusChanged { if (!it.hasFocus) onLeave() }) { content() }
}

@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
internal fun LibTab(label: String, selected: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Card(
        onClick = onClick, modifier = modifier.padding(end = 10.dp), shape = CardDefaults.shape(RoundedCornerShape(50)),
        colors = CardDefaults.colors(containerColor = Color.Transparent),
        border = CardDefaults.border(border = Border(BorderStroke(if (selected) 1.dp else 0.dp, if (selected) TEXT else Color.Transparent)), focusedBorder = Border(BorderStroke(2.dp, ACCENT))),
    ) { Text(label, color = TEXT, fontSize = 13.sp, modifier = Modifier.padding(horizontal = 14.dp, vertical = 5.dp)) }
}

@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun LibraryScreen(
    server: String, token: String, profileId: Long, libId: Long, libName: String,
    onOpen: (TvCard) -> Unit, onBack: () -> Unit, onUnauthorized: () -> Unit,
    restoreKey: String? = null, onFocusKey: (String) -> Unit = {},
    libs: List<TvLib> = emptyList(), profileName: String = "", profileColor: String = "", profilePhoto: String = "",
    onNavigate: (String) -> Unit = {}, onSwitchProfile: () -> Unit = {}, onDisconnect: () -> Unit = {},
) {
    var view by remember { mutableStateOf<LibView?>(null) }   // null = ainda usa o salvo no servidor
    var items by remember { mutableStateOf<List<TvCard>>(emptyList()) }
    var total by remember { mutableStateOf(0) }
    var genres by remember { mutableStateOf<List<String>>(emptyList()) }
    var name by remember { mutableStateOf(libName) }
    var error by remember { mutableStateOf("") }
    var loaded by remember { mutableStateOf(false) }
    var loadingMore by remember { mutableStateOf(false) }
    var version by remember { mutableStateOf(0) }
    var tab by remember { mutableStateOf(0) }                                  // 0 = Recomendado (destaque + fileiras), 1 = Explorar (grade com filtros)
    var recRows by remember { mutableStateOf<List<TvRow>>(emptyList()) }
    var recLoaded by remember { mutableStateOf(false) }
    var focused by remember { mutableStateOf<TvCard?>(null) }
    var hero by remember { mutableStateOf<TvHero?>(null) }
    val firstRec = remember { FocusRequester() }
    val scope = rememberCoroutineScope()
    val first = remember { FocusRequester() }
    val gridState = rememberLazyGridState()
    BackHandler { onBack() }

    LaunchedEffect(version) {
        loaded = false
        error = ""
        when (val r = withContext(Dispatchers.IO) { TvLibraryApi.page(server, token, profileId, libId, 0, view) }) {
            is LibResult.Unauthorized -> onUnauthorized()
            is LibResult.Err -> { error = r.msg; items = emptyList() }
            is LibResult.Ok -> { items = r.items; total = r.total; genres = r.genres; view = r.view; if (r.name.isNotEmpty()) name = r.name }
        }
        loaded = true
    }
    // Recomendado (43.3): "Continue assistindo" (em andamento) e "Adicionados recentemente" da própria biblioteca
    LaunchedEffect(libId) {
        val a = withContext(Dispatchers.IO) { TvLibraryApi.page(server, token, profileId, libId, 0, LibView("played", "desc", "progress", "")) }
        val b = withContext(Dispatchers.IO) { TvLibraryApi.page(server, token, profileId, libId, 0, LibView("added", "desc", "all", "")) }
        if (a is LibResult.Unauthorized || b is LibResult.Unauthorized) { onUnauthorized(); return@LaunchedEffect }
        val rows = mutableListOf<TvRow>()
        (a as? LibResult.Ok)?.items?.take(20)?.takeIf { it.isNotEmpty() }?.let { rows.add(TvRow("continue", "Continue assistindo", it)) }
        (b as? LibResult.Ok)?.items?.take(20)?.takeIf { it.isNotEmpty() }?.let { rows.add(TvRow("recent", "Adicionados recentemente", it)) }
        recRows = rows
        recLoaded = true
        if (rows.isEmpty()) tab = 1
    }
    LaunchedEffect(focused) {
        val c = focused ?: return@LaunchedEffect
        delay(350)
        hero = try { withContext(Dispatchers.IO) { TvHomeApi.hero(server, token, profileId, c) } } catch (e: TvUnauthorized) { onUnauthorized(); null }
    }
    LaunchedEffect(recLoaded, tab) { if (recLoaded && tab == 0 && recRows.isNotEmpty()) runCatching { firstRec.requestFocus() } }
    // Foco inicial: o último card focado (ao voltar dos detalhes), se estiver nas páginas já carregadas; senão o primeiro
    val startIdx = remember(loaded) { items.indexOfFirst { it.type + it.id == restoreKey }.coerceAtLeast(0) }
    LaunchedEffect(loaded, items.isNotEmpty(), tab) {
        if (tab == 1 && loaded && items.isNotEmpty()) {
            runCatching { gridState.scrollToItem(startIdx) }
            runCatching { first.requestFocus() }
        }
    }

    fun more() {
        if (loadingMore || items.size >= total || !loaded) return
        loadingMore = true
        val off = items.size
        scope.launch {
            when (val r = withContext(Dispatchers.IO) { TvLibraryApi.page(server, token, profileId, libId, off, view) }) {
                is LibResult.Ok -> if (items.size == off) items = items + r.items
                is LibResult.Unauthorized -> onUnauthorized()
                else -> {}
            }
            loadingMore = false
        }
    }

    // Ordenado por título, carrega as demais páginas (até 800 itens) para o índice alfabético ficar completo
    LaunchedEffect(items.size, loadingMore, view?.sort, total, loaded) {
        if (loaded && view?.sort == "title" && items.size < total && total <= 800 && !loadingMore) more()
    }

    fun change(v: LibView) {
        view = v
        version++
        scope.launch(Dispatchers.IO) { TvLibraryApi.saveView(server, token, profileId, libId, v) }
    }

    val v = view
    TvDrawer(
        libs = libs, selected = "library:$libId", server = server, profileName = profileName, profileColor = profileColor, profilePhoto = profilePhoto,
        onNavigate = { dest -> if (dest != "library:$libId:$name") onNavigate(dest) }, onSwitchProfile = onSwitchProfile, onDisconnect = onDisconnect,
    ) {
    Box(Modifier.fillMaxSize().background(BG)) {
    HeroBackdrop(server, hero?.backdrop)
    Column(Modifier.fillMaxSize().padding(start = 24.dp + DRAWER_INSET, top = 16.dp, end = 24.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            val tabReqs = remember { List(2) { FocusRequester() } }
            PillGroup(tabReqs[tab.coerceIn(0, 1)]) {
                Row(Modifier.background(Color(0x66000000), RoundedCornerShape(50)).padding(horizontal = 6.dp, vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                    LibTab("Recomendado", tab == 0, { tab = 0 }, Modifier.focusRequester(tabReqs[0]))
                    LibTab("Explorar", tab == 1, { tab = 1 }, Modifier.focusRequester(tabReqs[1]))
                }
            }
            Spacer(Modifier.weight(1f))
            TvClock()
        }
        if (tab == 0) {
            HeroInfo(server, focused, hero)
            if (!recLoaded) Text("Carregando…", color = MUTED, fontSize = 20.sp)
            LazyColumn(verticalArrangement = Arrangement.spacedBy(14.dp), modifier = Modifier.fillMaxSize()) {
                items(recRows, key = { it.key }) { row ->
                    Column {
                        Text(row.title, color = TEXT, fontSize = 20.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(bottom = 6.dp))
                                                val rs = androidx.compose.foundation.lazy.rememberLazyListState()
                        val fr = remember { FocusRequester() }
                        RowEnter(fr, rs) { LazyRow(state = rs, horizontalArrangement = Arrangement.spacedBy(14.dp), contentPadding = PaddingValues(start = 12.dp, end = 48.dp, top = 12.dp, bottom = 14.dp)) {
                            items(row.items, key = { it.type + it.id }) { card ->
                                PosterCard(server, card, onFocus = { focused = it; onFocusKey(it.type + it.id) }, onOpen = onOpen,
                                    modifier = (if (row.key == recRows.first().key && card.id == row.items.first().id) Modifier.focusRequester(firstRec) else Modifier).let { if (card === row.items.first()) it.focusRequester(fr) else it })
                            }
                        } }
                    }
                }
            }
        } else Column(Modifier.fillMaxSize().padding(top = 12.dp)) {
        Spacer(Modifier.height(4.dp))
        val chipFirst = remember { FocusRequester() }
        if (v != null) EnterAt(chipFirst) { Row(Modifier.padding(start = 4.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            val fi = FILTERS.indexOfFirst { it.first == v.filter }.coerceAtLeast(0)
            ToolChip(FILTER_SHORT[fi], { change(v.copy(filter = FILTERS[(fi + 1) % FILTERS.size].first)) }, Modifier.focusRequester(chipFirst))
            if (genres.isNotEmpty() || v.genre.isNotEmpty()) {
                val opts = listOf("") + genres
                val gi = opts.indexOf(v.genre).coerceAtLeast(0)
                ToolChip(if (v.genre.isEmpty()) "Gêneros" else v.genre, { change(v.copy(genre = opts[(gi + 1) % opts.size])) })
            }
            Text("por", color = TEXT, fontSize = 12.sp)
            val si = SORTS.indexOfFirst { it.first == v.sort }.coerceAtLeast(0)
            ToolChip(SORTS[si].third, {
                val n = SORTS[(si + 1) % SORTS.size]
                change(v.copy(sort = n.first, dir = n.second))
            }, lead = { DirIcon(v.dir == "asc") })
            if (loaded && error.isEmpty()) Text("$total ${if (total == 1) "item" else "itens"}", color = TEXT, fontSize = 11.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.background(Color.Black, RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 2.dp))
            ToolChip("", { change(v.copy(dir = if (v.dir == "asc") "desc" else "asc")) }, lead = { DotsIcon() })
        } }
        Spacer(Modifier.height(10.dp))
        Box(Modifier.fillMaxSize()) {
            when {
                !loaded -> Text("Carregando…", color = MUTED, fontSize = 20.sp, modifier = Modifier.align(Alignment.Center))
                error.isNotEmpty() -> Column(Modifier.align(Alignment.Center), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(error, color = Color(0xFFE57373), fontSize = 20.sp)
                    Spacer(Modifier.height(16.dp))
                    TvButton("Tentar de novo", Modifier.width(260.dp).focusRequester(first)) { version++ }
                }
                items.isEmpty() -> Text("Nenhum item neste filtro.", color = MUTED, fontSize = 20.sp, modifier = Modifier.align(Alignment.Center))
                else -> {
                    val letterIdx = remember(items) { LinkedHashMap<String, Int>().also { m -> items.forEachIndexed { i, c -> m.putIfAbsent(letterOf(c.title), i) } } }
                    val showIndex = v?.sort == "title" && letterIdx.size > 1
                    val curLetter = items.getOrNull(gridState.firstVisibleItemIndex)?.let { letterOf(it.title) }.orEmpty()
                    Row(Modifier.fillMaxSize()) {
                        val nav = remember(gridState) { GridNav(gridState, scope) }
                        nav.total = items.size
                        GridEnter(nav, if (items.first().wide) 190f else 118f, 14f, 20f, Modifier.weight(1f).fillMaxHeight()) {
                        LazyVerticalGrid(
                            columns = GridCells.Adaptive(if (items.first().wide) 190.dp else 118.dp),
                            contentPadding = PaddingValues(start = 12.dp, top = 12.dp, bottom = 40.dp, end = 8.dp),
                            verticalArrangement = Arrangement.spacedBy(16.dp),
                            horizontalArrangement = Arrangement.spacedBy(14.dp),
                            state = gridState,
                            modifier = Modifier.fillMaxSize(),
                        ) {
                            items(count = items.size, key = { items[it].type + items[it].id }) { idx ->
                                PosterCard(server, items[idx], onFocus = { focused = it; onFocusKey(it.type + it.id); if (idx >= items.size - 12) more() }, onOpen = onOpen,
                                    modifier = (if (idx == startIdx) Modifier.focusRequester(first) else Modifier).then(nav.item(idx)),
                                    width = if (items[idx].wide) 190.dp else 118.dp)
                            }
                        }
                        }
                        if (showIndex) AlphaIndex(letterIdx.keys.toList(), curLetter, { l -> letterIdx[l]?.let { i -> scope.launch { gridState.scrollToItem(i) } } }, Modifier.fillMaxHeight())
                    }
                }
            }
        }
    }
    }
    }
    }
}
