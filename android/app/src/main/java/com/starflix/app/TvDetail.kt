package com.starflix.app

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusGroup
import androidx.compose.foundation.focusable
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.focus.focusProperties
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.tv.material3.Border
import androidx.tv.material3.Card
import androidx.tv.material3.CardDefaults
import androidx.tv.material3.ExperimentalTvMaterial3Api
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.tv.material3.Text
import coil.compose.AsyncImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** Destino de uma tela de detalhes: filme, série, temporada (`id` = série, `n` = temporada), episódio, coleção ou lista de reprodução. */
data class Target(val kind: String, val id: Long, val n: Int = 0)

fun TvCard.target(): Target? = when (type) {
    "movie", "show", "episode", "collection", "playlist" -> Target(type, id)
    "season" -> Target("season", id, n)
    else -> null  // "video" (Outros Vídeos) não tem página: reproduz direto
}

/** Dados do episódio em foco (43.5). */
data class EpInfo(val id: Long, val title: String, val meta: String, val overview: String, val badges: List<String>, val directors: String, val tech: List<String>)

data class Review(val author: String, val rating: Double, val created: String, val text: String)

data class CastLine(val name: String, val role: String, val image: String = "")

data class Detail(
    val kind: String, val id: Long, val title: String, val meta: String, val overview: String,
    val backdrop: String?, val poster: String?,
    val playPath: String?, val playLabel: String, val playTitle: String, val position: Int,
    val watchKind: String?, val watched: Boolean, val listId: Long, val inList: Boolean,
    val seasons: List<TvCard>, val episodes: List<TvCard>, val cast: List<CastLine>, val items: List<TvCard>, val itemsTitle: String,
    val seasonNums: List<Int> = emptyList(), val showId: Long = 0L, val reviews: List<Review> = emptyList(),
    val logo: String? = null, val contentRating: String = "", val badges: List<String> = emptyList(), val directors: String = "", val tech: List<String> = emptyList(),
)

sealed class DetailResult {
    data class Ok(val d: Detail) : DetailResult()
    object Unauthorized : DetailResult()
    data class Err(val msg: String) : DetailResult()
}

/** Detalhes da TV (40.12): `/api/tv/movie|show|show/<id>/season/<n>|episode|collection|playlist`, Minha Lista e marcar assistido. */
object TvDetailApi {
    private fun JSONObject.str(k: String): String = if (isNull(k)) "" else optString(k, "")

    private fun cards(j: JSONObject, k: String) = j.optJSONArray(k)?.let { a -> (0 until a.length()).map { TvHomeApi.parseCard(a.getJSONObject(it)) } }.orEmpty()

    private fun seasonCards(j: JSONObject, showId: Long): List<TvCard> = j.optJSONArray("seasons")?.let { a ->
        (0 until a.length()).map { i ->
            val s = a.getJSONObject(i)
            val n = s.optInt("n")
            val count = s.optInt("count")
            val w = s.optInt("watched")
            TvCard("season", showId, if (n == 0) "Especiais" else "Temporada $n", "$count ${if (count == 1) "episódio" else "episódios"}",
                s.str("image"), 0, count > 0 && w >= count, false, null, 0L, n)
        }
    }.orEmpty()

    private fun cast(j: JSONObject) = j.optJSONArray("cast")?.let { a ->
        (0 until a.length()).map { val c = a.getJSONObject(it); CastLine(c.str("name"), c.str("label").ifEmpty { c.str("role") }, c.str("image")) }
    }.orEmpty()

    private fun minutes(sec: Int) = if (sec <= 0) "" else if (sec >= 3600) "${sec / 3600} h ${sec % 3600 / 60} min" else "${maxOf(1, sec / 60)} min"

    private fun meta(vararg parts: String) = parts.filter { it.isNotBlank() }.joinToString(" · ")

    private fun genres(j: JSONObject) = j.optJSONArray("genres")?.let { a -> (0 until minOf(3, a.length())).joinToString(", ") { a.getString(it) } }.orEmpty()

    private fun badges(j: JSONObject): List<String> = buildList {
        if (!j.isNull("imdb") && j.optDouble("imdb") > 0) add("IMDb " + "%.1f".format(java.util.Locale.US, j.optDouble("imdb")))
        if (!j.isNull("rt")) add("RT ${j.optInt("rt")}%")
        if (!j.isNull("rating") && j.optDouble("rating") > 0) add("TMDB " + "%.1f".format(java.util.Locale.US, j.optDouble("rating")))
    }

    private fun reviews(j: JSONObject): List<Review> = j.optJSONArray("reviews")?.let { a ->
        (0 until a.length()).map { val r = a.getJSONObject(it); Review(r.str("author"), if (r.isNull("rating")) 0.0 else r.optDouble("rating"), r.str("created").take(10), r.str("text")) }
    }.orEmpty()

    private fun directors(j: JSONObject) = j.optJSONArray("directors")?.let { a -> (0 until a.length()).joinToString(", ") { a.getString(it) } }.orEmpty()

    private fun tech(j: JSONObject) = j.optJSONArray("tech")?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty()

    private fun playLabel(pos: Int) = if (pos > 0) "Continuar" else "Reproduzir"

    private fun empty(kind: String, id: Long) = Detail(kind, id, "", "", "", null, null, null, "Reproduzir", "", 0, null, false, 0L, false,
        emptyList(), emptyList(), emptyList(), emptyList(), "")

