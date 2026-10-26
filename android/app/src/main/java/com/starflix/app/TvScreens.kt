package com.starflix.app

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextAlign
import coil.compose.AsyncImage
import android.graphics.Bitmap
import android.os.Build
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Border
import androidx.tv.material3.Button
import androidx.tv.material3.ClickableSurfaceDefaults
import androidx.tv.material3.ExperimentalTvMaterial3Api
import androidx.tv.material3.Surface
import androidx.tv.material3.ButtonDefaults
import androidx.tv.material3.Text
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private val BG = Color(0xFF1F2326)
private val ACCENT = Color(0xFFE5A00D)
private val TEXT = Color(0xFFEEEEEE)
private val MUTED = Color(0xFF9A9EA3)
private val CARD = Color(0xFF2F3236)

@Composable
private fun Logo(size: Int = 44) {
    Text(
        buildAnnotatedString {
            withStyle(SpanStyle(color = TEXT)) { append("Star") }
            withStyle(SpanStyle(color = ACCENT)) { append("Flix") }
        },
        fontSize = size.sp,
        fontWeight = FontWeight.Bold,
    )
}

@Composable
internal fun TvButton(label: String, modifier: Modifier = Modifier, centered: Boolean = false, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        modifier = modifier,
        colors = ButtonDefaults.colors(
            containerColor = CARD, contentColor = TEXT,
            focusedContainerColor = ACCENT, focusedContentColor = Color.Black,
        ),
    ) { if (centered) Text(label, fontSize = 20.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth()) else Text(label, fontSize = 20.sp, fontWeight = FontWeight.Bold) }
}

internal fun qrBitmap(text: String, size: Int = 480): Bitmap {
    val m = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, size, size, mapOf(EncodeHintType.MARGIN to 1))
    val px = IntArray(size * size) { i -> if (m.get(i % size, i / size)) 0xFF000000.toInt() else 0xFFFFFFFF.toInt() }
    return Bitmap.createBitmap(px, size, size, Bitmap.Config.ARGB_8888)
}

/**
 * Tela de pareamento: QR code (gerado aqui) + código de 6 caracteres + endereço /tv. Consulta o servidor a cada 2 s;
 * ao vencer (ou se o servidor não conhecer mais o código) pede outro sozinha. Autorizado: `onPaired(token)`.
 */
