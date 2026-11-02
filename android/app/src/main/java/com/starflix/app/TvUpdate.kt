package com.starflix.app

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.Spacer
import androidx.tv.material3.Button
import androidx.tv.material3.ExperimentalTvMaterial3Api
import androidx.tv.material3.Text
import kotlinx.coroutines.delay

/**
 * 63.7: modal bloqueante de atualização da TV (mesmo fluxo do celular, 63.6). Janela própria: Voltar e clique fora não fecham, o foco fica
 * no botão **Atualizar** (D-pad/OK). Mostra versão instalada → nova, progresso, ajuste "Instalar apps desconhecidos" (retoma em `resumeTick`)
 * e **Tentar de novo**. Some quando a versão pendente é limpa (instalada ou servidor sem APK).
 */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun TvUpdateDialog(release: AppRelease, base: String, resumeTick: Int) {
    val ctx = LocalContext.current
    var st by remember { mutableStateOf<UpdateState?>(null) }
    val gold = Color(0xFFE5A00D)
    fun begin() {
        st = UpdateState.Downloading(-1)
        AppInstaller.start(ctx, base, release) { st = it }
    }
    LaunchedEffect(resumeTick) {  // voltou dos ajustes com a permissão liberada
        if (st == UpdateState.NeedPermission && AppInstaller.canInstall(ctx)) begin()
    }
    val s = st
    val showBtn = s == null || s == UpdateState.NeedPermission || s is UpdateState.Failed
    val req = remember { FocusRequester() }
    LaunchedEffect(showBtn) {
        if (showBtn) {
            delay(150)
            try { req.requestFocus() } catch (e: Exception) { }
        }
    }
    Dialog(onDismissRequest = { }, properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false, usePlatformDefaultWidth = false)) {
        Box(Modifier.fillMaxSize().background(Color(0xFF1F2326)), contentAlignment = Alignment.Center) {
            Column(Modifier.width(640.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Text(Txt.s(R.string.update_title), color = Color(0xFFEEEEEE), fontSize = 32.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center)
                Text(Txt.s(R.string.update_versions, AppUpdate.installedName(ctx), release.versionName), color = gold, fontSize = 22.sp)
                val msg = when (s) {
                    null -> Txt.s(R.string.update_body)
                    is UpdateState.Downloading -> if (s.percent < 0) Txt.s(R.string.update_downloading_unknown) else Txt.s(R.string.update_downloading, s.percent.toString())
                    UpdateState.NeedPermission -> Txt.s(R.string.update_permission)
                    UpdateState.Installing -> Txt.s(R.string.update_installing)
                    is UpdateState.Failed -> s.message
                }
                Text(msg, color = Color(0xFF9A9EA3), fontSize = 20.sp, textAlign = TextAlign.Center)
                if (s is UpdateState.Downloading && s.percent >= 0) {
                    Box(Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp)).background(Color(0xFF2F3236))) {
                        Box(Modifier.fillMaxWidth(s.percent / 100f).height(8.dp).background(gold))
                    }
                }
                Spacer(Modifier.height(8.dp))
                if (showBtn) {
                    val label = when (s) {
                        UpdateState.NeedPermission -> Txt.s(R.string.update_open_settings)
                        is UpdateState.Failed -> Txt.s(R.string.retry)
                        else -> Txt.s(R.string.update_btn)
                    }
                    Button(
                        onClick = {
                            if (s == UpdateState.NeedPermission) {
                                try { ctx.startActivity(AppInstaller.permissionIntent(ctx)) } catch (e: Exception) { st = UpdateState.Failed(Txt.s(R.string.update_err_install, "")) }
                            } else begin()
                        },
                        modifier = Modifier.focusRequester(req).padding(horizontal = 8.dp),
                    ) { Text(label, fontSize = 20.sp) }
                }
            }
        }
    }
}