    fun load(server: String, token: String, profile: Long, t: Target): DetailResult = try {
        val path = when (t.kind) {
            "show" -> "/api/tv/show/${t.id}"
            "season" -> "/api/tv/show/${t.id}/season/${t.n}"
            else -> "/api/tv/${t.kind}/${t.id}"
        }
        val (code, j) = TvApi.authed("GET", server, path, token, profile)
        if (code != 200 || j == null) DetailResult.Err(if (code == 404) "Item indisponível." else "Erro do servidor ($code).") else {
            val base = empty(t.kind, t.id)
            val im = j.optJSONObject("images")
            val d = when (t.kind) {
                "movie" -> {
                    val pos = j.optInt("position")
                    base.copy(title = j.str("title"), overview = j.str("overview").ifEmpty { j.str("tagline") },
                        meta = meta(j.optInt("year").takeIf { it > 0 }?.toString().orEmpty(), minutes(j.optInt("duration")), genres(j)),
                        logo = im?.str("logo")?.ifEmpty { null }, contentRating = j.str("content_rating"), badges = badges(j), directors = directors(j), tech = tech(j), reviews = reviews(j),
                        backdrop = im?.str("backdrop")?.ifEmpty { null } ?: im?.str("poster"), poster = im?.str("poster"),
                        playPath = j.str("play").ifEmpty { null }, playLabel = playLabel(pos), playTitle = j.str("title"), position = pos,
                        watchKind = "movie", watched = j.optBoolean("watched"), listId = t.id, inList = j.optBoolean("in_list"),
                        cast = cast(j), items = cards(j, "related"), itemsTitle = "Relacionados")
                }
                "show" -> {
                    val pl = j.optJSONObject("play")
                    val label = if (pl == null) "Reproduzir" else if (pl.optBoolean("next_up")) "Próximo: T${pl.optInt("season")} · E${pl.optInt("episode")}" else "Reproduzir"
                    base.copy(title = j.str("title"), overview = j.str("overview").ifEmpty { j.str("tagline") },
                        meta = meta(j.optInt("year").takeIf { it > 0 }?.toString().orEmpty(), genres(j), "${j.optInt("watched_count")}/${j.optInt("total")} assistidos"),
                        logo = im?.str("logo")?.ifEmpty { null }, contentRating = j.str("content_rating"), badges = badges(j), directors = directors(j), reviews = reviews(j),
                        backdrop = im?.str("backdrop")?.ifEmpty { null } ?: im?.str("poster"), poster = im?.str("poster"),
                        playPath = pl?.str("url")?.ifEmpty { null }, playLabel = label, playTitle = j.str("title"),
                        listId = t.id, inList = j.optBoolean("in_list"),
                        seasons = seasonCards(j, t.id), cast = cast(j), items = cards(j, "related"), itemsTitle = "Relacionados")
                }
                "season" -> {
                    val show = j.optJSONObject("show")
                    val sid = show?.optLong("id") ?: t.id
                    val ea = j.optJSONArray("episodes")
                    val eps = (0 until (ea?.length() ?: 0)).map { i ->
                        val e = ea!!.getJSONObject(i)
                        val n = e.optInt("episode")
                        val ttl = e.str("title")
                        TvCard("episode", e.optLong("id"), if (ttl.isEmpty()) "Episódio $n" else "$n. $ttl", "T${t.n} · E$n", e.str("image"),
                            e.optInt("pct"), e.optBoolean("watched"), true, e.str("play").ifEmpty { null }, sid, e.optInt("position"))  // n = posição salva (s)
                    }
                    val nums = j.optJSONArray("seasons")?.let { a -> (0 until a.length()).map { a.getInt(it) } }.orEmpty()
                    val sj = try { TvApi.authed("GET", server, "/api/tv/show/$sid", token, profile).let { if (it.first == 200) it.second else null } } catch (e: TvUnauthorized) { throw e } catch (e: Exception) { null }
                    val sim = sj?.optJSONObject("images")
                    base.copy(title = show?.str("title").orEmpty(), meta = if (t.n == 0) "Especiais" else "Temporada ${t.n}",
                        overview = "${eps.size} ${if (eps.size == 1) "episódio" else "episódios"}", poster = "/season-poster/$sid/${t.n}",
                        backdrop = "/backdrop/$sid", episodes = eps, seasonNums = nums, showId = sid, listId = sid, inList = sj?.optBoolean("in_list") == true,
                        logo = sim?.str("logo")?.ifEmpty { null }, contentRating = sj?.str("content_rating").orEmpty(), cast = if (sj != null) cast(sj) else emptyList(), reviews = if (sj != null) reviews(sj) else emptyList())
                }
                "episode" -> {
                    val pos = j.optInt("position")
                    val s = j.optInt("season")
                    val n = j.optInt("episode")
                    base.copy(title = j.str("title").ifEmpty { "Episódio $n" }, overview = j.str("overview"),
                        meta = meta(j.str("show"), "T$s · E$n", j.str("air_date"), minutes(j.optInt("duration"))),
                        backdrop = j.str("image"), poster = j.str("image"),
                        playPath = j.str("play").ifEmpty { null }, playLabel = playLabel(pos), playTitle = "${j.str("show")} · T$s E$n", position = pos,
                        watchKind = "episode", watched = j.optBoolean("watched"))
                }
                "collection" -> {
                    val next = j.optLong("next_id", 0L)
                    val its = cards(j, "items")
                    base.copy(title = j.str("title"), overview = j.str("overview"),
                        meta = "${its.size} ${if (its.size == 1) "item" else "itens"}", poster = j.str("image"),
                        backdrop = j.str("backdrop").ifEmpty { j.str("image") },
                        playPath = if (next > 0 && its.any { it.id == next }) "/stream/movie/$next/play" else null, playTitle = j.str("title"),
                        items = its, itemsTitle = "Itens")
                }
                else -> {  // playlist
                    val its = cards(j, "items")
                    base.copy(title = j.str("title"), meta = "${its.size} ${if (its.size == 1) "item" else "itens"}", poster = j.str("image"),
                        backdrop = j.str("image"), items = its, itemsTitle = "Itens")
                }
            }
            DetailResult.Ok(d)
        }
    } catch (e: TvUnauthorized) {
        DetailResult.Unauthorized
    } catch (e: Exception) {
        DetailResult.Err("Servidor inacessível.")
    }

    private fun dateBr(raw: String): String = try {
        java.text.SimpleDateFormat("d 'de' MMM 'de' yyyy", java.util.Locale("pt", "BR")).format(java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.US).parse(raw.take(10))!!)
    } catch (e: Exception) { raw }

    /** Metadados do episódio em foco: `T1 • E2  data  duração`, sinopse, nota IMDb, direção e selos técnicos. */
    fun episodeInfo(server: String, token: String, profile: Long, id: Long): EpInfo? = try {
        val (code, j) = TvApi.authed("GET", server, "/api/tv/episode/$id", token, profile)
        if (code != 200 || j == null) null else {
            val parts = mutableListOf("T${j.optInt("season")} • E${j.optInt("episode")}")
            j.str("air_date").takeIf { it.isNotEmpty() }?.let { parts.add(dateBr(it)) }
            minutes(j.optInt("duration")).takeIf { it.isNotEmpty() }?.let { parts.add(it) }
            val b = buildList { if (!j.isNull("imdb") && j.optDouble("imdb") > 0) add("IMDb " + "%.1f".format(java.util.Locale.US, j.optDouble("imdb"))) }
            EpInfo(id, j.str("title"), parts.joinToString("  "), j.str("overview"), b, directors(j), tech(j))
        }
    } catch (e: TvUnauthorized) {
        throw e
    } catch (e: Exception) {
        null
    }

    /** true/false = deu certo; null = token revogado. */
    fun setList(server: String, token: String, profile: Long, id: Long, on: Boolean): Boolean? = call(server, token, profile, if (on) "POST" else "DELETE", "/api/tv/mylist/$id", null)

    fun setWatched(server: String, token: String, profile: Long, kind: String, id: Long, watched: Boolean): Boolean? =
        call(server, token, profile, "POST", "/api/tv/watched/$kind/$id", JSONObject().put("watched", watched).toString())

    private fun call(server: String, token: String, profile: Long, method: String, path: String, body: String?): Boolean? = try {
        TvApi.authed(method, server, path, token, profile, body).first == 200
    } catch (e: TvUnauthorized) {
        null
    } catch (e: Exception) {
        false
    }
}

private val BG = Color(0xFF1F2326)
private val ACCENT = Color(0xFFE5A00D)
private val TEXT = Color(0xFFEEEEEE)
private val MUTED = Color(0xFF9A9EA3)

