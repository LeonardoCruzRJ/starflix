package com.starflix.app

import androidx.activity.compose.BackHandler
import android.net.Uri
import android.os.Build
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
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
import androidx.tv.material3.Text
import kotlinx.coroutines.delay

/**
 * 58.14: TV sem servidor salvo procura o StarFlix na rede (NSD, ~8 s). Um só achado segue sozinho (após ~2 s, para ver se há outros);
 * vários viram uma lista com D-pad; nenhum (ou Voltar) chama [onNone] (Conectar pelo celular, 58.15).
 */
@Composable
fun DiscoverScreen(onChosen: (ServerInfo, String) -> Unit, onNone: () -> Unit) {
    val ctx = LocalContext.current
    val found = remember { mutableStateListOf<Pair<ServerInfo, String>>() }
    var list by remember { mutableStateOf(false) }
    val first = remember { FocusRequester() }
    val disc = remember {
        ServerDiscovery(ctx) { info, url ->
            val dup = found.any { (info.id.isNotEmpty() && it.first.id == info.id) || it.second == url }
            if (!dup) found.add(info to url)
        }
    }
    DisposableEffect(Unit) { onDispose { disc.stop() } }
    BackHandler { onNone() }
    LaunchedEffect(Unit) {
        disc.start(8000)
        var t = 0
        var firstAt = -1
        while (t < 8000) {
            delay(250)
            t += 250
            if (found.size > 1) { list = true; return@LaunchedEffect }
            if (found.size == 1) {
                if (firstAt < 0) firstAt = t
                if (t - firstAt >= 2000) { onChosen(found[0].first, found[0].second); return@LaunchedEffect }
            }
        }
        when (found.size) {
            0 -> onNone()
            1 -> onChosen(found[0].first, found[0].second)
            else -> list = true
        }
    }
    LaunchedEffect(list) {
        if (list) { delay(150); try { first.requestFocus() } catch (e: Exception) { } }
    }
    Column(
        Modifier.fillMaxSize().background(Color(0xFF1F2326)).padding(80.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (!list) {
            Text(Txt.s(R.string.tv_searching), color = Color(0xFFEEEEEE), fontSize = 30.sp, fontWeight = FontWeight.Bold)
            Text(Txt.s(R.string.tv_same_network), color = Color(0xFF9A9EA3), fontSize = 18.sp)
        } else {
            Text(Txt.s(R.string.tv_choose_server), color = Color(0xFFEEEEEE), fontSize = 30.sp, fontWeight = FontWeight.Bold)
            found.forEachIndexed { i, (info, url) ->
                TvButton("${info.name}  ·  $url", Modifier.width(640.dp).let { if (i == 0) it.focusRequester(first) else it }, centered = true) { onChosen(info, url) }
            }
        }
    }
}

/**
 * 58.15: "Conectar pelo celular": a TV mostra o QR `starflix://tvpair?ip&port&k&n` e espera o celular (já conectado ao servidor) enviar o ticket
 * ao mini servidor. Recebido, `onPaired(info, endereço, token)`; a TV vai direto aos perfis. Sem rede ou com o tempo esgotado, avisa e oferece outro QR. Txt.s(R.string.tv_enter_address) (58.17, último recurso) abre a tela de endereço com teclado.
 */
@Composable
fun TvBridgeScreen(onPaired: (ServerInfo, String, String) -> Unit, onAddress: () -> Unit, onBack: () -> Unit) {
    var gen by remember { mutableStateOf(0) }
    var key by remember { mutableStateOf("") }
    var port by remember { mutableStateOf(0) }
    var state by remember { mutableStateOf("run") }  // run | noip | closed
    val ip = remember(gen) { TvBridgeServer.localIp() }
    val btn = remember { FocusRequester() }
    BackHandler { onBack() }
    DisposableEffect(gen) {
        if (ip == null) {
            state = "noip"
            onDispose { }
        } else {
            val srv = TvBridgeServer(onPaired = onPaired, onKey = { key = it }, onExpired = { state = "closed" })
            if (srv.start()) { key = srv.key; port = srv.port; state = "run" } else state = "noip"
            onDispose { srv.stop() }
        }
    }
    LaunchedEffect(state, gen) {
        delay(150)
        try { btn.requestFocus() } catch (e: Exception) { }
    }
    Row(
        Modifier.fillMaxSize().background(Color(0xFF1F2326)).padding(80.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(64.dp),
    ) {
        Box(Modifier.size(320.dp).background(Color.White, RoundedCornerShape(12.dp)).padding(12.dp), contentAlignment = Alignment.Center) {
            if (state == "run" && ip != null && key.isNotEmpty()) {
                val text = "starflix://tvpair?ip=$ip&port=$port&k=$key&n=${Uri.encode(Build.MODEL ?: "TV")}"
                val bmp = remember(text) { qrBitmap(text).asImageBitmap() }
                Image(bmp, contentDescription = Txt.s(R.string.tv_qr_desc), modifier = Modifier.fillMaxSize())
            } else {
                Text(Txt.s(R.string.tv_no_qr), color = Color.Black, fontSize = 20.sp)
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text(Txt.s(R.string.tv_connect_phone), color = Color(0xFFEEEEEE), fontSize = 30.sp, fontWeight = FontWeight.Bold)
            when (state) {
                "run" -> {
                    Text(
                    Txt.s(R.string.tv_connect_phone_help),
                    color = Color(0xFF9A9EA3), fontSize = 18.sp, modifier = Modifier.width(560.dp),
                )
                    TvButton(Txt.s(R.string.tv_enter_address), Modifier.focusRequester(btn)) { onAddress() }
                }
                "noip" -> {
                    Text(Txt.s(R.string.tv_no_network), color = Color(0xFFE57373), fontSize = 18.sp, modifier = Modifier.width(560.dp))
                    TvButton(Txt.s(R.string.retry), Modifier.focusRequester(btn)) { gen++ }
                    TvButton(Txt.s(R.string.tv_enter_address)) { onAddress() }
                }
                else -> {
                    Text(Txt.s(R.string.tv_qr_expired), color = Color(0xFFE57373), fontSize = 18.sp, modifier = Modifier.width(560.dp))
                    TvButton(Txt.s(R.string.tv_new_qr), Modifier.focusRequester(btn)) { gen++ }
                    TvButton(Txt.s(R.string.tv_enter_address)) { onAddress() }
                }
            }
        }
    }
}
