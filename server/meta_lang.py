"""59.37: o idioma dos agentes (TMDB, TVDB, SubDL) é o idioma escolhido pelo usuário nas configurações pessoais (sem opção por agente).
Trocar de idioma (com login) grava o novo idioma dos agentes e faz uma nova varredura de metadados (capa, sinopse, título, gênero,
elenco, temporadas, episódios) em todos os itens de todas as bibliotecas de filmes e séries. Campos travados ficam como estão."""
import logging

import config
from server.db import get_db

log = logging.getLogger(__name__)

# idioma da interface -> (TMDB, TVDB, SubDL)
MAP = {
    "pt-BR": ("pt-BR", "por", "BR_PT"), "en-US": ("en-US", "eng", "EN"), "es-ES": ("es-ES", "spa", "ES"),
    "ru-RU": ("ru-RU", "rus", "RU"), "fr-FR": ("fr-FR", "fra", "FR"), "de-DE": ("de-DE", "deu", "DE"),
    "it-IT": ("it-IT", "ita", "IT"), "ja-JP": ("ja-JP", "jpn", "JA"), "zh-CN": ("zh-CN", "zho", "ZH"),
    "tr-TR": ("tr-TR", "tur", "TR"),
}
DEFAULT = "pt-BR"
KEY = "meta_lang"  # settings: idioma da interface a que os agentes estão ajustados


def region_of(lang):
    """pt-BR -> BR (a região das listas do TMDB acompanha o idioma)."""
    return lang.split("-")[1] if "-" in lang else lang.upper()


def _set(conn, key, value):
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def _get(conn, key):
    r = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return (r["value"] or "").strip() if r else ""


def _apply(lang):
    tmdb, tvdb, subdl = MAP[lang]
    config.TMDB_LANG, config.TMDB_REGION, config.TVDB_LANG, config.SUBDL_LANG = tmdb, region_of(tmdb), tvdb, subdl


def current():
    return next((k for k, v in MAP.items() if v[0] == config.TMDB_LANG), DEFAULT)


def load(conn):
    """Na partida: banco -> config. Sem valor salvo usa o idioma do TMDB que o admin tinha escolhido antes, depois o padrão do servidor."""
    lang = _get(conn, KEY)
    if lang not in MAP:
        lang = _get(conn, "lang_tmdb")
    if lang not in MAP:
        lang = _get(conn, "default_lang")
    lang = lang if lang in MAP else DEFAULT
    _apply(lang)
    if not _get(conn, "data_lang"):  # 59.41: idioma em que os dados já gravados estão
        _set(conn, "data_lang", lang)


def follow(lang):
    """O usuário trocou o idioma: ajusta os agentes e refaz os metadados de todas as bibliotecas. True se houve mudança."""
    if lang not in MAP:
        return False
    with get_db() as conn:
        same = lang == current()
        _set(conn, KEY, lang)
        conn.commit()
    if same:  # os metadados já estão neste idioma: nada a refazer
        return False
    _apply(lang)
    try:
        from server.tmdb_lists import ensure_fresh
        ensure_fresh()  # listas do TMDB do Início (por idioma/região) em segundo plano
    except Exception:
        log.exception("falha ao atualizar as listas do TMDB no novo idioma")
    from server.scanner import refresh_language_async
    refresh_language_async()
    return True