/**
 * Tela de detalhes (40.12) para filme, série, temporada, episódio, coleção e lista de reprodução. Botões Reproduzir/Continuar,
 * Marcar como assistido e Minha Lista; temporadas, episódios, itens e relacionados são cards que abrem a próxima tela (`onOpen`);
 * elenco em texto. Reproduzir chama `onPlay(caminho, título, posição)` (player da TV na 40.14). 401 → `onUnauthorized`.
 */
@Composable
fun DetailScreen(
    server: String, token: String, profileId: Long, target: Target,
    onOpen: (TvCard) -> Unit, onPlay: (path: String, title: String, position: Int) -> Unit, onBack: () -> Unit, onUnauthorized: () -> Unit, refresh: Int = 0,
) {
    var result by remember(target) { mutableStateOf<DetailResult?>(null) }
    var reload by remember { mutableStateOf(0) }
    var watched by remember(target) { mutableStateOf(false) }
    var inList by remember(target) { mutableStateOf(false) }
    var notice by remember(target) { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    val first = remember(target) { FocusRequester() }
    val epWatched = remember(target) { androidx.compose.runtime.mutableStateMapOf<Long, Boolean>() }
    BackHandler { onBack() }

    val loadFr = remember(target) { FocusRequester() }
    LaunchedEffect(target, reload, refresh) {
        // 57.24: ao recarregar (voltar do player, progresso) o conteúdo antigo fica na tela — sem piscar "Carregando…" e sem o foco cair no menu lateral
        if (result is DetailResult.Err) result = null
        when (val r = withContext(Dispatchers.IO) { TvDetailApi.load(server, token, profileId, target) }) {
            is DetailResult.Unauthorized -> onUnauthorized()
            is DetailResult.Ok -> { result = r; watched = r.d.watched; inList = r.d.inList }
            is DetailResult.Err -> if (result == null) result = r
        }
    }
    val ok = result as? DetailResult.Ok
    // enquanto carrega, o foco fica no próprio "Carregando…" (senão cai no menu lateral e ele abre)
    LaunchedEffect(target) {
        repeat(10) {
            if (result != null) return@LaunchedEffect
            if (runCatching { loadFr.requestFocus() }.isSuccess) return@LaunchedEffect
            kotlinx.coroutines.delay(40)
        }
    }
    // foco inicial só quando o conteúdo aparece pela 1ª vez (não a cada recarga); tenta de novo até o item existir na tela
    LaunchedEffect(target, result != null) {
        if (result == null) return@LaunchedEffect
        repeat(25) {
            kotlinx.coroutines.delay(if (it == 0) 30L else 80L)
            if (runCatching { first.requestFocus() }.isSuccess) return@LaunchedEffect
        }
    }

    fun toggleWatched(d: Detail) {
        val kind = d.watchKind ?: return
        val want = !watched
        scope.launch {
            val r = withContext(Dispatchers.IO) { TvDetailApi.setWatched(server, token, profileId, kind, d.id, want) }
            when (r) { true -> { watched = want; notice = "" }; null -> onUnauthorized(); false -> notice = "Não foi possível salvar." }
        }
    }

    fun setEpWatched(id: Long, want: Boolean) {
        scope.launch {
            val r = withContext(Dispatchers.IO) { TvDetailApi.setWatched(server, token, profileId, "episode", id, want) }
            when (r) { true -> { epWatched[id] = want; notice = "" }; null -> onUnauthorized(); false -> notice = "Não foi possível salvar." }
        }
    }

    fun toggleList(d: Detail) {
        val want = !inList
        scope.launch {
            val r = withContext(Dispatchers.IO) { TvDetailApi.setList(server, token, profileId, d.listId, want) }
            when (r) { true -> { inList = want; notice = "" }; null -> onUnauthorized(); false -> notice = "Não foi possível salvar." }
        }
    }

    Box(Modifier.fillMaxSize().background(BG)) {
        val bd = ok?.d?.backdrop
        if (ok?.d?.kind == "movie" || ok?.d?.kind == "show" || ok?.d?.kind == "season") HeroBackdrop(server, bd) else {
            if (!bd.isNullOrEmpty()) RetryAsyncImage(model = server + bd, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize().alpha(0.3f))
            Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color.Transparent, BG), startY = 400f)))
        }
        when {
            result == null -> Text("Carregando…", color = MUTED, fontSize = 20.sp, modifier = Modifier.align(Alignment.Center).focusRequester(loadFr).focusable())
            result is DetailResult.Err -> Column(Modifier.align(Alignment.Center), horizontalAlignment = Alignment.CenterHorizontally) {
                Text((result as DetailResult.Err).msg, color = Color(0xFFE57373), fontSize = 20.sp)
                Spacer(Modifier.height(16.dp))
                TvButton("Tentar de novo", Modifier.width(260.dp).focusRequester(first)) { reload++ }
                Spacer(Modifier.height(10.dp))
                TvButton("Voltar", Modifier.width(260.dp)) { onBack() }
            }
            ok != null -> {
                val d = ok.d
                // Foco inicial em um só lugar: Reproduzir; senão Marcar assistido; senão Minha Lista; senão o 1º card
                val focusOn = when {
                    d.playPath != null -> "play"
                    d.watchKind != null -> "watch"
                    d.kind == "movie" || d.kind == "show" -> "list"
                    else -> "card"
                }
                if (d.kind == "movie" || d.kind == "show") MediaDetail(
                    server, d, watched, inList, notice, first,
                    onPlay = { pos -> onPlay(d.playPath.orEmpty(), d.playTitle, pos) }, onToggleWatched = { toggleWatched(d) }, onToggleList = { toggleList(d) }, onOpen = onOpen,
                ) else if (d.kind == "season") SeasonDetail(
                    server, token, profileId, d, inList, notice, epWatched, first,
                    onPlay = { path, title, pos -> onPlay(path, title, pos) }, onSetWatched = { id, want -> setEpWatched(id, want) },
                    onToggleList = { toggleList(d) }, onOpen = onOpen, onUnauthorized = onUnauthorized,
                ) else {
                // Cabeçalho fixo no alto (não rola, então nada sai da tela); só as fileiras rolam abaixo dele
                Column(Modifier.fillMaxSize().padding(start = DRAWER_INSET + 16.dp, top = 48.dp, end = 32.dp)) {
                        Row(horizontalArrangement = Arrangement.spacedBy(28.dp)) {
                            if (!d.poster.isNullOrEmpty()) {
                                val wide = d.kind == "episode"
                                RetryAsyncImage(model = server + d.poster, contentDescription = d.title, contentScale = ContentScale.Crop,
                                    modifier = (if (wide) Modifier.size(320.dp, 180.dp) else Modifier.size(200.dp, 300.dp)).background(Color(0xFF2F3236), RoundedCornerShape(8.dp)))
                            }
                            Column(Modifier.width(760.dp)) {
                                Text(d.title, color = TEXT, fontSize = 34.sp, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                if (d.meta.isNotEmpty()) Text(d.meta, color = ACCENT, fontSize = 16.sp, modifier = Modifier.padding(top = 4.dp))
                                if (d.overview.isNotEmpty()) Text(d.overview, color = TEXT, fontSize = 16.sp, maxLines = 5, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 10.dp))
                                if (d.cast.isNotEmpty()) Text("Elenco: " + d.cast.take(8).joinToString(", ") { if (it.role.isEmpty()) it.name else "${it.name} (${it.role})" },
                                    color = MUTED, fontSize = 14.sp, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 10.dp))
                                Spacer(Modifier.height(18.dp))
                                EnterAt(first) { Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                    if (d.playPath != null) TvButton(d.playLabel, Modifier.width(250.dp).let { if (focusOn == "play") it.focusRequester(first) else it }) {
                                        onPlay(d.playPath, d.playTitle, d.position)
                                    }
                                    if (d.watchKind != null) TvButton(if (watched) "✓ Assistido" else "Marcar assistido", Modifier.width(250.dp).let { if (focusOn == "watch") it.focusRequester(first) else it }) { toggleWatched(d) }
                                    if (d.kind == "movie" || d.kind == "show") TvButton(if (inList) "✓ Minha Lista" else "+ Minha Lista", Modifier.width(250.dp).let { if (focusOn == "list") it.focusRequester(first) else it }) { toggleList(d) }
                                } }
                                Text(notice, color = Color(0xFFE57373), fontSize = 14.sp, modifier = Modifier.padding(top = 8.dp).height(20.dp))
                            }
                        }
                    Spacer(Modifier.height(18.dp))
                    val sections = listOf("Temporadas" to d.seasons, "Episódios" to d.episodes, d.itemsTitle to d.items).filter { it.second.isNotEmpty() }
                    LazyColumn(Modifier.weight(1f), contentPadding = PaddingValues(bottom = 48.dp), verticalArrangement = Arrangement.spacedBy(22.dp)) {
                    items(sections, key = { it.first }) { (title, list) ->
                        val fr = remember { FocusRequester() }
                        Column {
                            Text(title, color = TEXT, fontSize = 20.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(bottom = 8.dp))
                            FirstEnter(fr) { st -> LazyRow(state = st, horizontalArrangement = Arrangement.spacedBy(14.dp), contentPadding = PaddingValues(start = 12.dp, end = 48.dp, top = 12.dp, bottom = 14.dp)) {
                                items(list, key = { it.type + it.id + ":" + it.n }) { c ->
                                    val mine = focusOn == "card" && list === sections.first().second && c === list.first()
                                    PosterCard(server, c, onFocus = {}, onOpen = onOpen, modifier = (if (mine) Modifier.focusRequester(first) else Modifier).let { if (c === list.first()) it.focusRequester(fr) else it })
                                } }
                            }
                        }
                    }
                    }
                }
                }
            }
        }
    }
}

