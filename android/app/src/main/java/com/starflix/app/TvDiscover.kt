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
            Text("Procurando seu servidor…", color = Color(0xFFEEEEEE), fontSize = 30.sp, fontWeight = FontWeight.Bold)
            Text("A TV e o servidor precisam estar na mesma rede.", color = Color(0xFF9A9EA3), fontSize = 18.sp)
        } else {
            Text("Escolha o servidor", color = Color(0xFFEEEEEE), fontSize = 30.sp, fontWeight = FontWeight.Bold)
            found.forEachIndexed { i, (info, url) ->
                TvButton("${info.name}  ·  $url", Modifier.width(640.dp).let { if (i == 0) it.focusRequester(first) else it }, centered = true) { onChosen(info, url) }
            }
        }
    }
}

/**
 * 58.15: "Conectar pelo celular": a TV mostra o QR `starflix://tvpair?ip&port&k&n` e espera o celular (já conectado ao servidor) enviar o ticket
 * ao mini servidor. Recebido, `onPaired(info, endereço, token)`; a TV vai direto aos perfis. Sem rede ou com o tempo esgotado, avisa e oferece outro QR. "Digitar endereço" (58.17, último recurso) abre a tela de endereço com teclado.
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
                Image(bmp, contentDescription = "QR code para conectar pelo celular", modifier = Modifier.fillMaxSize())
            } else {
                Text("Sem QR", color = Color.Black, fontSize = 20.sp)
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text("Conectar pelo celular", color = Color(0xFFEEEEEE), fontSize = 30.sp, fontWeight = FontWeight.Bold)
            when (state) {
                "run" -> {
                    Text(
                    "No celular com o app StarFlix já conectado, abra Configurações → Conectar uma TV, toque em Ler QR code da TV e aponte para o QR ao lado. O celular e a TV precisam estar na mesma rede.",
                    color = Color(0xFF9A9EA3), fontSize = 18.sp, modifier = Modifier.width(560.dp),
                )
                    TvButton("Digitar endereço", Modifier.focusRequester(btn)) { onAddress() }
                }
                "noip" -> {
                    Text("A TV está sem Wi-Fi nem Ethernet. Conecte-a à rede e tente de novo.", color = Color(0xFFE57373), fontSize = 18.sp, modifier = Modifier.width(560.dp))
                    TvButton("Tentar de novo", Modifier.focusRequester(btn)) { gen++ }
                    TvButton("Digitar endereço") { onAddress() }
                }
                else -> {
                    Text("Tempo esgotado. Gere um QR novo.", color = Color(0xFFE57373), fontSize = 18.sp, modifier = Modifier.width(560.dp))
                    TvButton("Gerar QR novo", Modifier.focusRequester(btn)) { gen++ }
                    TvButton("Digitar endereço") { onAddress() }
                }
            }
        }
    }
}
