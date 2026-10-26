package com.starflix.app

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.compose.runtime.LaunchedEffect
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.setValue
import androidx.tv.material3.MaterialTheme
import coil.Coil

/**
 * Interface da TV (Android TV, controle remoto). Aberta pela MainActivity quando o aparelho é uma TV (UiModeManager); não usa WebView.
 * Fluxo: servidor (URL) → pareamento (QR + código) → escolha de perfil → Início nativo (HomeScreen, 40.10).
 * O token fica em TvStore (criptografado); token revogado (401) em qualquer chamada chama [unauthorized] e volta ao pareamento.
 */
class TvActivity : ComponentActivity() {
    /** 57.30: Voltar com o menu lateral aberto só o fecha (em qualquer tela); a tecla nem chega ao conteúdo. */
    override fun dispatchKeyEvent(event: android.view.KeyEvent): Boolean {
        if (event.keyCode == android.view.KeyEvent.KEYCODE_BACK) {
            val c = TvDrawerBack.close
            if (c != null) {
                if (event.action == android.view.KeyEvent.ACTION_UP) c()
                return true
            }
        }
        return super.dispatchKeyEvent(event)
    }

    private enum class Screen { PAIR, PROFILE, HOME, LIBRARY, DETAIL, SEARCH, MYLIST }

    /** 52.16: link `starflix://item?type=movie|episode&id=…&play=1` (linha "Reproduzir a seguir"); fica pendente até a TV estar pareada, com perfil e numa tela de navegação. */
    private data class DeepLink(val type: String, val id: Long, val play: Boolean)

    private var pendingLink by mutableStateOf<DeepLink?>(null)

    private fun parseLink(i: Intent?): DeepLink? {
        val u = i?.data ?: return null
        if (i.action != Intent.ACTION_VIEW || u.scheme != "starflix" || u.host != "item") return null
        val type = u.getQueryParameter("type")?.takeIf { it == "movie" || it == "episode" } ?: return null
        val id = u.getQueryParameter("id")?.toLongOrNull()?.takeIf { it > 0 } ?: return null
        return DeepLink(type, id, u.getQueryParameter("play") == "1")
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        parseLink(intent)?.let { pendingLink = it }
    }

    private lateinit var store: TvStore
    private var playTick by mutableStateOf(0)   // sobe ao voltar do player: Início e detalhes recarregam (progresso, assistido)

    private var fromPlayer = false   // 52.17: voltou do player; o próximo onResume espera um pouco (o player grava a posição em segundo plano)