/** Ícone desenhado dentro do botão circular (as fontes da TV não têm todos os símbolos). */
private fun DrawScope.iconPlay(c: Color) {
    val w = size.width; val h = size.height
    drawPath(Path().apply { moveTo(w * 0.38f, h * 0.27f); lineTo(w * 0.38f, h * 0.73f); lineTo(w * 0.74f, h * 0.5f); close() }, c)
}

private fun DrawScope.iconRestart(c: Color) {
    val w = size.width; val h = size.height
    drawArc(c, startAngle = -50f, sweepAngle = 290f, useCenter = false, topLeft = Offset(w * 0.27f, h * 0.27f),
        size = androidx.compose.ui.geometry.Size(w * 0.46f, h * 0.46f), style = Stroke(2.2.dp.toPx()))
    drawPath(Path().apply { moveTo(w * 0.62f, h * 0.2f); lineTo(w * 0.62f, h * 0.4f); lineTo(w * 0.8f, h * 0.3f); close() }, c)
}

private fun DrawScope.iconList(c: Color, on: Boolean) {
    val w = size.width; val h = size.height
    val p = Path().apply { moveTo(w * 0.34f, h * 0.24f); lineTo(w * 0.66f, h * 0.24f); lineTo(w * 0.66f, h * 0.76f); lineTo(w * 0.5f, h * 0.62f); lineTo(w * 0.34f, h * 0.76f); close() }
    if (on) drawPath(p, c) else drawPath(p, c, style = Stroke(2.dp.toPx()))
}

private fun DrawScope.iconCheck(c: Color, on: Boolean) {
    val w = size.width; val h = size.height
    if (on) drawCircle(c, w * 0.24f, Offset(w / 2, h / 2)) else drawCircle(c, w * 0.24f, Offset(w / 2, h / 2), style = Stroke(2.dp.toPx()))
    val k = if (on) (if (c == Color.Black) Color.White else Color.Black) else c  // 57.29: em foco (círculo preto) o visto fica branco
    drawLine(k, Offset(w * 0.42f, h * 0.5f), Offset(w * 0.48f, h * 0.57f), 2.2.dp.toPx())
    drawLine(k, Offset(w * 0.48f, h * 0.57f), Offset(w * 0.6f, h * 0.42f), 2.2.dp.toPx())
}

@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun CircleBtn(label: String, onHint: (String) -> Unit, modifier: Modifier = Modifier, onClick: () -> Unit, icon: DrawScope.(Color) -> Unit) {
    var focused by remember { mutableStateOf(false) }
    Card(
        onClick = onClick, shape = CardDefaults.shape(CircleShape),
        colors = CardDefaults.colors(containerColor = Color(0x99383840), focusedContainerColor = Color.White),
        border = CardDefaults.border(focusedBorder = Border(BorderStroke(2.dp, ACCENT))),
        scale = CardDefaults.scale(focusedScale = 1.1f),
        modifier = modifier.size(48.dp).onFocusChanged { focused = it.isFocused; if (it.isFocused) onHint(label) },
    ) { Canvas(Modifier.size(48.dp)) { icon(if (focused) Color.Black else Color.White) } }
}

