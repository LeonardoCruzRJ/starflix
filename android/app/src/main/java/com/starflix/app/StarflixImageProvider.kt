package com.starflix.app

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import java.io.File
import java.io.FileNotFoundException

/**
 * 52.16: entrega ao launcher da TV as imagens da linha "Reproduzir a seguir" (o launcher não tem o Bearer do servidor).
 * Exportado, só leitura e só arquivos de `cacheDir/watchnext/` (baixados pelo [TvWatchNext]); `content://com.starflix.app.watchnext/<nome>.jpg`.
 * Não lista nada (`query` devolve null) e recusa `..`, subpastas, `%2f`, links simbólicos e qualquer nome fora de `[A-Za-z0-9_]+.jpg`.
 */
class StarflixImageProvider : ContentProvider() {
    override fun onCreate(): Boolean = true

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        if (mode != "r") throw FileNotFoundException("somente leitura")
        val ctx = context ?: throw FileNotFoundException()
        val segs = uri.pathSegments
        val name = segs.singleOrNull() ?: throw FileNotFoundException()  // sem subpastas nem caminho vazio
        if (!NAME.matches(name)) throw FileNotFoundException()           // barra de `..`, `%2f`, `.tmp` e outros nomes
        val dir = File(ctx.cacheDir, TvWatchNext.DIR).canonicalFile
        val file = File(dir, name).canonicalFile
        if (file.parentFile != dir || !file.isFile) throw FileNotFoundException()  // symlink que aponta para fora também cai aqui
        return ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
    }

    override fun getType(uri: Uri): String? = if (uri.pathSegments.size == 1 && NAME.matches(uri.pathSegments[0])) "image/jpeg" else null

    override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor? = null
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = 0
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0

    private companion object {
        val NAME = Regex("[A-Za-z0-9_]+\\.jpg")
    }
}
