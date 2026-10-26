import contextlib
import functools
import json
import os
import re
import shutil
import threading

import requests

import config
from server import scanstate
from server.db import get_db, lib_prefs, library_folders

TMDB_API = "https://api.themoviedb.org/3"


# 28.4: opções da biblioteca em uso (idioma, país, adulto, agente), por thread; sem contexto valem as variáveis de ambiente
_ctx = threading.local()
TVDB_LANGS = {"pt": "por", "en": "eng", "es": "spa", "fr": "fra", "de": "deu", "it": "ita", "ja": "jpn", "ru": "rus", "zh": "zho", "tr": "tur"}


def _opts():
    return getattr(_ctx, "opts", None) or {}


def _lang():
    return _opts().get("lang") or config.TMDB_LANG


@contextlib.contextmanager
def library_context(library_id):
    with get_db() as conn:
        row = conn.execute("SELECT prefs FROM libraries WHERE id = ?", (library_id,)).fetchone()
    p = lib_prefs(row or {"prefs": None})
    prev = getattr(_ctx, "opts", None)
    # 59.37: o idioma dos metadados é o do usuário (config.TMDB_LANG / TVDB_LANG, ver server/meta_lang.py), não mais o da biblioteca
    _ctx.opts = {"lang": None, "tvdb_lang": None,
                 "cert_country": p["cert_country"], "adult": p["adult"], "agent": p["agent"], "lang_art": p["lang_art"], "local_art": p["local_art"]}
    try:
        yield
    finally:
        _ctx.opts = prev


