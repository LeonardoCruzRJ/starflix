package com.starflix.app

import android.content.Context
import android.webkit.CookieManager
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.os.LocaleListCompat
import java.util.Locale

/** 59.29: idioma do app. Os códigos são os do catálogo do servidor (`i18n/*.json`, `locales_config.xml`). Sem escolha, vale o idioma do sistema. */
object AppLang {
    val LANGS = listOf(
        "pt-BR" to "Português (Brasil)", "en-US" to "English", "es-ES" to "Español", "ru-RU" to "Русский", "fr-FR" to "Français",
        "de-DE" to "Deutsch", "it-IT" to "Italiano", "ja-JP" to "日本語", "zh-CN" to "简体中文", "tr-TR" to "Türkçe",
    )

    /** Código do catálogo em uso (o idioma-base casa com o primeiro da lista; fora da lista cai em pt-BR). */
    fun current(): String {
        val l = AppCompatDelegate.getApplicationLocales().get(0) ?: Locale.getDefault()
        return LANGS.firstOrNull { it.first.equals(l.toLanguageTag(), true) }?.first
            ?: LANGS.firstOrNull { it.first.substringBefore('-').equals(l.language, true) }?.first ?: "pt-BR"
    }

    fun nameOf(code: String) = LANGS.firstOrNull { it.first == code }?.second ?: code

    /** Troca o idioma do app; as telas abertas se recriam sozinhas (as que declaram `locale` em configChanges recebem só o aviso). */
    fun set(code: String) {
        if (LANGS.none { it.first == code } || code == current()) return
        AppCompatDelegate.setApplicationLocales(LocaleListCompat.forLanguageTags(code))
    }

    /** Cookie `sf_lang` do site na origem do servidor (o site o lê antes de Accept-Language). */
    fun syncCookie(base: String) {
        val cm = CookieManager.getInstance()
        cm.setCookie(base, "sf_lang=" + current() + "; Max-Age=31536000; Path=/; SameSite=Lax")
        cm.flush()
    }

    fun headers(): Map<String, String> = mapOf("Accept-Language" to current() + "," + current().substringBefore('-') + ";q=0.9")
}