@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun CastCircle(server: String, c: CastLine, modifier: Modifier = Modifier) {
    Column(modifier.width(124.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Card(onClick = {}, shape = CardDefaults.shape(CircleShape), scale = CardDefaults.scale(focusedScale = 1.06f),
            border = CardDefaults.border(focusedBorder = Border(BorderStroke(3.dp, ACCENT))), modifier = Modifier.size(104.dp)) {
            Box(Modifier.fillMaxSize().background(Color(0xFF2F3236))) {
                if (c.image.isNotEmpty()) RetryAsyncImage(model = server + c.image, contentDescription = c.name, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            }
        }
        Text(c.name, color = TEXT, fontSize = 13.sp, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
        if (c.role.isNotEmpty()) Text(c.role, color = MUTED, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** Grupo (ex.: linha de botões) que, ao receber o foco vindo de fora (de cima ou de baixo), foca sempre o item indicado. */
@OptIn(ExperimentalComposeUiApi::class)
@Composable
internal fun EnterAt(req: FocusRequester?, content: @Composable () -> Unit) {
    val m = if (req != null) Modifier.focusProperties { enter = { req } } else Modifier
    Box(m.focusGroup()) { content() }
}

/**
 * 57.29: fileira de episódios. Vindo de CIMA (pílulas) entra no episódio inicial (`startIdx`); vindo de BAIXO (botões) volta ao episódio de onde o foco saiu (`last()`).
 * Só aponta para um card realmente composto (`live`), senão cai no mais próximo — requester sem item derruba o app. Ao sair para cima a fileira volta ao episódio inicial; ao sair para baixo não rola.
 */
@OptIn(ExperimentalComposeUiApi::class)
@Composable
private fun EpisodesEnter(
    reqs: List<FocusRequester>, live: Set<Int>, last: () -> Int, startIdx: Int, state: LazyListState, content: @Composable () -> Unit,
) {
    val sc = rememberCoroutineScope()
    var had by remember { mutableStateOf(false) }
    var dirUp by remember { mutableStateOf(false) }
    Box(
        Modifier
            .focusProperties {
                enter = { dir ->
                    val want = if (dir == androidx.compose.ui.focus.FocusDirection.Up) last() else startIdx
                    val idx = when {
                        want in live -> want
                        live.isNotEmpty() -> live.minByOrNull { kotlin.math.abs(it - want) } ?: want
                        else -> want
                    }
                    reqs[idx.coerceIn(0, reqs.lastIndex)]
                }
            }
            .focusGroup()
            .androidx_onPreviewKey { dirUp = it }
            .onFocusChanged {
                if (it.hasFocus) had = true
                else if (had) { had = false; if (dirUp) sc.launch { state.scrollToItem(startIdx) } }
            },
    ) { content() }
}

private fun Modifier.androidx_onPreviewKey(onVertical: (up: Boolean) -> Unit): Modifier = this.onPreviewKeyEvent { ev ->
    if (ev.type == androidx.compose.ui.input.key.KeyEventType.KeyDown) {
        when (ev.key) {
            androidx.compose.ui.input.key.Key.DirectionUp -> onVertical(true)
            androidx.compose.ui.input.key.Key.DirectionDown -> onVertical(false)
            else -> {}
        }
    }
    false
}

/** Fileira que, ao receber o foco vindo de fora, sempre foca o 1º item (não o último focado) e volta ao início quando o foco sai. */
@OptIn(ExperimentalComposeUiApi::class)
@Composable
private fun FirstEnter(first: FocusRequester?, content: @Composable (LazyListState) -> Unit) {
    val st = rememberLazyListState()
    val sc = rememberCoroutineScope()
    var had by remember { mutableStateOf(false) }
    val enter = if (first != null) Modifier.focusProperties { enter = { first } } else Modifier
    Box(enter.focusGroup().onFocusChanged { if (it.hasFocus) had = true else if (had) { had = false; sc.launch { st.scrollToItem(0) } } }) { content(st) }
}

/**
 * Detalhe de filme e série (43.4): logo (ou título), ano · duração · gêneros + classificação, selos de nota, sinopse em caixa translúcida,
 * "Dirigido por", botões circulares (Reproduzir/Continuar, Do início, Minha Lista, Assistido), selos técnicos à direita e as fileiras
 * Temporadas, Elenco & Equipe (fotos redondas) e Relacionados. Dado ausente = bloco oculto. `onPlay(-1)` = do início.
 */
@Composable
private fun MediaDetail(
    server: String, d: Detail, watched: Boolean, inList: Boolean, notice: String, first: FocusRequester,
    onPlay: (Int) -> Unit, onToggleWatched: () -> Unit, onToggleList: () -> Unit, onOpen: (TvCard) -> Unit,
) {
    var hint by remember { mutableStateOf("") }
    var showAll by remember { mutableStateOf(false) }
    val playReq = remember { FocusRequester() }
    val frSeasons = remember { FocusRequester() }
    val frCast = remember { FocusRequester() }
    val frRelated = remember { FocusRequester() }
    val frReviews = remember { FocusRequester() }
    if (showAll) ReviewsDialog(d.reviews) { showAll = false }
    // 57.31: garante o foco inicial no Reproduzir do filme/série: insiste por até 1,5 s enquanto nenhum botão do topo recebeu o foco (`hint` só muda quando um deles é focado)
    LaunchedEffect(Unit) {
        if (d.playPath == null) return@LaunchedEffect
        val t0 = System.currentTimeMillis()
        kotlinx.coroutines.delay(60)
        while (hint.isEmpty() && System.currentTimeMillis() - t0 < 1500) { runCatching { playReq.requestFocus() }; kotlinx.coroutines.delay(100) }
    }
    Column(Modifier.fillMaxSize().padding(start = DRAWER_INSET + 16.dp, end = 32.dp)) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(top = 24.dp, bottom = 40.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item("header") {
                Column {
            if (d.logo != null) RetryAsyncImage(model = server + d.logo, contentDescription = d.title, contentScale = ContentScale.Fit,
                alignment = Alignment.CenterStart, modifier = Modifier.height(72.dp).width(320.dp))
            else Text(d.title, color = TEXT, fontSize = 34.sp, fontWeight = FontWeight.Black, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 4.dp)) {
                Text(d.meta, color = MUTED, fontSize = 12.sp, maxLines = 1)
                if (d.contentRating.isNotEmpty()) Text(d.contentRating, color = TEXT, fontSize = 11.sp, fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(start = 8.dp).background(Color.Black, RoundedCornerShape(3.dp)).padding(horizontal = 5.dp, vertical = 1.dp))
            }
            if (d.badges.isNotEmpty()) Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                d.badges.forEach { Text(it, color = TEXT, fontSize = 11.sp, fontWeight = FontWeight.Bold, modifier = Modifier.background(Color(0x66000000), RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 2.dp)) }
            }
            if (d.overview.isNotEmpty()) {
                var expanded by remember { mutableStateOf(false) }
                var ovFocus by remember { mutableStateOf(false) }
                Text(d.overview, color = TEXT, fontSize = 13.sp, maxLines = if (expanded) Int.MAX_VALUE else 2, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 6.dp).width(640.dp)
                        .then(if (d.playPath == null) Modifier.focusRequester(first) else Modifier)  // 57.31: com Reproduzir, o foco inicial é ele (a sinopse fica a um ↑)
                    .focusProperties { if (d.playPath != null) down = playReq }
                    .onFocusChanged { ovFocus = it.isFocused }
                        .clip(RoundedCornerShape(6.dp))
                        .background(if (ovFocus) Color(0x33FFFFFF) else Color.Transparent)
                        .clickable { expanded = !expanded }
                        .padding(horizontal = 4.dp, vertical = 3.dp))
            }
            if (d.directors.isNotEmpty()) Text("Dirigido por ${d.directors}", color = MUTED, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
            Row(Modifier.fillMaxWidth().padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                EnterAt(if (d.playPath != null) playReq else null) { Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    if (d.playPath != null) CircleBtn(d.playLabel, { hint = it }, Modifier.focusRequester(first).focusRequester(playReq), { onPlay(d.position) }) { iconPlay(it) }
                    if (d.playPath != null && d.kind == "movie" && d.position > 0) CircleBtn("Do início", { hint = it }, Modifier, { onPlay(-1) }) { iconRestart(it) }
                    CircleBtn(if (inList) "Remover da Minha Lista" else "Adicionar à Minha Lista", { hint = it }, Modifier, onToggleList) { iconList(it, inList) }
                    if (d.watchKind != null) CircleBtn(if (watched) "Marcar como não assistido" else "Marcar como assistido", { hint = it }, Modifier, onToggleWatched) { iconCheck(it, watched) }
                    Text(if (notice.isNotEmpty()) notice else hint, color = if (notice.isNotEmpty()) Color(0xFFE57373) else MUTED, fontSize = 12.sp, modifier = Modifier.padding(start = 6.dp))
                } }
                Spacer(Modifier.weight(1f))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    d.tech.forEach { Text(it, color = TEXT, fontSize = 11.sp, fontWeight = FontWeight.Bold, modifier = Modifier.background(Color(0xCC000000), RoundedCornerShape(4.dp)).padding(horizontal = 7.dp, vertical = 3.dp)) }
                }
            }
                }
            }
            if (d.seasons.isNotEmpty()) item("seasons") {
                Column {
                    Text("Temporadas", color = TEXT, fontSize = 18.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(bottom = 4.dp))
                    FirstEnter(frSeasons) { st -> LazyRow(state = st, horizontalArrangement = Arrangement.spacedBy(14.dp), contentPadding = PaddingValues(start = 12.dp, end = 48.dp, top = 8.dp, bottom = 8.dp)) {
                        items(d.seasons, key = { it.type + it.id + ":" + it.n }) { c -> PosterCard(server, c, onFocus = {}, onOpen = onOpen, modifier = if (c === d.seasons.first()) Modifier.focusRequester(frSeasons) else Modifier) }
                    } }
                }
            }
            if (d.cast.isNotEmpty()) item("cast") {
                Column {
                    Text("Elenco & Equipe", color = TEXT, fontSize = 18.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(bottom = 4.dp))
                    FirstEnter(frCast) { st -> LazyRow(state = st, horizontalArrangement = Arrangement.spacedBy(14.dp), contentPadding = PaddingValues(start = 12.dp, end = 48.dp, top = 8.dp, bottom = 8.dp)) {
                        items(d.cast, key = { it.name + it.role }) { c -> CastCircle(server, c, if (c === d.cast.first()) Modifier.focusRequester(frCast) else Modifier) }
                    } }
                }
            }
            if (d.reviews.isNotEmpty()) item("reviews") { ReviewsRow(d.reviews, frReviews) { showAll = true } }
            if (d.items.isNotEmpty()) item("related") {
                Column {
                    Text(d.itemsTitle, color = TEXT, fontSize = 18.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(bottom = 4.dp))
                    FirstEnter(frRelated) { st -> LazyRow(state = st, horizontalArrangement = Arrangement.spacedBy(14.dp), contentPadding = PaddingValues(start = 12.dp, end = 48.dp, top = 8.dp, bottom = 8.dp)) {
                        items(d.items, key = { it.type + it.id }) { c -> PosterCard(server, c, onFocus = {}, onOpen = onOpen, modifier = if (c === d.items.first()) Modifier.focusRequester(frRelated) else Modifier) }
                    } }
                }
            }
        }
    }
}

@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun SeasonPill(label: String, selected: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Card(
        onClick = onClick, modifier = modifier.padding(end = 8.dp), shape = CardDefaults.shape(RoundedCornerShape(50)),
        colors = CardDefaults.colors(containerColor = Color(0x66000000)),
        border = CardDefaults.border(border = Border(BorderStroke(if (selected) 1.dp else 0.dp, if (selected) TEXT else Color.Transparent)), focusedBorder = Border(BorderStroke(2.dp, ACCENT))),
    ) { Text(label, color = TEXT, fontSize = 13.sp, maxLines = 1, softWrap = false, modifier = Modifier.padding(horizontal = 14.dp, vertical = 5.dp)) }
}

/** Cartão de episódio 16:9 (43.5): still, selo `✓ E2` e barra de progresso; OK reproduz. */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun EpisodeCard(server: String, c: TvCard, watched: Boolean, onFocus: (TvCard) -> Unit, onPlay: (TvCard) -> Unit, modifier: Modifier = Modifier) {
    Card(
        onClick = { onPlay(c) }, shape = CardDefaults.shape(RoundedCornerShape(8.dp)), scale = CardDefaults.scale(focusedScale = 1.05f),
        border = CardDefaults.border(focusedBorder = Border(BorderStroke(3.dp, Color.White))),
        modifier = modifier.size(260.dp, 146.dp).onFocusChanged { if (it.isFocused) onFocus(c) },
    ) {
        Box(Modifier.fillMaxSize().background(Color(0xFF2F3236))) {
            if (c.image.isNotEmpty()) RetryAsyncImage(model = server + c.image, contentDescription = c.title, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            Text((if (watched) "✓ " else "") + "E" + c.sub.substringAfter("E"), color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.align(Alignment.TopEnd).padding(6.dp).background(Color(0xCC000000), RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 1.dp))
            // 57.21: linha amarela cheia nos assistidos; parcial nos que ainda faltam
            if (watched) Box(Modifier.align(Alignment.BottomStart).fillMaxWidth().height(4.dp).background(ACCENT))
            else if (c.pct in 1..99) Box(Modifier.align(Alignment.BottomStart).fillMaxWidth(c.pct / 100f).height(4.dp).background(ACCENT))
        }
    }
}

/**
 * Episódios da série (43.5): pílulas (Série · Temporada 1 · 2 …), logo e dados do episódio em foco (`T1 • E2  data  duração`, sinopse,
 * direção), selos técnicos, fileira de cartões 16:9, botões circulares do episódio em foco (Reproduzir/Continuar, Do início, Minha Lista da
 * série, Assistido) e Elenco & Equipe. Tudo numa lista que rola; o foco inicial é o primeiro episódio não assistido.
 */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun SeasonDetail(
    server: String, token: String, profileId: Long, d: Detail, inList: Boolean, notice: String, epWatched: Map<Long, Boolean>, first: FocusRequester,
    onPlay: (String, String, Int) -> Unit, onSetWatched: (Long, Boolean) -> Unit, onToggleList: () -> Unit, onOpen: (TvCard) -> Unit, onUnauthorized: () -> Unit,
) {
    val eps = d.episodes
    // 57.21: foco inicial no episódio em andamento; se o último com progresso já foi todo assistido, no seguinte; sem progresso, no 1º
    val startIdx = remember(d) {
        val last = eps.indexOfLast { it.watched || it.pct in 1..99 }
        when { last < 0 -> 0; !eps[last].watched -> last; last + 1 < eps.size -> last + 1; else -> 0 }
    }
    var fe by remember(d) { mutableStateOf(eps.getOrNull(startIdx)) }
    var info by remember(d) { mutableStateOf<EpInfo?>(null) }
    var hint by remember { mutableStateOf("") }
    val frEp = remember { FocusRequester() }
    // 57.29: um FocusRequester por episódio + o último focado + quais estão compostos; ao voltar de baixo (botões) o foco retorna ao episódio de onde saiu
    val epReqs = remember(eps.size) { List(eps.size) { FocusRequester() } }
    var lastEp by remember { androidx.compose.runtime.mutableIntStateOf(startIdx) }
    val liveEps = remember { mutableSetOf<Int>() }
    val frAct = remember { FocusRequester() }
    val frCast = remember { FocusRequester() }
    val frRev = remember { FocusRequester() }
    var showAll by remember { mutableStateOf(false) }
    if (showAll) ReviewsDialog(d.reviews) { showAll = false }
    val rowState = androidx.compose.foundation.lazy.rememberLazyListState(initialFirstVisibleItemIndex = startIdx)
    LaunchedEffect(fe?.id) {
        val c = fe ?: return@LaunchedEffect
        kotlinx.coroutines.delay(200)
        info = try { withContext(Dispatchers.IO) { TvDetailApi.episodeInfo(server, token, profileId, c.id) } } catch (e: TvUnauthorized) { onUnauthorized(); null }
    }
    val c = fe
    val i = info?.takeIf { it.id == c?.id }
    val isWatched = c != null && (epWatched[c.id] ?: c.watched)
    val showCard = TvCard("show", d.showId, d.title, "", "", 0, false, false, null, 0L)
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = DRAWER_INSET + 16.dp, top = 20.dp, end = 32.dp, bottom = 40.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item("head") {
            Column {
                // pílulas numa fileira que rola (séries com 8+ temporadas espremiam as últimas e o texto quebrava letra a letra, esticando a linha)
                val pillState = androidx.compose.foundation.lazy.rememberLazyListState()
                val cur = remember(d) { d.seasonNums.indexOfFirst { d.meta == (if (it == 0) "Especiais" else "Temporada $it") } + 1 }
                LaunchedEffect(cur) { pillState.scrollToItem((cur - 2).coerceAtLeast(0)) }
                val curPill = remember { FocusRequester() }
                val scope = rememberCoroutineScope()
                // ↑ do conteúdo cai na temporada atual (não na 1ª); ao sair, a fileira volta a mostrar a atual para o foco poder retornar a ela
                PillGroup(if (cur > 0) curPill else null, Modifier.fillMaxWidth(), onLeave = { scope.launch { pillState.scrollToItem((cur - 2).coerceAtLeast(0)) } }) {
                LazyRow(Modifier.fillMaxWidth(), state = pillState, contentPadding = PaddingValues(end = 48.dp)) {
                    item { SeasonPill("Série", false) { onOpen(showCard) } }
                    items(d.seasonNums.size) { k ->
                        val n = d.seasonNums[k]
                        val lbl = if (n == 0) "Especiais" else "Temporada $n"
                        SeasonPill(lbl, d.meta == lbl, if (d.meta == lbl) Modifier.focusRequester(curPill) else Modifier) { onOpen(TvCard("season", d.showId, "", "", "", 0, false, false, null, 0L, n)) }
                    }
                }
                }
                Spacer(Modifier.height(8.dp))
                if (d.logo != null) RetryAsyncImage(model = server + d.logo, contentDescription = d.title, contentScale = ContentScale.Fit,
                    alignment = Alignment.CenterStart, modifier = Modifier.height(64.dp).width(300.dp))
                else Text(d.title, color = TEXT, fontSize = 34.sp, fontWeight = FontWeight.Black, maxLines = 1, overflow = TextOverflow.Ellipsis)
                // 57.20: título, selos, sinopse e direção ocupam sempre o mesmo espaço (com ou sem texto), para o layout não pular ao trocar de episódio
                val dens = androidx.compose.ui.platform.LocalDensity.current
                fun lines(n: Int, lh: androidx.compose.ui.unit.TextUnit) = with(dens) { (lh * n).toDp() }
                val ttl = i?.title.orEmpty().ifEmpty { c?.title.orEmpty() }
                Text(ttl, color = TEXT, fontSize = 18.sp, lineHeight = 24.sp, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.height(lines(1, 24.sp)))
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 2.dp)) {
                    Text(i?.meta ?: c?.sub.orEmpty(), color = MUTED, fontSize = 12.sp, maxLines = 1)
                    if (d.contentRating.isNotEmpty()) Text(d.contentRating, color = TEXT, fontSize = 11.sp, fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(start = 8.dp).background(Color.Black, RoundedCornerShape(3.dp)).padding(horizontal = 5.dp, vertical = 1.dp))
                }
                Row(Modifier.padding(top = 4.dp).height(22.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    i?.badges?.forEach { Text(it, color = TEXT, fontSize = 11.sp, fontWeight = FontWeight.Bold, modifier = Modifier.background(Color(0x66000000), RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 2.dp)) }
                }
                Text(i?.overview.orEmpty(), color = TEXT, fontSize = 13.sp, lineHeight = 18.sp, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp).width(640.dp).height(lines(2, 18.sp)))
                Text(if (i?.directors.isNullOrEmpty()) "" else "Dirigido por ${i!!.directors}", color = MUTED, fontSize = 12.sp, lineHeight = 16.sp, maxLines = 1, modifier = Modifier.padding(top = 4.dp).height(lines(1, 16.sp)))
            }
        }
        item("tech") {
            Row(Modifier.fillMaxWidth().height(22.dp), horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End)) {
                i?.tech?.forEach { Text(it, color = TEXT, fontSize = 11.sp, fontWeight = FontWeight.Bold, modifier = Modifier.background(Color(0xCC000000), RoundedCornerShape(4.dp)).padding(horizontal = 7.dp, vertical = 3.dp)) }
            }
        }
        item("eps") {
            EpisodesEnter(epReqs, liveEps, { lastEp }, startIdx, rowState) { LazyRow(state = rowState, horizontalArrangement = Arrangement.spacedBy(14.dp), contentPadding = PaddingValues(start = 12.dp, end = 48.dp, top = 8.dp, bottom = 10.dp)) {
                items(eps.size, key = { eps[it].id }) { idx ->
                    val e = eps[idx]
                    androidx.compose.runtime.DisposableEffect(idx) { liveEps.add(idx); onDispose { liveEps.remove(idx) } }
                    EpisodeCard(server, e, epWatched[e.id] ?: e.watched, onFocus = { fe = it; lastEp = idx }, onPlay = { x -> if (x.play != null) onPlay(x.play, x.title, x.n) },
                        modifier = (if (idx == startIdx) Modifier.focusRequester(first) else Modifier).let { if (idx == 0) it.focusRequester(frEp) else it }.focusRequester(epReqs[idx]))
                }
            } }
        }
        item("actions") {
            EnterAt(frAct) {             Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                if (c?.play != null) CircleBtn(if (c.n > 0 && !isWatched) "Continuar" else "Reproduzir", { hint = it }, Modifier.focusRequester(frAct), { onPlay(c.play, c.title, c.n) }) { iconPlay(it) }
                if (c?.play != null && c.n > 0 && !isWatched) CircleBtn("Do início", { hint = it }, Modifier, { onPlay(c.play, c.title, -1) }) { iconRestart(it) }
                CircleBtn(if (inList) "Remover a série da Minha Lista" else "Adicionar a série à Minha Lista", { hint = it }, if (c?.play == null) Modifier.focusRequester(frAct) else Modifier, onToggleList) { iconList(it, inList) }
                if (c != null) CircleBtn(if (isWatched) "Marcar como não assistido" else "Marcar como assistido", { hint = it }, Modifier, { onSetWatched(c.id, !isWatched) }) { iconCheck(it, isWatched) }
                Text(if (notice.isNotEmpty()) notice else hint, color = if (notice.isNotEmpty()) Color(0xFFE57373) else MUTED, fontSize = 12.sp, modifier = Modifier.padding(start = 6.dp))
            } }
        }
        if (d.cast.isNotEmpty()) item("cast") {
            Column {
                Text("Elenco & Equipe", color = TEXT, fontSize = 18.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(bottom = 4.dp))
                FirstEnter(frCast) { st -> LazyRow(state = st, horizontalArrangement = Arrangement.spacedBy(14.dp), contentPadding = PaddingValues(start = 12.dp, end = 48.dp, top = 8.dp, bottom = 8.dp)) {
                    items(d.cast, key = { it.name + it.role }) { x -> CastCircle(server, x, if (x === d.cast.first()) Modifier.focusRequester(frCast) else Modifier) }
                } }
            }
        }
        if (d.reviews.isNotEmpty()) item("reviews") { ReviewsRow(d.reviews, frRev) { showAll = true } }
    }
}

