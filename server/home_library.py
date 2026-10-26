"""32.6: fileiras do acervo (adicionados recentemente, coleções, listas de reprodução recentes)."""
from server.collections import library_collections
from server.db import get_db
from server import i18n
from server.home_rows import expand, genre_title, poster_items, row, spec
from server.libraries import get_setting  # noqa: F401
from server.playlists import playlist_ids, playlist_seconds, total_text


def _recent_ids(conn, lib_ids):
    """Itens das bibliotecas por data de adição (série: o episódio mais novo), mais recentes primeiro."""
    if not lib_ids:
        return []
    ql = ",".join("?" * len(lib_ids))
    return [r["id"] for r in conn.execute(
        "SELECT m.id, COALESCE(MAX(e.added_at), m.added_at) AS a FROM media m LEFT JOIN episodes e ON e.media_id = m.id "
        f"WHERE m.library_id IN ({ql}) GROUP BY m.id ORDER BY a DESC, m.id DESC LIMIT 40", lib_ids)]


def _recent_specs(ctx, kind, merged_title, libs):
    ids = [i for i, t in ctx.libs.items() if t == kind]

    def provider_for(lib_ids):
        def provider(c):
            with get_db() as conn:
                return poster_items(conn, c, _recent_ids(conn, lib_ids))
        return provider
    if ctx.merge_recent:  # 28.8: uma fileira por tipo com todas as bibliotecas
        return [spec(f"recent_{kind}s", merged_title, "poster", provider_for(ids))] if ids else []
    return [spec(f"recent_lib_{i}", lambda c, items, n=libs[i]: i18n.tr("home.row.recent_in", name=n), "poster", provider_for([i])) for i in ids]


def _lib_names(ctx):
    from server.libraries import visible_libraries
    return {l["id"]: l["name"] for l in visible_libraries(ctx.user_id)}


def hero_recent(user_id, profile_id, limit=8):
    """54.12: itens do destaque do celular — os mais recentes entre filmes E séries (todas as bibliotecas liberadas e visíveis no Início),
    por data de adição (série: o episódio mais novo). Devolve itens do `poster_items` ({id, type, title, year, ...})."""
    from server.home_rows import Ctx
    ctx = Ctx(user_id, profile_id)
    with get_db() as conn:
        mv = _recent_ids(conn, [i for i, t in ctx.libs.items() if t == "movie"])
        sh = _recent_ids(conn, [i for i, t in ctx.libs.items() if t == "show"])
        by_date = {r["id"]: r["a"] for r in conn.execute(
            "SELECT m.id, COALESCE(MAX(e.added_at), m.added_at) AS a FROM media m LEFT JOIN episodes e ON e.media_id = m.id "
            f"WHERE m.id IN ({','.join('?' * len(mv + sh)) or 'NULL'}) GROUP BY m.id", mv + sh)}
        ids = []  # intercala filme e série (cada lado já vem do mais novo ao mais antigo); o que faltar de um lado vem do outro
        for k in range(max(len(mv), len(sh))):
            for src in ((mv, sh) if (by_date.get(mv[0], 0) if mv else 0) >= (by_date.get(sh[0], 0) if sh else 0) else (sh, mv)):
                if k < len(src):
                    ids.append(src[k])
        return poster_items(conn, ctx, ids[:limit])


@expand("recent_movies")
def recent_movies(ctx):
    return _recent_specs(ctx, "movie", "home.row.recent_movies", _lib_names(ctx))


@expand("recent_shows")
def recent_shows(ctx):
    return _recent_specs(ctx, "show", "home.row.recent_shows", _lib_names(ctx))


@row("recent_videos", "home.row.recent_videos", "wide")
def recent_videos(ctx):
    """34.7: vídeos das bibliotecas Outros Vídeos (16:9, só título), mais recentes primeiro."""
    if not ctx.video_libs:
        return []
    from server.home_rows import _pct
    ql = ",".join("?" * len(ctx.video_libs))
    with get_db() as conn:
        rows = conn.execute(
            "SELECT m.id, m.title, m.library_id, m.info, "
            "COALESCE((SELECT pm.watched FROM progress pm WHERE pm.profile_id = ? AND pm.item_type = 'movie' AND pm.item_id = m.id), 0) AS seen, "
            "COALESCE((SELECT pm.position FROM progress pm WHERE pm.profile_id = ? AND pm.item_type = 'movie' AND pm.item_id = m.id), 0) AS pos "
            f"FROM media m WHERE m.library_id IN ({ql}) ORDER BY m.added_at DESC, m.id DESC LIMIT 40",
            (ctx.profile_id, ctx.profile_id, *ctx.video_libs)).fetchall()
    return [{"uid": f"m:{r['id']}", "id": r["id"], "type": "video", "kind": "movie", "title": r["title"], "year": None, "lib": r["library_id"],
             "still": f"/thumb/{r['id']}", "pct": _pct(dict(r, eps=0)), "watched": bool(r["seen"])} for r in rows]


