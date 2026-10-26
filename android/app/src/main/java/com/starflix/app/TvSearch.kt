package com.starflix.app

import android.app.Activity
import android.content.Intent
import android.speech.RecognizerIntent
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.tv.material3.Text
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.net.URLEncoder

sealed class ListResult {
    data class Ok(val items: List<TvCard>) : ListResult()
    object Unauthorized : ListResult()
    data class Err(val msg: String) : ListResult()
}

/** Busca (`/api/tv/search?q=`) e Minha Lista (`/api/tv/mylist`) da TV (40.13). */
object TvSearchApi {
    fun search(server: String, token: String, profile: Long, q: String): ListResult = try {
        val (code, j) = TvApi.authed("GET", server, "/api/tv/search?q=" + URLEncoder.encode(q, "UTF-8"), token, profile)
        if (code != 200 || j == null) ListResult.Err("Erro do servidor ($code).") else {
            val all = listOf("movies", "shows", "videos", "collections").flatMap { k ->
                j.optJSONArray(k)?.let { a -> (0 until a.length()).map { TvHomeApi.parseCard(a.getJSONObject(it)) } }.orEmpty()
            }
            ListResult.Ok(all.map { it.copy(wide = false) })  // grade uniforme: miniatura de vídeo também em cartão de pôster
        }
    } catch (e: TvUnauthorized) {
        ListResult.Unauthorized
    } catch (e: Exception) {
        ListResult.Err("Servidor inacessível.")
    }

    fun myList(server: String, token: String, profile: Long): ListResult = try {
        val (code, j) = TvApi.authed("GET", server, "/api/tv/mylist", token, profile)
        if (code != 200 || j == null) ListResult.Err("Erro do servidor ($code).") else {
            val a = j.optJSONArray("items")
            ListResult.Ok((0 until (a?.length() ?: 0)).map { TvHomeApi.parseCard(a!!.getJSONObject(it)) }.map { it.copy(wide = false) })
        }
    } catch (e: TvUnauthorized) {
        ListResult.Unauthorized
    } catch (e: Exception) {
        ListResult.Err("Servidor inacessível.")
    }
}

private val BG = Color(0xFF1F2326)
private val TEXT = Color(0xFFEEEEEE)
private val MUTED = Color(0xFF9A9EA3)
private val ERR = Color(0xFFE57373)

@Composable
private fun CardGrid(server: String, items: List<TvCard>, onOpen: (TvCard) -> Unit, modifier: Modifier = Modifier, firstFocus: FocusRequester? = null) {
    val st = androidx.compose.foundation.lazy.grid.rememberLazyGridState()
    val sc = androidx.compose.runtime.rememberCoroutineScope()
    val nav = remember(st) { GridNav(st, sc) }
    nav.total = items.size
    GridEnter(nav, 140f, 14f, 28f, modifier) {
        LazyVerticalGrid(
            columns = GridCells.Adaptive(140.dp), modifier = Modifier.fillMaxSize(), state = st,
            contentPadding = PaddingValues(start = 12.dp, top = 12.dp, bottom = 40.dp, end = 16.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp), horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            items(count = items.size, key = { items[it].type + items[it].id }) { i ->
                PosterCard(server, items[i], onFocus = {}, onOpen = onOpen, modifier = (if (i == 0 && firstFocus != null) Modifier.focusRequester(firstFocus) else Modifier).then(nav.item(i)))
            }
        }
    }
}

/**
 * Busca (40.13): teclado na tela à esquerda (D-pad), resultados em grade à direita, busca 400 ms depois da última tecla.
 * "Ditar" só aparece quando o aparelho tem reconhecimento de voz. Voltar → Início; 401 → `onUnauthorized`.
 */