private fun DrawScope.star(cx: Float, cy: Float, r: Float, c: Color, filled: Boolean) {
    val p = Path()
    for (k in 0 until 10) {
        val rad = if (k % 2 == 0) r else r * 0.45f
        val a = Math.PI / 5 * k - Math.PI / 2
        val x = cx + (rad * Math.cos(a)).toFloat()
        val y = cy + (rad * Math.sin(a)).toFloat()
        if (k == 0) p.moveTo(x, y) else p.lineTo(x, y)
    }
    p.close()
    if (filled) drawPath(p, c) else drawPath(p, c, style = Stroke(1.2.dp.toPx()))
}

/** Cinco estrelas para a nota 0–10 (cada estrela = 2 pontos; mesma regra do site). */
@Composable
private fun Stars(rating: Double, modifier: Modifier = Modifier) {
    Canvas(modifier.size(90.dp, 16.dp)) {
        val r = size.height / 2
        for (i in 0 until 5) star(r + i * (size.width - 2 * r) / 4, r, r, ACCENT, rating >= 2 * (i + 1) - 1)
    }
}

private fun reviewDate(raw: String): String = try {
    java.text.SimpleDateFormat("d 'de' MMMM 'de' yyyy", java.util.Locale("pt", "BR")).format(java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.US).parse(raw.take(10))!!)
} catch (e: Exception) { raw }