def _in_library(skip_when_none=False):
    """Decorador para funções `f(library_id, ...)`: roda dentro do contexto da biblioteca; `skip_when_none` pula o exame
    da biblioteca inteira quando o agente é \"Nenhum\" (correspondência manual de um item, com media_id, continua)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(library_id, *a, **k):
            with library_context(library_id):
                media_id = a[0] if a else k.get("media_id")
                if skip_when_none and media_id is None and _opts().get("agent") == "none":
                    return 0
                return fn(library_id, *a, **k)
        return wrapper
    return deco


def tmdb_get(path, **params):
    """Chama a API do TMDB (aceita chave v3 ou token v4 'eyJ...')."""
    key = config.TMDB_API_KEY
    headers = {}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    else:
        params["api_key"] = key
    params.setdefault("language", _lang())
    if path.startswith("/search/"):
        params.setdefault("include_adult", "true" if _opts().get("adult") else "false")
    r = requests.get(TMDB_API + path, params=params, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()


def tmdb_details(kind, tmdb_id):
    """Detalhes de /movie/ID ou /tv/ID (com elenco/equipe e classificação); sinopse vazia cai para en-US."""
    extra = "credits,release_dates" if kind == "movie" else "credits,content_ratings"
    d = tmdb_get(f"/{kind}/{tmdb_id}", append_to_response=extra + ",external_ids,images,reviews,recommendations", include_image_language=f"{_lang()[:2]},en,null")
    if not (d.get("overview") or "").strip() and _lang() != "en-US":
        d["overview"] = tmdb_get(f"/{kind}/{tmdb_id}", language="en-US").get("overview")
    return d


def omdb_ratings(imdb_id):
    """(nota IMDb, Rotten Tomatoes %) via OMDb; (None, None) sem chave, sem id ou em qualquer falha."""
    if not config.OMDB_API_KEY or not imdb_id:
        return None, None
    try:
        r = requests.get("https://www.omdbapi.com/", params={"i": imdb_id, "apikey": config.OMDB_API_KEY}, timeout=15)
        r.raise_for_status()
        j = r.json()
    except (requests.RequestException, ValueError):
        return None, None
    if not isinstance(j, dict) or j.get("Response") == "False":
        return None, None
    try:
        imdb = float(j.get("imdbRating"))
    except (TypeError, ValueError):
        imdb = None
    rt = None
    for x in j.get("Ratings") or []:
        if isinstance(x, dict) and x.get("Source") == "Rotten Tomatoes":
            try:
                rt = int(str(x.get("Value", "")).rstrip("%"))
            except ValueError:
                pass
    return imdb, rt


def omdb_season(imdb_id, n):
    """{episódio: nota IMDb} de uma temporada via OMDb (um pedido por temporada); {} sem chave, sem id ou em falha (36.1)."""
    if not config.OMDB_API_KEY or not imdb_id:
        return {}
    try:
        r = requests.get("https://www.omdbapi.com/", params={"i": imdb_id, "Season": n, "apikey": config.OMDB_API_KEY}, timeout=15)
        r.raise_for_status()
        j = r.json()
    except (requests.RequestException, ValueError):
        return {}
    out = {}
    for x in (j.get("Episodes") or []) if isinstance(j, dict) else []:
        try:
            out[int(x.get("Episode"))] = float(x.get("imdbRating"))
        except (TypeError, ValueError):
            pass
    return out


def _genres(d):
    return ", ".join(g["name"] for g in d.get("genres", []))


def _locks(conn, media_id):
    """Campos travados do item (media.locks, JSON {"campo": 1}); travado nunca é sobrescrito."""
    r = conn.execute("SELECT locks FROM media WHERE id = ?", (media_id,)).fetchone()
    try:
        v = json.loads(r["locks"]) if r and r["locks"] else {}
    except ValueError:
        v = {}
    return v if isinstance(v, dict) else {}


def _certification(d, kind):
    """Classificação indicativa: país da biblioteca (padrão BR) e, se não houver, US."""
    countries = list(dict.fromkeys([_opts().get("cert_country") or "BR", "US"]))
    if kind == "movie":
        by = {x.get("iso_3166_1"): x for x in (d.get("release_dates") or {}).get("results") or []}
        for cc in countries:
            for rel in (by.get(cc) or {}).get("release_dates") or []:
                if (rel.get("certification") or "").strip():
                    return rel["certification"].strip()
    else:
        by = {x.get("iso_3166_1"): x for x in (d.get("content_ratings") or {}).get("results") or []}
        for cc in countries:
            if (by.get(cc) or {}).get("rating", "").strip():
                return by[cc]["rating"].strip()
    return None


def _credit_lists(d, kind):
    """{papel: [(tmdb_id, nome, foto, personagem)]} a partir do elenco e da equipe do TMDB."""
    cr = d.get("credits") or {}
    crew = cr.get("crew") or []

    def pick(rows, limit):
        seen, out = set(), []
        for c in rows:
            if c.get("id") is None or c["id"] in seen or not c.get("name"):
                continue
            seen.add(c["id"])
            out.append((c["id"], c["name"], c.get("profile_path"), None))
            if len(out) >= limit:
                break
        return out

    writers = [c for c in crew if c.get("department") == "Writing"]
    if kind == "tv":
        writers = [dict(c, id=c.get("id")) for c in d.get("created_by") or []] + writers
    return {
        "cast": [
            (c["id"], c["name"], c.get("profile_path"), c.get("character") or None)
            for c in (cr.get("cast") or [])[:20] if c.get("id") is not None and c.get("name")
        ],
        "director": pick([c for c in crew if c.get("job") == "Director"], 10),
        "writer": pick(writers, 10),
        "producer": pick([c for c in crew if c.get("job") in ("Producer", "Executive Producer")], 10),
    }


def _pick_poster(d):
    """Pôster remoto: com `lang_art` o do idioma da biblioteca (senão o padrão do TMDB); sem, o mais votado de qualquer idioma."""
    posters = [p for p in (d.get("images") or {}).get("posters") or [] if p.get("file_path")]
    if _opts().get("lang_art", True):
        for p in posters:
            if p.get("iso_639_1") == _lang()[:2]:
                return p["file_path"]
    elif posters:
        return posters[0]["file_path"]
    return d.get("poster_path")


def _pick_logo(d):
    """Caminho remoto do logo (com `lang_art`: pt, depois en, depois sem idioma; sem: o mais votado)."""
    logos = (d.get("images") or {}).get("logos") or []
    if not _opts().get("lang_art", True):
        return next((lg["file_path"] for lg in logos if lg.get("file_path")), None)
    for lang in (_lang()[:2], "en", None):
        for lg in logos:
            if lg.get("iso_639_1") == lang and lg.get("file_path"):
                return lg["file_path"]
    return None


def _save_credits(conn, media_id, d, kind, locks):
    for role, people in _credit_lists(d, kind).items():
        if locks.get(role):
            continue
        conn.execute("DELETE FROM credits WHERE media_id = ? AND episode_id IS NULL AND role = ?", (media_id, role))
        for i, (tid, name, photo, character) in enumerate(people):
            conn.execute(
                "INSERT INTO people (name, photo, tmdb_id) VALUES (?, ?, ?) "
                "ON CONFLICT(tmdb_id) DO UPDATE SET name = excluded.name, "
                "photo = CASE WHEN people.photo IS NULL OR people.photo LIKE '/%' THEN excluded.photo ELSE people.photo END",
                (name, photo, tid),
            )
            pid = conn.execute("SELECT id FROM people WHERE tmdb_id = ?", (tid,)).fetchone()["id"]
            conn.execute(
                "INSERT INTO credits (media_id, episode_id, person_id, role, character, ord) VALUES (?, NULL, ?, ?, ?, ?)",
                (media_id, pid, role, character, i),
            )


def _save_reviews(conn, media_id, d):
    """Cache das avaliações do TMDB (até 10, texto cortado em 2000 caracteres)."""
    rows = []
    for r in ((d.get("reviews") or {}).get("results") or [])[:10]:
        text = (r.get("content") or "").strip()
        if not text:
            continue
        rating = (r.get("author_details") or {}).get("rating")
        rows.append((media_id, r.get("author") or None, rating if isinstance(rating, (int, float)) else None,
                     (r.get("created_at") or "")[:10] or None, text[:2000]))
    conn.execute("DELETE FROM reviews WHERE media_id = ?", (media_id,))
    conn.executemany("INSERT INTO reviews (media_id, author, rating, created, text) VALUES (?, ?, ?, ?, ?)", rows)


def _save_related(conn, media_id, d):
    conn.execute("DELETE FROM related WHERE media_id = ?", (media_id,))
    for i, r in enumerate(((d.get("recommendations") or {}).get("results") or [])[:40]):
        if r.get("id") is not None:
            conn.execute("INSERT OR IGNORE INTO related (media_id, tmdb_id, ord) VALUES (?, ?, ?)", (media_id, r["id"], i))


def _save_tags(conn, media_id, kind, names, locks, lock_key):
    if locks.get(lock_key):
        return
    conn.execute("DELETE FROM tags WHERE media_id = ? AND kind = ?", (media_id, kind))
    for n in names:
        conn.execute("INSERT OR IGNORE INTO tags (media_id, kind, name) VALUES (?, ?, ?)", (media_id, kind, n))


def _apply(conn, media_id, d, kind):
    """Grava os metadados do TMDB respeitando media.locks (campo travado nunca é sobrescrito)."""
    movie = kind == "movie"
    locks = _locks(conn, media_id)
    date = (d.get("release_date") if movie else d.get("first_air_date")) or None
    year = int(date[:4]) if date else None
    rating = d.get("vote_average")
    imdb_id = (d.get("external_ids") or {}).get("imdb_id") or d.get("imdb_id") or None
    imdb, rt = omdb_ratings(imdb_id)  # rede antes de qualquer escrita (9.3)
    # (coluna, valor, trava, coalesce)
    fields = [
        ("title", (d.get("title") or None) if movie else None, "title", True),
        ("year", year, "release_date", True),
        ("overview", d.get("overview"), "overview", False),
        ("genres", _genres(d), "genres", False),
        ("poster", _pick_poster(d), "poster", False),
        ("original_title", (d.get("original_title") if movie else d.get("original_name")) or None, "original_title", True),
        ("release_date", date, "release_date", True),
        ("content_rating", _certification(d, kind), "content_rating", True),
        ("rating", round(rating, 1) if rating else None, "rating", True),
        ("tagline", d.get("tagline") or None, "tagline", True),
        ("backdrop", d.get("backdrop_path"), "backdrop", False),
        ("logo", _pick_logo(d), "logo", False),
        ("imdb_id", imdb_id, "imdb_id", True),
        ("imdb_rating", imdb, "imdb_rating", True),
        ("rt_rating", rt, "rt_rating", True),
    ]
    sets, vals = ["tmdb_id = ?", "data_lang = ?"], [d["id"], _lang()]  # 59.41: idioma em que estes dados foram gravados
    for col, val, lock, coalesce in fields:
        if col != "title" and locks.get(lock):
            continue
        if col == "title" and (not movie or locks.get("title")):
            continue  # série: o título é a chave de ligação dos episódios novos
        sets.append(f"{col} = COALESCE(?, {col})" if coalesce else f"{col} = ?")
        vals.append(val)
    conn.execute(f"UPDATE media SET {', '.join(sets)} WHERE id = ?", (*vals, media_id))
    _save_tags(conn, media_id, "genre", [g["name"] for g in d.get("genres", []) if g.get("name")], locks, "genres")
    _save_tags(conn, media_id, "country", [c["name"] for c in d.get("production_countries") or [] if c.get("name")], locks, "country")
    _save_credits(conn, media_id, d, kind, locks)
    _save_reviews(conn, media_id, d)
    _save_related(conn, media_id, d)
    conn.execute("UPDATE media SET meta_ok = 1 WHERE id = ?", (media_id,))


def apply_movie(conn, media_id, d):
    _apply(conn, media_id, d, "movie")


def _season_locks(row):
    try:
        v = json.loads(row["locks"]) if row and row["locks"] else {}
    except ValueError:
        v = {}
    return v if isinstance(v, dict) else {}


def _upsert_season(conn, media_id, n, title, overview, poster):
    """Cria/atualiza seasons (media_id, n); campo travado ou já preenchido (overview/título vazios) é respeitado."""
    row = conn.execute("SELECT * FROM seasons WHERE media_id = ? AND season = ?", (media_id, n)).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO seasons (media_id, season, title, overview, poster) VALUES (?, ?, ?, ?, ?)",
            (media_id, n, title or None, (overview or "").strip() or None, poster or None),
        )
        return
    lk = _season_locks(row)
    sets, vals = [], []
    for col, val in (("title", title or None), ("overview", (overview or "").strip() or None), ("poster", poster or None)):
        if lk.get(col) or val is None:
            continue
        sets.append(f"{col} = ?")
        vals.append(val)
    if sets:
        conn.execute(f"UPDATE seasons SET {', '.join(sets)} WHERE id = ?", (*vals, row["id"]))


def apply_show(conn, media_id, d):
    """Não sobrescreve o título (chave de ligação dos episódios novos)."""
    _apply(conn, media_id, d, "tv")
    for sn in d.get("seasons") or []:
        if sn.get("season_number") is not None:
            _upsert_season(conn, media_id, sn["season_number"], sn.get("name"), sn.get("overview"), sn.get("poster_path"))


def match_movie(title, year=None):
    """Busca o filme no TMDB e devolve os detalhes (ou None se não achar)."""
    params = {"query": title}
    if year:
        params["year"] = year
    results = tmdb_get("/search/movie", **params).get("results")
    if not results and year:
        results = tmdb_get("/search/movie", query=title).get("results")
    if not results:
        return None
    return tmdb_details("movie", results[0]["id"])


_RESET_LIBS = "(SELECT id FROM libraries WHERE type IN ('movie', 'show'))"


def reset_for_language(conn, new):
    """59.41: o idioma mudou para `new`. Guarda os dados do idioma anterior (meta_cache) e devolve os já guardados em `new`; só o que nunca
    foi buscado nesse idioma é marcado para o próximo exame (meta_ok, título/sinopse/crew_ok dos episódios sem trava, biografias).
    Campos travados (locks) ficam; itens que já estão em `new` não são tocados."""
    from server import meta_cache
    r = conn.execute("SELECT value FROM settings WHERE key = 'data_lang'").fetchone()
    legacy = (r["value"] if r and r["value"] else None) or new
    meta_cache.save(conn, legacy, new)
    done = meta_cache.restore(conn, legacy, new)
    todo = (f"SELECT id FROM media WHERE tmdb_id > 0 AND library_id IN {_RESET_LIBS} AND COALESCE(data_lang, ?) != ?", (legacy, new))
    ids = [x["id"] for x in conn.execute(*todo) if x["id"] not in done]
    for i in range(0, len(ids), 500):
        part, q = ids[i:i + 500], ",".join("?" * len(ids[i:i + 500]))
        conn.execute(f"UPDATE media SET meta_ok = NULL WHERE id IN ({q})", part)
        conn.execute(f"UPDATE episodes SET title = NULL, overview = NULL WHERE (locks IS NULL OR locks IN ('', '{{}}')) AND media_id IN ({q})", part)
        conn.execute(f"UPDATE episodes SET crew_ok = NULL WHERE title IS NULL AND media_id IN ({q})", part)
    conn.execute("UPDATE people SET info_ok = 0, info_at = 0 WHERE tmdb_id IS NOT NULL AND bio IS NOT NULL")
    conn.execute("INSERT INTO settings (key, value) VALUES ('data_lang', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (new,))


@_in_library(True)
def identify_movies(library_id, media_id=None):
    """Preenche metadados dos filmes sem correspondência.
    media.tmdb_id: NULL = ainda não buscado, 0 = sem correspondência. media.poster guarda o poster_path do TMDB."""
    if not config.TMDB_API_KEY:
        return 0
    done = 0
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, year, tmdb_id FROM media WHERE library_id = ? AND path IS NOT NULL "
            "AND (tmdb_id IS NULL OR (tmdb_id > 0 AND meta_ok IS NULL)) AND (? IS NULL OR id = ?)",
            (library_id, media_id, media_id),
        ).fetchall()
        for r in rows:
            scanstate.set_current(r["id"])
            try:
                if r["tmdb_id"]:  # já casado antes da 23.13/23.17: só completa os metadados (sem nova busca)
                    try:
                        apply_movie(conn, r["id"], tmdb_details("movie", r["tmdb_id"]))
                        done += 1
                    except requests.HTTPError as e:
                        if e.response is None or e.response.status_code != 404:
                            raise
                    except (KeyError, ValueError, TypeError):
                        conn.rollback()
                    conn.execute("UPDATE media SET meta_ok = 1 WHERE id = ?", (r["id"],))  # não repete a cada scan
                    conn.commit()
                    download_posters(library_id, r["id"])  # 35.14: a capa do item fica pronta ao terminar o item
                    continue
                d = match_movie(r["title"], r["year"])
                if d is not None:
                    apply_movie(conn, r["id"], d)
            except requests.RequestException:
                break  # sem rede/chave inválida: tenta de novo no próximo scan
            except (KeyError, ValueError, TypeError):
                d = None  # resposta inesperada: marca sem correspondência e segue
            if d is None:
                conn.execute("UPDATE media SET tmdb_id = 0 WHERE id = ?", (r["id"],))
                conn.commit()
                continue
            conn.commit()
            download_posters(library_id, r["id"])  # 35.14: a capa do item fica pronta ao terminar o item
            done += 1
    return done


def match_show(title, year=None):
    """Busca a série no TMDB e devolve os detalhes (ou None se não achar)."""
    params = {"query": title}
    if year:
        params["first_air_date_year"] = year
    results = tmdb_get("/search/tv", **params).get("results")
    if not results and year:
        results = tmdb_get("/search/tv", query=title).get("results")
    if not results:
        return None
    return tmdb_details("tv", results[0]["id"])


@_in_library(True)
def identify_shows(library_id, media_id=None):
    """Preenche metadados das séries sem correspondência (tmdb_id NULL = não buscado, 0 = sem correspondência).
    O título NÃO é sobrescrito: ele é a chave que o scanner usa para ligar episódios novos à série."""
    if not config.TMDB_API_KEY:
        return 0
    done = 0
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, year, tmdb_id FROM media WHERE library_id = ? AND path IS NULL "
            "AND (tmdb_id IS NULL OR (tmdb_id > 0 AND meta_ok IS NULL)) AND (? IS NULL OR id = ?)",
            (library_id, media_id, media_id),
        ).fetchall()
        for r in rows:
            scanstate.set_current(r["id"])
            try:
                if r["tmdb_id"]:  # já casado antes da 23.13/23.17: só completa os metadados (sem nova busca)
                    try:
                        apply_show(conn, r["id"], tmdb_details("tv", r["tmdb_id"]))
                        done += 1
                    except requests.HTTPError as e:
                        if e.response is None or e.response.status_code != 404:
                            raise
                    except (KeyError, ValueError, TypeError):
                        conn.rollback()
                    conn.execute("UPDATE media SET meta_ok = 1 WHERE id = ?", (r["id"],))  # não repete a cada scan
                    conn.commit()
                    download_posters(library_id, r["id"])  # 35.14: a capa do item fica pronta ao terminar o item
                    continue
                d = match_show(r["title"], r["year"])
                if d is not None:
                    apply_show(conn, r["id"], d)
            except requests.RequestException:
                break
            except (KeyError, ValueError, TypeError):
                d = None
            if d is None:
                conn.execute("UPDATE media SET tmdb_id = 0 WHERE id = ?", (r["id"],))
                conn.commit()
                continue
            conn.commit()
            download_posters(library_id, r["id"])  # 35.14: a capa do item fica pronta ao terminar o item
            done += 1
    return done


# ---------- TheTVDB (episódios) ----------
TVDB_API = "https://api4.thetvdb.com/v4"
_tvdb_token = None


def reset_tvdb_token():
    """45.5: a chave do TVDB mudou; o token em cache era da anterior."""
    global _tvdb_token
    _tvdb_token = None


def tvdb_get(path, **params):
    global _tvdb_token
    for attempt in (0, 1):
        if not _tvdb_token:
            r = requests.post(TVDB_API + "/login", json={"apikey": config.TVDB_API_KEY}, timeout=15)
            r.raise_for_status()
            _tvdb_token = r.json()["data"]["token"]
        r = requests.get(
            TVDB_API + path, params=params, headers={"Authorization": "Bearer " + _tvdb_token}, timeout=20
        )
        if r.status_code == 401 and attempt == 0:
            _tvdb_token = None
            continue
        r.raise_for_status()
        return r.json()


def _tvdb_episodes(path):
    out, page = [], 0
    while True:
        j = tvdb_get(path, page=page)
        out += (j.get("data") or {}).get("episodes") or []
        if (j.get("links") or {}).get("next") is None:
            return out
        page += 1


def fetch_tvdb_episodes(tvdb_id):
    """Devolve {(temporada, episódio): (título, sinopse)}; traduzido (TVDB_LANG) quando existir."""
    eps = {}
    for i, path in enumerate((f"/series/{tvdb_id}/episodes/default", f"/series/{tvdb_id}/episodes/default/{_opts().get('tvdb_lang') or config.TVDB_LANG}")):
        try:
            items = _tvdb_episodes(path)
        except requests.HTTPError as e:
            if i == 1 and e.response is not None and e.response.status_code == 404:
                continue  # sem tradução: usa os títulos originais
            raise
        for e in items:
            key = (e.get("seasonNumber"), e.get("number"))
            name, overview = eps.get(key, ("", None))
            eps[key] = (e.get("name") or name, e.get("overview") or overview)
    return eps


def find_tvdb_id(show):
    """id da série no TheTVDB: via TMDB (external_ids) ou busca por nome."""
    if show["tmdb_id"] and show["tmdb_id"] > 0 and config.TMDB_API_KEY:
        ext = tmdb_get(f"/tv/{show['tmdb_id']}/external_ids")
        if ext.get("tvdb_id"):
            return int(ext["tvdb_id"])
    found = tvdb_get("/search", query=show["title"], type="series").get("data") or []
    return int(found[0]["tvdb_id"]) if found else None


@_in_library(True)
def identify_episodes(library_id, media_id=None):
    """Preenche título/sinopse dos episódios (title NULL = não buscado, '' = TVDB não tem).
    media.tvdb_id: NULL = não buscado, 0 = série não encontrada. media_id restringe a uma série."""
    if not config.TVDB_API_KEY:
        return 0
    done = 0
    with get_db() as conn:
        shows = conn.execute(
            "SELECT DISTINCT m.id, m.title, m.tmdb_id, m.tvdb_id FROM media m "
            "JOIN episodes e ON e.media_id = m.id "
            "WHERE m.library_id = ? AND m.path IS NULL AND e.title IS NULL "
            "AND (m.tvdb_id IS NULL OR m.tvdb_id > 0) AND (? IS NULL OR m.id = ?)",
            (library_id, media_id, media_id),
        ).fetchall()
        for s in shows:
            try:
                tvdb_id = s["tvdb_id"] or find_tvdb_id(s)
                if not tvdb_id:
                    conn.execute("UPDATE media SET tvdb_id = 0 WHERE id = ?", (s["id"],))
                    conn.commit()
                    continue
                conn.execute("UPDATE media SET tvdb_id = ? WHERE id = ?", (tvdb_id, s["id"]))
                conn.commit()  # a chamada de rede abaixo não pode segurar a transação
                eps = fetch_tvdb_episodes(tvdb_id)
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:  # só esta série falhou: não trava as demais
                    conn.execute("UPDATE media SET tvdb_id = 0 WHERE id = ?", (s["id"],))
                    conn.commit()
                    continue
                break
            except requests.RequestException:
                break
            except (KeyError, ValueError, TypeError):
                conn.execute("UPDATE media SET tvdb_id = 0 WHERE id = ?", (s["id"],))
                conn.commit()
                continue
            pending = conn.execute(
                "SELECT id, season, episode FROM episodes WHERE media_id = ? AND title IS NULL", (s["id"],)
            ).fetchall()
            for e in pending:
                name, overview = eps.get((e["season"], e["episode"]), ("", None))
                conn.execute("UPDATE episodes SET title = ?, overview = ? WHERE id = ?", (name, overview, e["id"]))
                done += 1
            conn.commit()
    return done


_EN_WORDS = {"the", "and", "of", "to", "in", "with", "her", "his", "after", "for", "is", "that", "on", "as", "who", "from"}
_PT_WORDS = {"o", "a", "de", "do", "da", "que", "e", "com", "em", "um", "uma", "para", "os", "as", "se", "por", "na", "no", "ele", "ela"}


def _looks_english(text):
    """Heurística simples (36.2): mais palavras comuns do inglês que do português."""
    w = re.findall(r"[a-zà-ú']+", (text or "").lower())
    return sum(x in _EN_WORDS for x in w) > sum(x in _PT_WORDS for x in w)


def _save_episode_crew(conn, mid, eid, x):
    """Diretor e roteirista do episódio (crew de /tv/ID/season/N, 36.1). Só preenche o papel que ainda não tem crédito: não sobrescreve o que o Editar gravou."""
    crew = x.get("crew") or []
    for role, rows in (("director", [c for c in crew if c.get("job") == "Director"]),
                       ("writer", [c for c in crew if c.get("department") == "Writing"])):
        if conn.execute("SELECT 1 FROM credits WHERE episode_id = ? AND role = ?", (eid, role)).fetchone():
            continue
        seen, ord_ = set(), 0
        for c in rows:
            if c.get("id") is None or c["id"] in seen or not c.get("name"):
                continue
            seen.add(c["id"])
            conn.execute(
                "INSERT INTO people (name, photo, tmdb_id) VALUES (?, ?, ?) "
                "ON CONFLICT(tmdb_id) DO UPDATE SET name = excluded.name, "
                "photo = CASE WHEN people.photo IS NULL OR people.photo LIKE '/%' THEN excluded.photo ELSE people.photo END",
                (c["name"], c.get("profile_path"), c["id"]),
            )
            pid = conn.execute("SELECT id FROM people WHERE tmdb_id = ?", (c["id"],)).fetchone()["id"]
            conn.execute("INSERT INTO credits (media_id, episode_id, person_id, role, character, ord) VALUES (?, ?, ?, ?, NULL, ?)",
                         (mid, eid, pid, role, ord_))
            ord_ += 1
            if ord_ >= 3:
                break


def _ep_locks(row):
    try:
        v = json.loads(row["locks"]) if row["locks"] else {}
    except ValueError:
        v = {}
    return v if isinstance(v, dict) else {}


@_in_library(True)
def identify_seasons(library_id, media_id=None):
    """Preenche seasons e, nos episódios, still/air_date/rating a partir do TMDB (/tv/ID/season/N).
    episodes.still: NULL = não buscado, '' = TMDB não tem (a rota /still gera um frame com ffmpeg),
    '/abc.jpg' = remoto, 'still/12.jpg' = arquivo local."""
    if not config.TMDB_API_KEY:
        return 0
    done = 0
    with get_db() as conn:
        shows = conn.execute(
            "SELECT id, tmdb_id, imdb_id FROM media WHERE library_id = ? AND path IS NULL AND tmdb_id > 0 AND (? IS NULL OR id = ?)",
            (library_id, media_id, media_id),
        ).fetchall()
        for sh in shows:
            nums = [r["season"] for r in conn.execute(
                "SELECT DISTINCT season FROM episodes WHERE media_id = ? AND (still IS NULL OR crew_ok IS NULL OR crew_ok < 2 "
                "OR season NOT IN (SELECT season FROM seasons WHERE media_id = ?))", (sh["id"], sh["id"]))]
            stop = False
            for n in nums:
                try:
                    j = tmdb_get(f"/tv/{sh['tmdb_id']}/season/{n}")
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 404:
                        conn.execute("UPDATE episodes SET still = CASE WHEN still IS NULL THEN '' ELSE still END, crew_ok = 2 "
                                     "WHERE media_id = ? AND season = ?", (sh["id"], n))
                        conn.commit()
                        continue
                    stop = True
                    break
                except requests.RequestException:
                    stop = True
                    break
                except (KeyError, ValueError, TypeError):
                    continue
                try:
                    _upsert_season(conn, sh["id"], n, j.get("name"), j.get("overview"), j.get("poster_path"))
                    by = {x.get("episode_number"): x for x in j.get("episodes") or []}
                    imdb_by = omdb_season(sh["imdb_id"], n)
                    by_en = {}
                    if not _lang().lower().startswith("en"):  # 36.3 (59.37: qualquer idioma que não seja inglês): nomes em inglês, para saber se o título gravado é o original sem tradução
                        try:
                            by_en = {y.get("episode_number"): (y.get("name") or "").strip()
                                     for y in tmdb_get(f"/tv/{sh['tmdb_id']}/season/{n}", language="en-US").get("episodes") or []}
                        except (requests.RequestException, ValueError, AttributeError):
                            by_en = {}
                    for e in conn.execute("SELECT * FROM episodes WHERE media_id = ? AND season = ?", (sh["id"], n)).fetchall():
                        x = by.get(e["episode"]) or {}
                        lk = _ep_locks(e)
                        still = e["still"] if lk.get("still") or (e["still"] and not e["still"].startswith("/") and e["still"] != "") else (x.get("still_path") or "")
                        air = e["air_date"] if lk.get("air_date") or lk.get("release_date") else (x.get("air_date") or e["air_date"])
                        vote = x.get("vote_average")
                        rating = e["rating"] if lk.get("rating") else (round(vote, 1) if vote else e["rating"])
                        # 36.2: TVDB sem tradução deixa a sinopse em inglês; em biblioteca pt usa a do TMDB (pt-BR) no lugar
                        new_ov = (x.get("overview") or "").strip()
                        if (new_ov and not lk.get("overview") and not _lang().lower().startswith("en") and not _looks_english(new_ov)
                                and (not (e["overview"] or "").strip() or _looks_english(e["overview"]))):
                            conn.execute("UPDATE episodes SET overview = ? WHERE id = ?", (new_ov, e["id"]))
                        t_pt, t_en, t_now = (x.get("name") or "").strip(), by_en.get(e["episode"], ""), (e["title"] or "").strip()
                        if t_pt and not lk.get("title") and (not t_now or (t_en and t_now.lower() == t_en.lower() and t_pt.lower() != t_en.lower())):
                            conn.execute("UPDATE episodes SET title = ? WHERE id = ?", (t_pt, e["id"]))  # 36.3
                        conn.execute("UPDATE episodes SET still = ?, air_date = ?, rating = ?, imdb_rating = COALESCE(?, imdb_rating), crew_ok = 2 WHERE id = ?",
                                     (still, air, rating, imdb_by.get(e["episode"]), e["id"]))
                        _save_episode_crew(conn, sh["id"], e["id"], x)
                        done += 1
                except (KeyError, ValueError, TypeError):
                    conn.rollback()
                    continue
                conn.commit()
            if stop:
                break
    return done


# ---------- Pôsteres ----------
TMDB_IMG = "https://image.tmdb.org/t/p/"


# ---------- Arte local (28.7) ----------
LOCAL_ART = {"poster": ("poster", "folder", "cover"), "backdrop": ("fanart", "backdrop")}
_ART_EXT = (".jpg", ".jpeg", ".png", ".webp")
_LOCAL_SEASON_DIR = re.compile(r"^(?:(?:season|temporada|saison|staffel|s)[\s._-]*\d{1,2}|specials?|especiais)$", re.I)
MAX_LOCAL_IMG = 10 * 1024 * 1024


def _find_art(folder, names):
    try:
        files = {f.lower(): f for f in os.listdir(folder)}
    except OSError:
        return None
    for n in names:
        for e in _ART_EXT:
            f = files.get(n + e)
            if f and os.path.isfile(os.path.join(folder, f)):
                return os.path.join(folder, f)
    return None


def _sniff_ext(path):
    try:
        with open(path, "rb") as f:
            b = f.read(12)
    except OSError:
        return None
    if b[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return ".webp"
    return None


def _item_dir(conn, row, roots):
    """Pasta própria do filme/série (nunca a raiz da biblioteca, para um poster.jpg solto não valer para todos)."""
    if row["path"]:
        d = os.path.dirname(row["path"])
    else:
        ep = conn.execute("SELECT path FROM episodes WHERE media_id = ? ORDER BY season, episode LIMIT 1", (row["id"],)).fetchone()
        if not ep:
            return None
        for root in roots:
            rel = os.path.relpath(ep["path"], root)
            if not rel.startswith(".."):
                break
        else:
            return None
        parts = rel.split(os.sep)
        if len(parts) < 2 or _LOCAL_SEASON_DIR.match(parts[0]):
            return None
        d = os.path.join(root, parts[0])
    d = os.path.normpath(d)
    return None if d in {os.path.normpath(r) for r in roots} else d


@_in_library()
def apply_local_art(library_id, media_id=None):
    """`local_art`: poster/folder/cover.* e fanart/backdrop.* na pasta do item vencem o TMDB (copiados para data/posters;
    campo travado em `locks` nunca é trocado). Roda depois da identificação e antes dos downloads."""
    if not _opts().get("local_art", True):
        return 0
    done = 0
    with get_db() as conn:
        roots = library_folders(conn, library_id)
        rows = conn.execute("SELECT id, path, poster, backdrop FROM media WHERE library_id = ? AND (? IS NULL OR id = ?)",
                            (library_id, media_id, media_id)).fetchall()
        for r in rows:
            d = _item_dir(conn, r, roots)
            if not d:
                continue
            locks = _locks(conn, r["id"])
            for col, names in LOCAL_ART.items():
                if locks.get(col):
                    continue
                src = _find_art(d, names)
                ext = _sniff_ext(src) if src else None
                try:
                    if not ext or os.path.getsize(src) > MAX_LOCAL_IMG:
                        continue
                    rel = f"{'bd/' if col == 'backdrop' else ''}{r['id']}{ext}"
                    dest = os.path.join(config.POSTERS_DIR, rel)
                    if r[col] == rel and os.path.exists(dest) and os.path.getmtime(dest) >= os.path.getmtime(src):
                        continue
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copyfile(src, dest)
                except OSError:
                    continue
                if r[col] and r[col] != rel:
                    remove_local(r[col])
                conn.execute(f"UPDATE media SET {col} = ? WHERE id = ?", (rel, r["id"]))
                conn.commit()
                done += 1
    return done


@_in_library()
def download_posters(library_id, media_id=None):
    """Baixa para data/posters/ os pôsteres ainda remotos (media_id restringe a um item).
    media.poster: '/abc.jpg' = caminho remoto do TMDB; '12.jpg' = arquivo local; NULL = sem pôster."""
    done = 0
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, poster FROM media WHERE library_id = ? AND poster LIKE '/%' AND (? IS NULL OR id = ?)",
            (library_id, media_id, media_id),
        ).fetchall()
        for r in rows:
            scanstate.set_current(r["id"])
            try:
                resp = requests.get(TMDB_IMG + config.TMDB_IMG_SIZE + r["poster"], timeout=20)
                resp.raise_for_status()
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    conn.execute("UPDATE media SET poster = NULL WHERE id = ?", (r["id"],))
                    conn.commit()
                    continue
                break
            except requests.RequestException:
                break
            name = f"{r['id']}.jpg"
            os.makedirs(config.POSTERS_DIR, exist_ok=True)
            with open(os.path.join(config.POSTERS_DIR, name), "wb") as f:
                f.write(resp.content)
            conn.execute("UPDATE media SET poster = ? WHERE id = ?", (name, r["id"]))
            conn.commit()
            done += 1
    return done



# ---------- Backdrop, logo e fotos de elenco (23.14) ----------
# media.backdrop/logo e people.photo: '/abc.jpg' = remoto do TMDB; 'bd/12.jpg' = arquivo local em data/posters; NULL = sem imagem
IMG_SPECS = {"backdrop": ("bd", "w1280"), "logo": ("logo", "w500"), "season": ("season", "w342"), "still": ("still", "w300")}
MEDIA_IMG_COLS = ("backdrop", "logo")  # colunas de media baixadas no primeiro laço de download_images
PEOPLE_SIZE = "w185"


def remove_local(name):
    """Apaga arquivo local de imagem (caminho relativo a data/posters; remoto '/...' é ignorado)."""
    if not name or name.startswith("/"):
        return
    rel = os.path.normpath(name)
    if os.path.isabs(rel) or rel.startswith(".."):
        return
    try:
        os.remove(os.path.join(config.POSTERS_DIR, rel))
    except OSError:
        pass


def show_image_names(conn, where, args):
    """Arquivos locais de temporadas e stills das mídias que casam com `where` (condição sobre media m)."""
    names = [r[0] for r in conn.execute(
        f"SELECT s.poster FROM seasons s JOIN media m ON m.id = s.media_id WHERE {where}", args)]
    names += [r[0] for r in conn.execute(
        f"SELECT e.still FROM episodes e JOIN media m ON m.id = e.media_id WHERE {where}", args)]
    return [n for n in names if n and not n.startswith("/")]


def collection_image_names(conn, where, args):
    """Arquivos locais de imagens (col/...) das coleções que casam com `where` (condição sobre collections c)."""
    names = []
    for r in conn.execute(f"SELECT c.poster, c.backdrop, c.logo, c.square FROM collections c WHERE {where}", args):
        names += [r[k] for k in ("poster", "backdrop", "logo", "square")]
    return [n for n in names if n and not n.startswith("/")]


def prune_people():
    """Remove pessoas sem nenhum crédito e as fotos delas."""
    with get_db() as conn:
        rows = conn.execute("SELECT id, photo, photo_big FROM people WHERE id NOT IN (SELECT person_id FROM credits)").fetchall()
        for r in rows:
            conn.execute("DELETE FROM people WHERE id = ?", (r["id"],))
            remove_local(r["photo"])
            remove_local(r["photo_big"])


def _download(remote, size, rel):
    """Baixa para data/posters/<rel>; devolve True, False (404: sem imagem) ou None (rede: tentar depois)."""
    try:
        resp = requests.get(TMDB_IMG + size + remote, timeout=20)
        resp.raise_for_status()
    except requests.HTTPError as e:
        return False if e.response is not None and e.response.status_code == 404 else None
    except requests.RequestException:
        return None
    path = os.path.join(config.POSTERS_DIR, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(resp.content)
    return True


@_in_library()
def download_images(library_id, media_id=None):
    """Baixa backdrops, logos e fotos do elenco ainda remotos (media_id restringe a um item)."""
    done = 0
    with get_db() as conn:
        for col in MEDIA_IMG_COLS:
            sub, size = IMG_SPECS[col]
            rows = conn.execute(
                f"SELECT id, {col} AS img FROM media WHERE library_id = ? AND {col} LIKE '/%' AND (? IS NULL OR id = ?)",
                (library_id, media_id, media_id),
            ).fetchall()
            for r in rows:
                rel = f"{sub}/{r['id']}{os.path.splitext(r['img'])[1] or '.jpg'}"
                ok = _download(r["img"], size, rel)
                if ok is None:
                    break
                conn.execute(f"UPDATE media SET {col} = ? WHERE id = ?", (rel if ok else None, r["id"]))
                conn.commit()
                done += ok
        rows = conn.execute(
            "SELECT s.id, s.poster AS img, s.media_id, s.season FROM seasons s JOIN media m ON m.id = s.media_id "
            "WHERE m.library_id = ? AND s.poster LIKE '/%' AND (? IS NULL OR m.id = ?)", (library_id, media_id, media_id),
        ).fetchall()
        for r in rows:
            rel = f"season/{r['media_id']}-{r['season']}.jpg"
            ok = _download(r["img"], IMG_SPECS["season"][1], rel)
            if ok is None:
                break
            conn.execute("UPDATE seasons SET poster = ? WHERE id = ?", (rel if ok else None, r["id"]))
            conn.commit()
            done += ok
        rows = conn.execute(
            "SELECT e.id, e.still AS img FROM episodes e JOIN media m ON m.id = e.media_id "
            "WHERE m.library_id = ? AND e.still LIKE '/%' AND (? IS NULL OR m.id = ?)", (library_id, media_id, media_id),
        ).fetchall()
        for r in rows:
            rel = f"still/{r['id']}.jpg"
            ok = _download(r["img"], IMG_SPECS["still"][1], rel)
            if ok is None:
                break
            conn.execute("UPDATE episodes SET still = ? WHERE id = ?", (rel if ok else "", r["id"]))
            conn.commit()
            done += ok
        rows = conn.execute(
            "SELECT DISTINCT p.id, p.photo FROM people p JOIN credits c ON c.person_id = p.id "
            "JOIN media m ON m.id = c.media_id WHERE m.library_id = ? AND p.photo LIKE '/%' AND (? IS NULL OR m.id = ?)",
            (library_id, media_id, media_id),
        ).fetchall()
        for r in rows:
            rel = f"people/{r['id']}.jpg"
            ok = _download(r["photo"], PEOPLE_SIZE, rel)
            if ok is None:
                break
            conn.execute("UPDATE people SET photo = ? WHERE id = ?", (rel if ok else None, r["id"]))
            conn.commit()
            done += ok
    return done
