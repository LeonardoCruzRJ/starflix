package com.starflix.app

import androidx.tv.material3.SelectableSurfaceColors
import androidx.tv.material3.SelectableSurfaceDefaults
import androidx.tv.material3.Surface
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.ui.graphics.Brush
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.focusProperties
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import coil.compose.AsyncImage
import androidx.compose.ui.Alignment
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.activity.compose.BackHandler
import androidx.tv.material3.DrawerValue
import androidx.tv.material3.rememberDrawerState
import androidx.tv.material3.ExperimentalTvMaterial3Api
import androidx.tv.material3.LocalContentColor
import androidx.tv.material3.ModalNavigationDrawer
import androidx.tv.material3.Text


/** Largura da barra recolhida: cada tela recua o seu conteúdo (não o fundo) por este valor para não ficar sob a barra. */
val DRAWER_INSET = 56.dp

private val DRAWER_BG = Color(0xE60B0D10)   // painel aberto: escuro e levemente translúcido
private val PILL_BG = Color(0x73000000)     // pílula recolhida: bem translúcida (deixa ver a cor do fundo)
private val DRAWER_TEXT = Color(0xFFF2F2F2)
private val DRAWER_MUTED = Color(0xFFB8BCC2)
private val DRAWER_ACCENT = Color(0xFFE5A00D)

/** Ícones desenhados (as fontes da TV não têm todos os símbolos Unicode); seguem a cor do item (foco/seleção). */
@Composable
private fun DrawerIcon(kind: String) {
    val tint = LocalContentColor.current
    Canvas(Modifier.size(18.dp)) {
        val w = size.width
        val h = size.height
        val sw = 2.4.dp.toPx()
        when (kind) {
            "home" -> {
                // casinha em contorno (telhado + corpo) com porta
                val roof = androidx.compose.ui.graphics.Path().apply {
                    moveTo(w * 0.04f, h * 0.48f); lineTo(w * 0.5f, h * 0.06f); lineTo(w * 0.96f, h * 0.48f)
                }
                drawPath(roof, tint, style = Stroke(sw, cap = androidx.compose.ui.graphics.StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round))
                val body = androidx.compose.ui.graphics.Path().apply {
                    moveTo(w * 0.17f, h * 0.4f); lineTo(w * 0.17f, h * 0.94f); lineTo(w * 0.83f, h * 0.94f); lineTo(w * 0.83f, h * 0.4f)
                }
                drawPath(body, tint, style = Stroke(sw, cap = androidx.compose.ui.graphics.StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round))
                drawRect(tint, Offset(w * 0.4f, h * 0.6f), Size(w * 0.2f, h * 0.34f), style = Stroke(sw))
            }
            "movie" -> {
                // rolo de filme: retângulo arredondado, duas tiras laterais e furinhos
                drawRoundRect(tint, Offset(w * 0.08f, h * 0.06f), Size(w * 0.84f, h * 0.88f), androidx.compose.ui.geometry.CornerRadius(w * 0.1f), style = Stroke(sw))
                drawLine(tint, Offset(w * 0.28f, h * 0.06f), Offset(w * 0.28f, h * 0.94f), sw * 0.8f)
                drawLine(tint, Offset(w * 0.72f, h * 0.06f), Offset(w * 0.72f, h * 0.94f), sw * 0.8f)
                for (i in 0..2) {
                    val y = h * (0.25f + 0.25f * i)
                    drawLine(tint, Offset(w * 0.08f, y), Offset(w * 0.28f, y), sw * 0.8f)
                    drawLine(tint, Offset(w * 0.72f, y), Offset(w * 0.92f, y), sw * 0.8f)
                }
            }
            "show" -> {
                // monitor/TV: tela arredondada com pé e base
                drawRoundRect(tint, Offset(w * 0.04f, h * 0.1f), Size(w * 0.92f, h * 0.62f), androidx.compose.ui.geometry.CornerRadius(w * 0.08f), style = Stroke(sw))
                drawLine(tint, Offset(w / 2, h * 0.72f), Offset(w / 2, h * 0.9f), sw)
                drawLine(tint, Offset(w * 0.28f, h * 0.92f), Offset(w * 0.72f, h * 0.92f), sw, cap = androidx.compose.ui.graphics.StrokeCap.Round)
            }
            "menu" -> for (i in 0..2) {
                val y = h * (0.15f + 0.35f * i)
                drawLine(tint, Offset(0f, y), Offset(w, y), sw)
            }
            "search" -> {
                drawCircle(tint, w * 0.32f, Offset(w * 0.4f, h * 0.4f), style = Stroke(sw))
                drawLine(tint, Offset(w * 0.64f, h * 0.64f), Offset(w, h), sw)
            }
            "list" -> {
                drawLine(tint, Offset(w / 2, 0f), Offset(w / 2, h), sw)
                drawLine(tint, Offset(0f, h / 2), Offset(w, h / 2), sw)
            }
            "check" -> {
                drawRoundRect(tint, Offset(w * 0.06f, h * 0.06f), Size(w * 0.88f, h * 0.88f), androidx.compose.ui.geometry.CornerRadius(w * 0.16f), style = Stroke(sw))
                val tick = androidx.compose.ui.graphics.Path().apply {
                    moveTo(w * 0.27f, h * 0.52f); lineTo(w * 0.44f, h * 0.7f); lineTo(w * 0.75f, h * 0.3f)
                }
                drawPath(tick, tint, style = Stroke(sw, cap = androidx.compose.ui.graphics.StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round))
            }
            "box" -> drawRoundRect(tint, Offset(w * 0.06f, h * 0.06f), Size(w * 0.88f, h * 0.88f), androidx.compose.ui.geometry.CornerRadius(w * 0.16f), style = Stroke(sw))
            "user" -> {
                drawCircle(tint, w * 0.22f, Offset(w * 0.5f, h * 0.3f), style = Stroke(sw))
                drawArc(tint, 200f, 140f, false, Offset(w * 0.12f, h * 0.6f), Size(w * 0.76f, h * 0.7f), style = Stroke(sw, cap = androidx.compose.ui.graphics.StrokeCap.Round))
            }
            "exit" -> {
                drawLine(tint, Offset(w * 0.1f, h * 0.1f), Offset(w * 0.9f, h * 0.9f), sw)
                drawLine(tint, Offset(w * 0.9f, h * 0.1f), Offset(w * 0.1f, h * 0.9f), sw)
            }
        }
    }
}