@Composable
private fun ReviewHead(r: Review) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(r.author.take(1).uppercase(), color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold,
            modifier = Modifier.size(32.dp).background(Color(0xFFB04A8A), CircleShape).wrapContentSize())
        Column(Modifier.padding(start = 10.dp)) {
            Text(r.author, color = TEXT, fontSize = 13.sp, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (r.created.isNotEmpty()) Text(reviewDate(r.created), color = MUTED, fontSize = 11.sp)
        }
    }
}

/** Avaliações & Análises (43.6): cartões com avatar, nome, data, estrelas e texto cortado, mais \"Ver todos\". Sem análises = bloco oculto. */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun ReviewsRow(reviews: List<Review>, first: FocusRequester? = null, onAll: () -> Unit) {
    Column {
        Text("Avaliações & Análises", color = TEXT, fontSize = 18.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(bottom = 4.dp))
        FirstEnter(first) { st -> LazyRow(state = st, horizontalArrangement = Arrangement.spacedBy(14.dp), contentPadding = PaddingValues(start = 12.dp, end = 48.dp, top = 8.dp, bottom = 8.dp)) {
            items(reviews.take(8).size, key = { it }) { i ->
                val r = reviews[i]
                Card(onClick = onAll, shape = CardDefaults.shape(RoundedCornerShape(10.dp)), colors = CardDefaults.colors(containerColor = Color(0x66000000)),
                    border = CardDefaults.border(focusedBorder = Border(BorderStroke(3.dp, Color.White))), modifier = Modifier.size(300.dp, 140.dp).let { if (i == 0 && first != null) it.focusRequester(first) else it }) {
                    Column(Modifier.padding(12.dp)) {
                        ReviewHead(r)
                        if (r.rating > 0) Stars(r.rating, Modifier.padding(top = 6.dp))
                        Text(r.text.replace("\n", " "), color = TEXT, fontSize = 12.sp, maxLines = 3, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
                    }
                }
            }
            item("all") {
                Card(onClick = onAll, shape = CardDefaults.shape(RoundedCornerShape(50)), colors = CardDefaults.colors(containerColor = Color(0x66000000)),
                    border = CardDefaults.border(focusedBorder = Border(BorderStroke(3.dp, Color.White)))) {
                    Text("Ver todos", color = TEXT, fontSize = 14.sp, modifier = Modifier.padding(horizontal = 22.dp, vertical = 10.dp))
                }
            }
        } }
    }
}

/** \"Ver todos\": todas as análises com o texto inteiro, numa lista que rola; Voltar fecha. */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun ReviewsDialog(reviews: List<Review>, onClose: () -> Unit) {
    androidx.compose.ui.window.Dialog(onDismissRequest = onClose, properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false)) {
        Box(Modifier.fillMaxSize().background(Color(0xF2101214)).padding(horizontal = 80.dp, vertical = 32.dp)) {
            Column {
                Text("Avaliações & Análises", color = TEXT, fontSize = 22.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(bottom = 12.dp))
                LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp), contentPadding = PaddingValues(bottom = 40.dp)) {
                    items(reviews.size, key = { it }) { i ->
                        val r = reviews[i]
                        Card(onClick = {}, shape = CardDefaults.shape(RoundedCornerShape(10.dp)), colors = CardDefaults.colors(containerColor = Color(0x33FFFFFF)),
                            border = CardDefaults.border(focusedBorder = Border(BorderStroke(3.dp, Color.White))), modifier = Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(14.dp)) {
                                ReviewHead(r)
                                if (r.rating > 0) Stars(r.rating, Modifier.padding(top = 6.dp))
                                Text(r.text, color = TEXT, fontSize = 14.sp, modifier = Modifier.padding(top = 8.dp))
                            }
                        }
                    }
                }
            }
        }
    }
}