    private val playerLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        if (r.resultCode == PlayerActivity.RESULT_UNAUTHORIZED) { TvWatchNext.clearAsync(this, store); store.clearLogin(); recreate() }
        else { fromPlayer = true; playTick++ }
    }

    /** 52.17: ao abrir o app e ao voltar do player, atualiza a linha "Reproduzir a seguir" (assistido sai, próximo episódio entra). */
    override fun onResume() {
        super.onResume()
        TvWatchNext.refresh(this, store, if (fromPlayer) 1500L else 0L)
        fromPlayer = false
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = TvStore(this)
        if (store.server.isBlank()) {  // 58.14/58.15: sem servidor salvo, procura na rede; achou = guarda e recomeça no pareamento; não achou = Conectar pelo celular
            setContent {
                MaterialTheme {
                    var bridge by remember { mutableStateOf(false) }
                    if (!bridge) DiscoverScreen(
                        onChosen = { info, url ->
                            ServerStore(this).save(info, url)
                            store.clearLogin()
                            store.server = url
                            recreate()
                        },
                        onNone = { bridge = true },  // 58.15: não achou na rede → Conectar pelo celular
                    ) else TvBridgeScreen(
                        onPaired = { info, url, token ->  // um scan só: servidor + token, a TV vai direto aos perfis
                            ServerStore(this).save(info, url)
                            store.clearLogin()
                            store.server = url
                            store.token = token
                            recreate()
                        },
                        onAddress = {  // 58.17: último recurso, endereço digitado → /api/server-info → PairScreen
                            startActivity(Intent(this, ConnectActivity::class.java))
                            finish()
                        },
                        onBack = { finish() },
                    )
                }
            }
            return
        }
        pendingLink = parseLink(intent)
        Coil.setImageLoader(tvImageLoader(this, store))  // toda imagem leva Authorization + X-Profile
        setContent {
            MaterialTheme {
                var splash by rememberSaveable { mutableStateOf(true) }   // pré-loading só ao abrir o app
                if (splash) { SplashScreen { splash = false }; return@MaterialTheme }
                var screen by remember { mutableStateOf(start()) }
                var homeFocus by remember { mutableStateOf<String?>(null) }   // último card focado no Início (Voltar restaura)
                var libId by remember { mutableStateOf(0L) }
                var libName by remember { mutableStateOf("") }
                var libFocus by remember { mutableStateOf<String?>(null) }
                var libs by remember { mutableStateOf<List<TvLib>>(emptyList()) }   // bibliotecas do menu lateral (vêm do Início)
                // biblioteca nova (ou fixada/desafixada) entra no menu sozinha: relê a lista a cada troca de tela e ao voltar do player
                LaunchedEffect(screen, playTick, store.profileId) {
                    if (store.token.isNotEmpty() && store.profileId != 0L) {
                        val fresh = withContext(Dispatchers.IO) { TvHomeApi.libraries(store.server, store.token, store.profileId) }
                        if (fresh != null && fresh != libs) libs = fresh
                    }
                }
                var searchQuery by remember { mutableStateOf("") }
                val stack = remember { mutableStateListOf<Target>() }          // pilha de detalhes (filme → série → temporada → episódio…)
                var origin by remember { mutableStateOf(Screen.HOME) }          // tela de onde o 1º detalhe foi aberto
                fun open(from: Screen, c: TvCard) {
                    val t = c.target()
                    if (t == null) { play(c.play, c.title, 0); return }
                    if (stack.isEmpty()) origin = from
                    stack.add(t); screen = Screen.DETAIL
                }
                // 52.16: link da linha da TV: abre o detalhe ou já continua a reprodução; sem pareamento/perfil espera (o fluxo normal segue e volta aqui)
                LaunchedEffect(pendingLink, screen) {
                    val l = pendingLink ?: return@LaunchedEffect
                    val ready = store.token.isNotBlank() && store.profileId > 0L &&
                        (screen == Screen.HOME || screen == Screen.LIBRARY || screen == Screen.DETAIL || screen == Screen.SEARCH || screen == Screen.MYLIST)
                    if (!ready) return@LaunchedEffect
                    pendingLink = null
                    if (l.play) play("/stream/${l.type}/${l.id}/play", "", 0)
                    else { stack.clear(); origin = Screen.HOME; stack.add(Target(l.type, l.id)); screen = Screen.DETAIL }
                }
                // 401: token revogado → pareamento; 403: perfil apagado → escolha de perfil (o token segue valendo)
                fun unauthorized() {
                    TvWatchNext.clearAsync(this@TvActivity, store)   // 52.17: nada do perfil/aparelho antigo fica no launcher
                    stack.clear(); homeFocus = null; libFocus = null
                    if (TvApi.badProfile) { TvApi.badProfile = false; store.profileId = 0L; screen = Screen.PROFILE }
                    else { store.clearLogin(); screen = Screen.PAIR }
                }
                // "Desconectar esta TV": avisa o servidor (some de /tv) e apaga o token daqui
                fun disconnect() {
                    val s = store.server
                    val t = store.token
                    Thread { TvApi.logout(s, t) }.start()
                    TvWatchNext.clearAsync(this@TvActivity, store)   // 52.17
                    stack.clear(); homeFocus = null; libFocus = null
                    store.clearLogin(); screen = Screen.PAIR
                }
                // 52.17: trocar de perfil limpa a linha; ao escolher o novo, `onPicked` republica só os dele
                fun switchProfile() { TvWatchNext.clearAsync(this@TvActivity, store); store.profileId = 0L; homeFocus = null; libFocus = null; stack.clear(); screen = Screen.PROFILE }
                fun navigate(dest: String) {
                    val p = dest.split(":", limit = 3)
                    stack.clear()
                    if (dest == "home") { screen = Screen.HOME }
                    else if (p[0] == "library" && p.size == 3) { libId = p[1].toLong(); libName = p[2]; libFocus = null; screen = Screen.LIBRARY }
                    else if (dest == "search") screen = Screen.SEARCH
                    else if (dest == "mylist") screen = Screen.MYLIST
                }
                // pílula lateral em todas as telas de navegação (Busca, Minha Lista e detalhes), sobreposta ao conteúdo
                @Composable
                fun withDrawer(selected: String, content: @Composable () -> Unit) {
                    TvDrawer(
                        libs = libs, selected = selected, server = store.server, profileName = store.profileName, profileColor = store.profileColor, profilePhoto = store.profilePhoto,
                        onNavigate = { dest -> if (dest != selected) navigate(dest) }, onSwitchProfile = { switchProfile() }, onDisconnect = { disconnect() },
                        content = content,
                    )
                }
            when (screen) {
                Screen.PAIR -> PairScreen(
                    server = store.server,
                    onPaired = { token -> store.token = token; store.profileId = 0L; screen = Screen.PROFILE },
                )
                Screen.PROFILE -> ProfileScreen(
                    server = store.server,
                    token = store.token,
                    onPicked = { p -> store.profileId = p.id; store.profileName = p.name; store.profileColor = p.color; store.profilePhoto = p.photo; screen = Screen.HOME; TvWatchNext.refresh(this@TvActivity, store) },
                    onUnauthorized = { unauthorized() },
                    onExit = { finish() },
                )
                Screen.HOME -> HomeScreen(
                    server = store.server,
                    token = store.token,
                    profileId = store.profileId,
                    profileName = store.profileName, profileColor = store.profileColor, profilePhoto = store.profilePhoto,
                    onOpen = { c -> open(Screen.HOME, c) },
                    onExit = { finish() },
                    refresh = playTick,
                    onNavigate = { dest -> navigate(dest) },
                    onLibs = { libs = it },
                    onSwitchProfile = { switchProfile() },
                    restoreKey = homeFocus,
                    onFocusKey = { homeFocus = it },
                    onDisconnect = { disconnect() },
                    onUnauthorized = { unauthorized() },
                )
                Screen.LIBRARY -> key(libId) { LibraryScreen(
                    libs = libs, profileName = store.profileName, profileColor = store.profileColor, profilePhoto = store.profilePhoto,
                    onNavigate = { dest -> navigate(dest) },
                    onSwitchProfile = { switchProfile() },
                    onDisconnect = { disconnect() },
                    server = store.server, token = store.token, profileId = store.profileId, libId = libId, libName = libName,
                    onOpen = { c -> open(Screen.LIBRARY, c) }, onBack = { screen = Screen.HOME }, onUnauthorized = { unauthorized() },
                    restoreKey = libFocus, onFocusKey = { libFocus = it },
                ) }
                Screen.SEARCH -> withDrawer("search") { SearchScreen(
                    server = store.server, token = store.token, profileId = store.profileId, initialQuery = searchQuery,
                    onQuery = { searchQuery = it }, onOpen = { c -> open(Screen.SEARCH, c) },
                    onBack = { screen = Screen.HOME }, onUnauthorized = { unauthorized() },
                ) }
                Screen.MYLIST -> withDrawer("mylist") { MyListScreen(
                    server = store.server, token = store.token, profileId = store.profileId,
                    onOpen = { c -> open(Screen.MYLIST, c) }, onBack = { screen = Screen.HOME }, onUnauthorized = { unauthorized() },
                ) }
                Screen.DETAIL -> withDrawer(run {
                    // filme → biblioteca de filmes; série, temporada ou episódio → biblioteca de séries (prefere a biblioteca de onde se veio)
                    val want = when (stack.lastOrNull()?.kind) { "movie" -> "movie"; "show", "season", "episode" -> "show"; else -> "" }
                    val lib = if (want.isEmpty()) null else (libs.firstOrNull { it.type == want && origin == Screen.LIBRARY && it.id == libId } ?: libs.firstOrNull { it.type == want })
                    if (lib != null) "library:${lib.id}" else ""
                }) { DetailScreen(
                    server = store.server, token = store.token, profileId = store.profileId, target = stack.last(), refresh = playTick,
                    onOpen = { c -> open(Screen.DETAIL, c) },
                    onPlay = { path, title, pos -> play(path, title, pos) },
                    onBack = { stack.removeAt(stack.lastIndex); if (stack.isEmpty()) screen = origin },
                    onUnauthorized = { stack.clear(); unauthorized() },
                ) }
            }
            
            }
        }
    }

    /** Abre o PlayerActivity no modo TV (Bearer + X-Profile); ele retoma da posição salva e segue para o próximo episódio. */
    private fun play(path: String?, title: String, position: Int) {
        val m = Regex("/stream/(movie|episode)/(\\d+)/play").find(path.orEmpty())
        if (m == null) { Toast.makeText(this, "\"$title\" não tem vídeo para reproduzir.", Toast.LENGTH_SHORT).show(); return }
        playerLauncher.launch(
            Intent(this, PlayerActivity::class.java)
                .putExtra(PlayerActivity.EXTRA_KIND, m.groupValues[1])
                .putExtra(PlayerActivity.EXTRA_ID, m.groupValues[2].toInt())
                .putExtra(PlayerActivity.EXTRA_TV, true)
                .putExtra(PlayerActivity.EXTRA_SERVER, store.server)
                .putExtra(PlayerActivity.EXTRA_TOKEN, store.token)
                .putExtra(PlayerActivity.EXTRA_PROFILE, store.profileId)
                .apply { if (position < 0) putExtra(PlayerActivity.EXTRA_START, 0) },  // -1 = "Do início": ignora a posição salva
        )
    }

    private fun start() = when {
        store.token.isBlank() -> Screen.PAIR
        store.profileId <= 0L -> Screen.PROFILE
        else -> Screen.HOME
    }
}