/** Item do menu (próprio, no lugar do `NavigationDrawerItem`, cuja largura fixa de 280dp vazava do painel): aberto = ícone + texto; fechado = só o ícone. */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun DrawerRow(
    open: Boolean, selected: Boolean, onClick: () -> Unit, modifier: Modifier, colors: SelectableSurfaceColors,
    leading: @Composable () -> Unit, label: String, trailing: String? = null, maxLines: Int = 1,
) {
    Surface(
        selected = selected, onClick = onClick,
        modifier = (if (open) Modifier.fillMaxWidth() else Modifier.width(48.dp)).then(modifier),
        shape = SelectableSurfaceDefaults.shape(RoundedCornerShape(50)),
        colors = colors, scale = SelectableSurfaceDefaults.scale(focusedScale = 1f),
    ) {
        Row(Modifier.fillMaxSize().padding(horizontal = if (open) 12.dp else 0.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = if (open) Arrangement.Start else Arrangement.Center) {
            Box(Modifier.size(24.dp), contentAlignment = Alignment.Center) { leading() }
            if (open) {
                Spacer(Modifier.width(12.dp))
                Text(label, fontSize = 13.sp, maxLines = maxLines, modifier = Modifier.weight(1f))
                if (trailing != null) Text(trailing, fontSize = 13.sp)
            }
        }
    }
}

/** Foto escolhida pelo usuário em círculo; sem foto (ou se não carregar), círculo com a inicial e a cor do perfil. */
@Composable
private fun ProfileDot(server: String, name: String, color: String, photo: String, size: androidx.compose.ui.unit.Dp = 24.dp) {
    val c = runCatching { Color(android.graphics.Color.parseColor(color)) }.getOrDefault(DRAWER_ACCENT)
    var failed by remember(photo) { mutableStateOf(false) }
    Box(Modifier.size(size).clip(CircleShape).background(c), contentAlignment = Alignment.Center) {
        if (photo.isNotEmpty() && !failed) {
            AsyncImage(
                model = server + photo, contentDescription = name, contentScale = ContentScale.Crop,
                onError = { failed = true }, modifier = Modifier.fillMaxSize(),
            )
        } else {
            Text(name.take(1).uppercase(), color = Color.White, fontSize = (size.value / 2).sp, fontWeight = FontWeight.Bold)
        }
    }
}

/**
 * Barra lateral das telas da TV (43.1): fechada = ícones soltos (perfil, pesquisar, início, mais) por cima do conteúdo; aberta = painel arredondado por cima, sem empurrar o conteúdo. `selected` = "home" | "library:<id>" | "search" | "mylist".
 * `onNavigate` recebe "home", "library:<id>:<nome>", "search" ou "mylist".
 */
/** 57.30: ponte entre o menu lateral e a `TvActivity`: `close` só existe enquanto o menu está aberto. */
object TvDrawerBack {
    @Volatile var close: (() -> Unit)? = null
}

@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun TvDrawer(
    libs: List<TvLib>, selected: String, server: String, profileName: String, profileColor: String, profilePhoto: String,
    onNavigate: (String) -> Unit, onSwitchProfile: () -> Unit, onDisconnect: () -> Unit,
    content: @Composable () -> Unit,
) {
    val focus = androidx.compose.ui.platform.LocalFocusManager.current
    var userMenu by remember { mutableStateOf(false) }  // 57.10: popup do avatar (no lugar do menu "Mais")
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    // 57.30: com o menu aberto, Voltar o fecha em QUALQUER tela e onde quer que esteja o foco: a TvActivity pergunta a `TvDrawerBack` antes de a tecla chegar às telas
    val backScope = androidx.compose.runtime.rememberCoroutineScope()
    val menuOpen = drawerState.currentValue == DrawerValue.Open
    androidx.compose.runtime.DisposableEffect(menuOpen) {
        if (menuOpen) {
            val closer: () -> Unit = {
                if (!focus.moveFocus(FocusDirection.Right)) focus.clearFocus()
                drawerState.setValue(DrawerValue.Closed)
                // se o foco ainda ficou dentro do menu (ele reabriria), solta o foco de vez
                backScope.launch {
                    delay(120)
                    if (drawerState.currentValue == DrawerValue.Open) { focus.clearFocus(true); drawerState.setValue(DrawerValue.Closed) }
                }
            }
            TvDrawerBack.close = closer
            onDispose { if (TvDrawerBack.close === closer) TvDrawerBack.close = null }
        } else onDispose { }
    }
    if (menuOpen) BackHandler {  // reserva (caso a tecla chegue só pelo dispatcher)
        TvDrawerBack.close?.invoke()
    }
    // 57.27: o menu só pode receber foco depois de o usuário apertar ESQUERDA no conteúdo. Antes, qualquer perda de foco (trocar de tela, voltar do player, carregar)
    // fazia o foco cair no 1º item focável — o menu — e ele abria e fechava sozinho. `armed` é lido na hora da busca de foco (não precisa recompor).
    var armed by remember { mutableStateOf(false) }
    LaunchedEffect(drawerState.currentValue, userMenu) {
        if (drawerState.currentValue == DrawerValue.Closed && !userMenu) {
            delay(400)
            if (drawerState.currentValue == DrawerValue.Closed && !userMenu) armed = false
        }
    }
    ModalNavigationDrawer(
        drawerState = drawerState,
        modifier = Modifier.fillMaxSize(),
        scrimBrush = Brush.horizontalGradient(listOf(Color(0x99000000), Color.Transparent)),
        drawerContent = { drawer ->
            val open = drawer == DrawerValue.Open
            // ao abrir, o foco vai para o item da tela atual (Início, Pesquisar, Minhas Listas ou a biblioteca aberta), não para o primeiro
            val selReq = remember { FocusRequester() }
            LaunchedEffect(open) { if (open) { delay(80); runCatching { selReq.requestFocus() } } }
            val colors = SelectableSurfaceDefaults.colors(
                containerColor = Color.Transparent, contentColor = DRAWER_MUTED,
                focusedContainerColor = Color.White, focusedContentColor = Color.Black,
                pressedContainerColor = Color.White, pressedContentColor = Color.Black,
                selectedContainerColor = Color(0x33FFFFFF), selectedContentColor = DRAWER_TEXT,
                focusedSelectedContainerColor = Color.White, focusedSelectedContentColor = Color.Black,
                pressedSelectedContainerColor = Color.White, pressedSelectedContentColor = Color.Black,
            )
            // fechada: só os ícones soltos, sem fundo, por cima do conteúdo; aberta: painel arredondado por cima (o conteúdo não se mexe)
            val box = if (open) {
                Modifier.width(210.dp).clip(RoundedCornerShape(16.dp)).background(DRAWER_BG).padding(horizontal = 8.dp, vertical = 16.dp)
            } else Modifier.clip(RoundedCornerShape(28.dp)).background(PILL_BG).padding(horizontal = 6.dp, vertical = 10.dp)
            val ihDialog = Modifier.height(if (open) 50.dp else 38.dp)  // aberto: itens altos como o original (fonte 13sp); recolhido: compacto
            val ih = Modifier.focusProperties { canFocus = armed }.then(ihDialog)  // itens do menu: focáveis só depois de ESQUERDA (57.27)
            val scale by animateFloatAsState(if (open) 1f else 0.6f, label = "pill")  // recolhida: pílula compacta, só ícones pequenos
            if (userMenu) {
                val firstReq = remember { FocusRequester() }
                LaunchedEffect(Unit) { delay(80); runCatching { firstReq.requestFocus() } }
                androidx.compose.ui.window.Dialog(
                    onDismissRequest = { userMenu = false },
                    properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false),
                ) {
                    Box(Modifier.fillMaxSize().padding(start = if (open) 226.dp else 70.dp), contentAlignment = Alignment.CenterStart) {
                        Column(Modifier.width(280.dp).clip(RoundedCornerShape(12.dp)).background(DRAWER_BG).padding(bottom = 8.dp)) {
                            // cabeçalho como o do popup da web: foto grande e nome
                            Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 18.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                ProfileDot(server, profileName, profileColor, profilePhoto, size = 72.dp)
                                Spacer(Modifier.height(10.dp))
                                Text(profileName, color = DRAWER_TEXT, fontSize = 16.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                            }
                            Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0x40FFFFFF)))
                            Column(Modifier.padding(horizontal = 8.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                DrawerRow(true, false, { userMenu = false; onSwitchProfile() }, ihDialog.focusRequester(firstReq), colors, { DrawerIcon("user") }, Txt.s(R.string.tv_switch_user))
                                DrawerRow(true, false, { userMenu = false; onDisconnect() }, ihDialog, colors, { DrawerIcon("exit") }, Txt.s(R.string.tv_disconnect))
                            }
                        }
                    }
                }
            }
            // 43.1 (revisão): a barra fica sobreposta (Modal) e centralizada na vertical; recolhida é uma pílula arredondada só com os 4 ícones
            Box(Modifier.fillMaxHeight().padding(start = 8.dp), contentAlignment = Alignment.CenterStart) {
            Column(
                Modifier.graphicsLayer { scaleX = scale; scaleY = scale; transformOrigin = TransformOrigin(0f, 0.5f) }.then(box)
                    // 57.20: com o menu aberto, Voltar só o fecha (tira o foco do menu para o conteúdo); com ele fechado, vale o Voltar da tela
                    .onPreviewKeyEvent { ev ->
                        if (open && (ev.key == Key.Back || ev.key == Key.Escape)) {
                            if (ev.type == KeyEventType.KeyUp && !focus.moveFocus(FocusDirection.Right)) focus.clearFocus()
                            true
                        } else false
                    },
                verticalArrangement = Arrangement.spacedBy(if (open) 8.dp else 6.dp),
            ) {
                DrawerRow(open, false, { userMenu = true }, ih, colors, { ProfileDot(server, profileName, profileColor, profilePhoto) }, profileName)
                if (open) DrawerRow(open, selected == "mylist", { onNavigate("mylist") }, ih.then(if (selected == "mylist") Modifier.focusRequester(selReq) else Modifier), colors, { DrawerIcon("list") }, Txt.s(R.string.tv_my_lists))
                DrawerRow(open, selected == "search", { onNavigate("search") }, ih.then(if (selected == "search") Modifier.focusRequester(selReq) else Modifier), colors, { DrawerIcon("search") }, Txt.s(R.string.tv_search))
                DrawerRow(open, selected == "home", { onNavigate("home") }, ih.then(if (selected == "home") Modifier.focusRequester(selReq) else Modifier), colors, { DrawerIcon("home") }, Txt.s(R.string.tv_home))
                if (open) {
                    Row(Modifier.fillMaxWidth().padding(start = 14.dp, end = 14.dp, top = 10.dp, bottom = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(Txt.s(R.string.tv_media_libraries), color = DRAWER_MUTED, fontSize = 9.sp, maxLines = 1)
                        Spacer(Modifier.width(8.dp))
                        Box(Modifier.weight(1f).height(1.dp).background(Color(0x40FFFFFF)))
                    }
                    libs.forEach { l ->
                        DrawerRow(open, selected == "library:${l.id}", { onNavigate("library:${l.id}:${l.name}") },
                            ih.then(if (selected == "library:${l.id}") Modifier.focusRequester(selReq) else Modifier), colors,
                            { DrawerIcon(if (l.type == "show") "show" else "movie") }, l.name)
                    }
                }
            }
            }
        },
    ) {
        Box(
            Modifier.fillMaxSize().onPreviewKeyEvent { ev ->
                // ESQUERDA arma o menu (antes da busca de foco que o próprio Compose faz depois); qualquer outra tecla desarma
                if (ev.type == KeyEventType.KeyDown) armed = ev.key == Key.DirectionLeft
                false
            },
        ) { content() }
    }
}
