"""32.2: listas do TMDB (em cartaz, populares, em alta…) guardadas em `tmdb_lists` e cruzadas com o acervo por tmdb_id."""
import json
import threading
import time

import requests

import config
from server.db import get_db

TTL = 24 * 3600
PAGES = 2

# key -> (tipo de item no servidor, caminho no TMDB, aceita region)
LISTS = {
    "movie_now_playing": ("movie", "/movie/now_playing", True),
    "movie_popular": ("movie", "/movie/popular", True),
    "movie_top_rated": ("movie", "/movie/top_rated", True),
    "movie_upcoming": ("movie", "/movie/upcoming", True),
    "tv_airing_today": ("show", "/tv/airing_today", False),
    "tv_on_the_air": ("show", "/tv/on_the_air", False),
    "tv_popular": ("show", "/tv/popular", False),
    "tv_top_rated": ("show", "/tv/top_rated", False),
    "trending_movie": ("movie", "/trending/movie/week", False),
    "trending_tv": ("show", "/trending/tv/week", False),
}

_lock = threading.Lock()
_bg = {"running": False}


def refresh_list(key):
    """Baixa as 2 primeiras páginas da lista e grava em tmdb_lists; False se falhar (mantém o cache anterior)."""
    from server.metadata import tmdb_get  # import tardio: metadata importa db
    _, path, use_region = LISTS[key]
    region, lang = config.TMDB_REGION, config.TMDB_LANG
    ids = []
    try:
        for page in range(1, PAGES + 1):
            params = {"page": page, "language": lang}
            if use_region and region:
                params["region"] = region
            for it in tmdb_get(path, **params).get("results", []):
                if isinstance(it.get("id"), int) and it["id"] not in ids:
                    ids.append(it["id"])
    except (requests.RequestException, ValueError, AttributeError):
        return False
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO tmdb_lists (list_key, region, lang, ids, fetched_at) VALUES (?, ?, ?, ?, ?)",
            (key, region, lang, json.dumps(ids), int(time.time())),
        )
    return True


def refresh_stale(force=False):
    """Renova as listas ausentes ou com mais de 24 h (região/idioma diferentes do atual contam como ausentes)."""
    if not config.TMDB_API_KEY or not _lock.acquire(blocking=False):
        return 0
    done = 0
    try:
        with get_db() as conn:
            have = {r["list_key"]: r["fetched_at"] for r in conn.execute(
                "SELECT list_key, fetched_at FROM tmdb_lists WHERE region = ? AND lang = ?", (config.TMDB_REGION, config.TMDB_LANG))}
        now = time.time()
        for key in LISTS:
            if force or now - have.get(key, 0) > TTL:
                if refresh_list(key):
                    done += 1
    finally:
        _lock.release()
    return done


def ensure_fresh():
    """1º acesso sem cache: renova em segundo plano e devolve na hora (o Início não espera)."""
    if not config.TMDB_API_KEY or _bg["running"]:
        return
    with get_db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM tmdb_lists WHERE region = ? AND lang = ?", (config.TMDB_REGION, config.TMDB_LANG)).fetchone()[0]
    if n >= len(LISTS):
        return
    _bg["running"] = True

    def run():
        try:
            refresh_stale()
        finally:
            _bg["running"] = False

    threading.Thread(target=run, daemon=True).start()


def list_ids(conn, key):
    """tmdb_ids da lista, na ordem do TMDB ([] se ainda não houver cache)."""
    r = conn.execute("SELECT ids FROM tmdb_lists WHERE list_key = ? AND region = ? AND lang = ?",
                     (key, config.TMDB_REGION, config.TMDB_LANG)).fetchone()
    try:
        return json.loads(r["ids"]) if r else []
    except ValueError:
        return []


def matches(conn, user_id, key, limit=None):
    """ids de `media` presentes na lista, na ordem do TMDB: filme só em biblioteca de filmes, série só em biblioteca
    de séries, sempre só em bibliotecas liberadas ao usuário."""
    from server.libraries import visible_libraries
    if key not in LISTS:
        return []
    kind = LISTS[key][0]
    libs = [l["id"] for l in visible_libraries(user_id) if l["type"] == kind]
    ids = list_ids(conn, key)
    if not libs or not ids:
        return []
    ql = ",".join("?" * len(libs))
    qi = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, tmdb_id FROM media WHERE library_id IN ({ql}) AND tmdb_id IN ({qi})", (*libs, *ids)).fetchall()
    pos = {t: i for i, t in enumerate(ids)}
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: (pos[r["tmdb_id"]], r["id"])):
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r["id"])
    return out[:limit] if limit else out
