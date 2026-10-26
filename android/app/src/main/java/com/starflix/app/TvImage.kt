package com.starflix.app

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import coil.ImageLoader
import coil.compose.AsyncImage
import coil.request.ImageRequest
import kotlinx.coroutines.delay
import okhttp3.Interceptor
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit

/** 45.4: tenta de novo na rede (falha de conexão, timeout, 408/429/5xx) até 3 vezes; 404 e demais 4xx não repetem (imagem que não existe). */
private fun retrying(chain: Interceptor.Chain): Response {
    for (attempt in 0..2) {
        try {
            val r = chain.proceed(chain.request())
            val transient = r.code == 408 || r.code == 429 || r.code >= 500
            if (!transient || attempt == 2) return r
            r.close()
        } catch (e: IOException) {
            if (attempt == 2) throw e
        }
        Thread.sleep(600L * (attempt + 1))
    }
    throw IOException("sem resposta")
}

/** Coil com `Authorization: Bearer` e `X-Profile` em toda imagem (poster, backdrop, still, avatar...), lendo o TvStore a cada pedido. */
fun tvImageLoader(context: Context, store: TvStore): ImageLoader {
    val auth = Interceptor { chain ->
        val b = chain.request().newBuilder()
        if (store.token.isNotBlank()) b.header("Authorization", "Bearer ${store.token}")
        if (store.profileId > 0) b.header("X-Profile", store.profileId.toString())
        chain.proceed(b.build())
    }
    val client = okhttp3.OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS)  // o servidor pode gerar a imagem na hora (o padrão de 10s estourava com muitas capas juntas)
        .addInterceptor(Interceptor { retrying(it) })
        .addInterceptor(auth).build()
    return ImageLoader.Builder(context.applicationContext).okHttpClient(client).crossfade(true).build()
}

/**
 * 45.4: AsyncImage que busca de novo a imagem que não carregou (capa, logo, fundo): até 4 novas tentativas com espera crescente.
 * Erro 4xx (imagem inexistente) não repete. Ao abrir qualquer tela as imagens ainda não carregadas são pedidas outra vez, pois a composição é nova.
 */
@Composable
fun RetryAsyncImage(
    model: String, contentDescription: String?, modifier: Modifier = Modifier,
    alignment: Alignment = Alignment.Center, contentScale: ContentScale = ContentScale.Fit,
) {
    val ctx = LocalContext.current
    var attempt by remember(model) { mutableStateOf(0) }
    var failed by remember(model) { mutableStateOf(false) }
    LaunchedEffect(model, failed) {
        if (failed && attempt < 4) {
            delay(1500L * (attempt + 1))
            attempt++
            failed = false
        }
    }
    val request = remember(model, attempt) {
        ImageRequest.Builder(ctx).data(model).setParameter("retry", attempt, memoryCacheKey = null).build()  // parâmetro novo = pedido novo, sem mudar a chave do cache
    }
    AsyncImage(
        model = request, contentDescription = contentDescription, modifier = modifier, alignment = alignment, contentScale = contentScale,
        onSuccess = { failed = false },
        onError = { e -> val t = e.result.throwable; if (!(t is coil.network.HttpException && t.response.code in 400..499)) failed = true },
    )
}