@row("collections", "home.row.collections")
def collections(ctx):
    out = []
    with get_db() as conn:
        for lid in ctx.libs:
            for c in library_collections(conn, lid):
                if c["n"]:
                    out.append({"uid": f"c:{c['id']}", "id": c["id"], "type": "collection", "title": c["title"], "n": c["n"],
                                "poster": f"/collection-poster/{c['id']}", "href": f"/collection/{c['id']}", "created": c["created_at"]})
    out.sort(key=lambda c: (c["created"], c["id"]), reverse=True)
    return out


@row("playlists", "home.row.playlists", "playlist")
def playlists(ctx):
    """Listas do usuário (mais recentes primeiro): capa (própria ou grade 2×2), nome e duração total."""
    if not ctx.libs:
        return []
    ql = ",".join("?" * len(ctx.libs))
    out = []
    with get_db() as conn:
        rows = conn.execute(f"SELECT * FROM playlists WHERE user_id = ? AND library_id IN ({ql}) ORDER BY created_at DESC, id DESC",
                            (ctx.user_id, *ctx.libs)).fetchall()
        for p in rows:
            ids = playlist_ids(conn, p)
            if not ids:
                continue
            sec = playlist_seconds(conn, ids, ctx.libs[p["library_id"]])
            out.append({"uid": f"p:{p['id']}", "id": p["id"], "type": "playlist", "title": p["title"], "n": len(ids),
                        "poster": f"/playlist-image/{p['id']}/poster" if p["poster"] else "", "thumbs": ids[:4],
                        "kind": ctx.libs[p["library_id"]], "sec": int(sec), "dur": total_text(sec), "href": f"/playlist/{p['id']}"})
    return out


GENRE_MIN = 6  # fileira de gênero só aparece com pelo menos 6 itens


def _top_genres(ctx):
    """Os 2 gêneros que o perfil mais assistiu (só com >= 6 itens no acervo); sem histórico, os 2 maiores do acervo."""
    if getattr(ctx, "genres", None) is not None:
        return ctx.genres
    ctx.genres = []
    if not ctx.libs:
        return ctx.genres
    ql = ",".join("?" * len(ctx.libs))
    with get_db() as conn:
        size = {r["name"]: r["n"] for r in conn.execute(
            "SELECT t.name, COUNT(DISTINCT m.id) AS n FROM tags t JOIN media m ON m.id = t.media_id "
            f"WHERE t.kind = 'genre' AND m.library_id IN ({ql}) GROUP BY t.name", list(ctx.libs))}
        seen = {r["name"]: r["n"] for r in conn.execute(
            "SELECT t.name, COUNT(DISTINCT m.id) AS n FROM tags t JOIN media m ON m.id = t.media_id "
            f"WHERE t.kind = 'genre' AND m.library_id IN ({ql}) AND (EXISTS (SELECT 1 FROM progress p WHERE p.profile_id = ? "
            "AND p.item_type = 'movie' AND p.item_id = m.id AND p.watched = 1) OR EXISTS (SELECT 1 FROM episodes e JOIN progress p "
            "ON p.item_type = 'episode' AND p.item_id = e.id AND p.profile_id = ? AND p.watched = 1 WHERE e.media_id = m.id)) "
            "GROUP BY t.name", (*ctx.libs, ctx.profile_id, ctx.profile_id))}
    ok = [g for g, n in size.items() if n >= GENRE_MIN]
    ok.sort(key=lambda g: (-seen.get(g, 0), -size[g], g.casefold()))  # sem histórico, seen = 0 para todos: vence o maior
    ctx.genres = ok[:2]
    return ctx.genres


def _genre_provider(n):
    def provider(ctx):
        g = _top_genres(ctx)
        if len(g) < n:
            return []
        ctx.genre_name = getattr(ctx, "genre_name", {})
        ctx.genre_name[n] = g[n - 1]
        ql = ",".join("?" * len(ctx.libs))
        with get_db() as conn:
            ids = [r["id"] for r in conn.execute(  # não assistidos primeiro, depois os assistidos; mais novos antes
                "SELECT m.id FROM media m JOIN tags t ON t.media_id = m.id AND t.kind = 'genre' AND t.name = ? "
                f"WHERE m.library_id IN ({ql}) ORDER BY m.added_at DESC, m.id DESC", (g[n - 1], *ctx.libs))]
            items = poster_items(conn, ctx, ids)
        return [i for i in items if not i["watched"]] + [i for i in items if i["watched"]]
    return provider


for _n in (1, 2):
    row(f"genre_{_n}", lambda ctx, items, n=_n: genre_title(ctx.genre_name[n]), "poster", min_items=GENRE_MIN)(_genre_provider(_n))