@Composable
fun PairScreen(server: String, onPaired: (token: String) -> Unit) {
    var info by remember { mutableStateOf<CodeResult.Ok?>(null) }
    var error by remember { mutableStateOf("") }
    var retry by remember { mutableStateOf(0) }  // 58.18: "Tentar de novo" recomeça na hora (sem esperar os 5 s)
    val retryFocus = remember { FocusRequester() }
    LaunchedEffect(error.isNotEmpty()) { if (error.isNotEmpty()) { delay(150); runCatching { retryFocus.requestFocus() } } }
    LaunchedEffect(server, retry) {
        var cur: CodeResult.Ok? = null

        suspend fun fetch(): CodeResult.Ok? = when (val r = withContext(Dispatchers.IO) { TvApi.requestCode(server, Build.MODEL ?: "TV") }) {
            is CodeResult.Ok -> r
            is CodeResult.Err -> { error = r.msg; null }
        }

        while (true) {
            val c = cur ?: fetch()?.also { cur = it; info = it; error = "" }
            if (c == null) { delay(5000); continue }
            delay(2000)
            val poll = c.poll
            when (val p = withContext(Dispatchers.IO) { TvApi.poll(server, poll) }) {
                is PollResult.Pending -> error = ""
                is PollResult.Authorized -> { onPaired(p.token); return@LaunchedEffect }
                is PollResult.Expired -> { cur = null; info = null }
                is PollResult.Err -> error = p.msg
            }
        }
    }

    Row(Modifier.fillMaxSize().background(BG).padding(80.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(64.dp)) {
        Box(Modifier.size(320.dp).background(Color.White, RoundedCornerShape(12.dp)).padding(12.dp), contentAlignment = Alignment.Center) {
            val i = info
            if (i != null) {
                val bmp = remember(i.code, server) { qrBitmap("$server/tv?code=${i.code}").asImageBitmap() }
                Image(bmp, contentDescription = "QR code de pareamento", modifier = Modifier.fillMaxSize())
            } else {
                Text("Gerando código…", color = Color.Black, fontSize = 20.sp)
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Logo(40)
            Text("Conecte esta TV à sua conta", color = TEXT, fontSize = 30.sp, fontWeight = FontWeight.Bold)
            Text("Escaneie o QR code com o celular ou abra o endereço abaixo no navegador e digite o código.", color = MUTED, fontSize = 18.sp, modifier = Modifier.width(560.dp))
            Text("$server/tv", color = TEXT, fontSize = 24.sp)
            Text(info?.code?.chunked(3)?.joinToString(" ") ?: "······", color = ACCENT, fontSize = 64.sp, fontWeight = FontWeight.Bold)
            Text(error, color = Color(0xFFE57373), fontSize = 16.sp, modifier = Modifier.height(22.dp))
            if (error.isNotEmpty()) TvButton("Tentar de novo", Modifier.width(260.dp).focusRequester(retryFocus)) { error = ""; info = null; retry++ }
        }
    }
}

/**
 * Escolha de perfil (40.9): avatares (cor + inicial) em grade, foco D-pad. Escolher valida no servidor (`POST /api/tv/profile/<id>`)
 * e chama `onPicked(perfil)`. Token revogado (401) chama `onUnauthorized()` (volta ao pareamento); Voltar = desconectar esta TV.
 */
@OptIn(ExperimentalLayoutApi::class, ExperimentalTvMaterial3Api::class)
@Composable
fun ProfileScreen(server: String, token: String, onPicked: (TvProfile) -> Unit, onUnauthorized: () -> Unit, onExit: () -> Unit) {
    var profiles by remember { mutableStateOf<List<TvProfile>?>(null) }
    var error by remember { mutableStateOf("") }
    var reload by remember { mutableStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val first = remember { FocusRequester() }
    BackHandler { onExit() }  // Voltar fecha o app; desconectar é o botão abaixo

    LaunchedEffect(reload) {
        error = ""
        when (val r = withContext(Dispatchers.IO) { TvApi.profiles(server, token) }) {
            is ProfilesResult.Ok -> profiles = r.profiles
            is ProfilesResult.Unauthorized -> onUnauthorized()
            is ProfilesResult.Err -> { error = r.msg; profiles = null }
        }
    }
    LaunchedEffect(profiles) { if (!profiles.isNullOrEmpty()) runCatching { first.requestFocus() } }

    fun pick(p: TvProfile) {
        if (busy) return
        busy = true
        scope.launch {
            val ok = withContext(Dispatchers.IO) { TvApi.pickProfile(server, token, p.id) }
            busy = false
            when (ok) {
                true -> onPicked(p)
                null -> onUnauthorized()
                false -> error = "Não foi possível escolher o perfil."
            }
        }
    }

    Column(Modifier.fillMaxSize().background(BG).padding(horizontal = 80.dp, vertical = 36.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Logo(36)
        Spacer(Modifier.height(12.dp))
        Text("Quem está assistindo?", color = TEXT, fontSize = 28.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(24.dp))
        val list = profiles
        when {
            list == null && error.isEmpty() -> Text("Carregando perfis…", color = MUTED, fontSize = 20.sp)
            list == null -> {
                Text(error, color = Color(0xFFE57373), fontSize = 18.sp)
                Spacer(Modifier.height(16.dp))
                TvButton("Tentar de novo", Modifier.width(260.dp).focusRequester(first)) { profiles = null; reload++ }
            }
            list.isEmpty() -> Text("Nenhum perfil. Crie um perfil no site e tente de novo.", color = MUTED, fontSize = 20.sp)
            else -> EnterAt(first) { FlowRow(horizontalArrangement = Arrangement.spacedBy(28.dp), verticalArrangement = Arrangement.spacedBy(28.dp)) {
                list.forEachIndexed { i, p ->
                    val color = runCatching { Color(android.graphics.Color.parseColor(p.color)) }.getOrDefault(ACCENT)
                    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.width(140.dp)) {
                        Surface(
                            onClick = { pick(p) },
                            modifier = Modifier.size(104.dp).let { if (i == 0) it.focusRequester(first) else it },
                            shape = ClickableSurfaceDefaults.shape(CircleShape),
                            colors = ClickableSurfaceDefaults.colors(containerColor = color, focusedContainerColor = color, contentColor = Color.White, focusedContentColor = Color.White),
                            border = ClickableSurfaceDefaults.border(focusedBorder = Border(BorderStroke(4.dp, ACCENT), shape = CircleShape)),
                            scale = ClickableSurfaceDefaults.scale(focusedScale = 1.12f),
                        ) {
                            var failed by remember(p.photo) { mutableStateOf(false) }
                            Box(Modifier.fillMaxSize().clip(CircleShape), contentAlignment = Alignment.Center) {
                                if (p.photo.isNotEmpty() && !failed) AsyncImage(
                                    model = server + p.photo, contentDescription = p.name, contentScale = ContentScale.Crop,
                                    onError = { failed = true }, modifier = Modifier.fillMaxSize(),
                                ) else Text(p.name.take(1).uppercase(), color = Color.White, fontSize = 44.sp, fontWeight = FontWeight.Bold)
                            }
                        }
                        Spacer(Modifier.height(12.dp))
                        Text(p.name, color = TEXT, fontSize = 20.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                    }
                }
            } }
        }
        if (error.isNotEmpty() && !list.isNullOrEmpty()) {
            Spacer(Modifier.height(20.dp))
            Text(error, color = Color(0xFFE57373), fontSize = 16.sp)
        }
    }
}