@Composable
fun SearchScreen(
    server: String, token: String, profileId: Long, initialQuery: String,
    onQuery: (String) -> Unit, onOpen: (TvCard) -> Unit, onBack: () -> Unit, onUnauthorized: () -> Unit,
) {
    var q by remember { mutableStateOf(initialQuery) }
    var res by remember { mutableStateOf<ListResult?>(null) }
    var retry by remember { mutableStateOf(0) }
    val first = remember { FocusRequester() }
    val ctx = LocalContext.current
    BackHandler { onBack() }
    LaunchedEffect(Unit) { runCatching { first.requestFocus() } }

    val speechIntent = remember {
        Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "pt-BR")
    }
    val canSpeak = remember { speechIntent.resolveActivity(ctx.packageManager) != null }
    val speech = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        if (r.resultCode == Activity.RESULT_OK) r.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()?.let { q = it.take(100) }
    }

    LaunchedEffect(q, retry) {
        onQuery(q)
        if (q.isBlank()) { res = null; return@LaunchedEffect }
        delay(400)
        when (val r = withContext(Dispatchers.IO) { TvSearchApi.search(server, token, profileId, q.trim()) }) {
            is ListResult.Unauthorized -> onUnauthorized()
            else -> res = r
        }
    }

    Row(Modifier.fillMaxSize().background(BG).padding(start = DRAWER_INSET + 8.dp, top = 28.dp), horizontalArrangement = Arrangement.spacedBy(32.dp)) {
        Column(Modifier.width(400.dp)) {
            Box(Modifier.width(400.dp).background(Color(0xFF2F3236), RoundedCornerShape(8.dp)).padding(14.dp)) {
                Text(if (q.isEmpty()) "Buscar filmes e séries" else q, color = if (q.isEmpty()) MUTED else TEXT, fontSize = 24.sp, maxLines = 1)
            }
            Spacer(Modifier.height(12.dp))
            val rows = listOf("abcdef", "ghijkl", "mnopqr", "stuvwx", "yz1234", "567890")
            val kreq = remember(canSpeak) { List(rows.size + 1 + if (canSpeak) 1 else 0) { FocusRequester() } }
            rows.forEachIndexed { r, row ->
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(vertical = 3.dp)) {
                    row.forEachIndexed { i, ch ->
                        TvButton(ch.toString(), Modifier.width(60.dp).let { if (r == 0 && i == 0) it.focusRequester(first) else it }.rowNav(kreq, r, i)) { if (q.length < 100) q += ch }
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(top = 6.dp)) {
                TvButton("Espaço", Modifier.width(126.dp).rowNav(kreq, rows.size, 0)) { if (q.isNotEmpty() && !q.endsWith(" ")) q += " " }
                TvButton("Apagar", Modifier.width(126.dp).rowNav(kreq, rows.size, 1)) { q = q.dropLast(1) }
                TvButton("Limpar", Modifier.width(126.dp).rowNav(kreq, rows.size, 2)) { q = "" }
            }
            if (canSpeak) TvButton("Ditar", Modifier.width(390.dp).padding(top = 6.dp).rowNav(kreq, rows.size + 1, 0)) {
                runCatching { speech.launch(speechIntent) }
            }
        }
        Box(Modifier.fillMaxSize()) {
            val r = res
            when {
                q.isBlank() -> Text("Digite para buscar.", color = MUTED, fontSize = 20.sp, modifier = Modifier.align(Alignment.Center))
                r == null -> Text("Buscando…", color = MUTED, fontSize = 20.sp, modifier = Modifier.align(Alignment.Center))
                r is ListResult.Err -> Column(Modifier.align(Alignment.Center), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(r.msg, color = ERR, fontSize = 20.sp)
                    Spacer(Modifier.height(16.dp))
                    TvButton("Tentar de novo", Modifier.width(260.dp)) { res = null; retry++ }
                }
                r is ListResult.Ok && r.items.isEmpty() -> Text("Nada encontrado para \"${q.trim()}\".", color = MUTED, fontSize = 20.sp, modifier = Modifier.align(Alignment.Center))
                r is ListResult.Ok -> CardGrid(server, r.items, onOpen, Modifier.fillMaxSize())
            }
        }
    }
}

/** Minha Lista (menu do Início): grade dos itens do perfil. Voltar → Início. */
@Composable
fun MyListScreen(server: String, token: String, profileId: Long, onOpen: (TvCard) -> Unit, onBack: () -> Unit, onUnauthorized: () -> Unit) {
    var res by remember { mutableStateOf<ListResult?>(null) }
    var reload by remember { mutableStateOf(0) }
    val first = remember { FocusRequester() }
    BackHandler { onBack() }
    LaunchedEffect(reload) {
        res = null
        when (val r = withContext(Dispatchers.IO) { TvSearchApi.myList(server, token, profileId) }) {
            is ListResult.Unauthorized -> onUnauthorized()
            else -> res = r
        }
    }
    LaunchedEffect(res) { if (res != null) runCatching { first.requestFocus() } }
    Column(Modifier.fillMaxSize().background(BG).padding(start = DRAWER_INSET + 8.dp, top = 28.dp, end = 24.dp)) {
        Text("Minha Lista", color = TEXT, fontSize = 30.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(12.dp))
        Box(Modifier.fillMaxSize()) {
            val r = res
            when {
                r == null -> Text("Carregando…", color = MUTED, fontSize = 20.sp, modifier = Modifier.align(Alignment.Center))
                r is ListResult.Err -> Column(Modifier.align(Alignment.Center), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(r.msg, color = ERR, fontSize = 20.sp)
                    Spacer(Modifier.height(16.dp))
                    TvButton("Tentar de novo", Modifier.width(260.dp).focusRequester(first)) { reload++ }
                }
                r is ListResult.Ok && r.items.isEmpty() -> Text("Sua lista está vazia. Adicione itens pela página de detalhes.", color = MUTED, fontSize = 20.sp, modifier = Modifier.align(Alignment.Center))
                r is ListResult.Ok -> CardGrid(server, r.items, onOpen, Modifier.fillMaxSize(), first)
            }
        }
    }
}
