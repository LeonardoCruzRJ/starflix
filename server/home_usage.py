"""32.4: fileiras de uso do perfil (Em Cartaz, Novos episódios, Porque você assistiu, Mais Assistidos no Servidor)."""
from server import i18n
from server.db import display_title, get_db
from server.home_rows import poster_items, row

NEW_EP_DAYS = 14
TOP_DAYS = 30
RESUME_MIN = 5  # igual a progress.RESUME_MIN


def _show_libs(ctx):
    return [i for i, t in ctx.libs.items() if t == "show"]


@row("on_deck", "home.row.on_deck")
def on_deck(ctx):
    """Próximo episódio de cada série em andamento (último episódio assistido + 1, ainda não visto), pelo último assistido."""
    libs = _show_libs(ctx)
    if not libs:
        return []
    ql = ",".join("?" * len(libs))
    out, seen = [], set()
    with get_db() as conn:
        last = conn.execute(
            "SELECT e.id, e.media_id, e.season, e.episode, e.path FROM progress p JOIN episodes e ON e.id = p.item_id "
            f"JOIN media m ON m.id = e.media_id WHERE p.profile_id = ? AND p.item_type = 'episode' AND p.watched = 1 AND m.library_id IN ({ql}) "
            "ORDER BY p.updated_at DESC, p.rowid DESC", (ctx.profile_id, *libs)).fetchall()
        for l in last:
            mid = l["media_id"]
            if mid in seen:
                continue
            seen.add(mid)
            if conn.execute(  # episódio em andamento já aparece em "Continue assistindo"
                "SELECT 1 FROM progress p JOIN episodes e ON e.id = p.item_id WHERE p.profile_id = ? AND p.item_type = 'episode' "
                "AND p.watched = 0 AND p.position > ? AND e.media_id = ?", (ctx.profile_id, RESUME_MIN, mid)).fetchone():
                continue
            n = conn.execute(
                "SELECT e.id, e.season, e.episode, e.title FROM episodes e "
                "LEFT JOIN progress p ON p.profile_id = ? AND p.item_type = 'episode' AND p.item_id = e.id "
                "WHERE e.media_id = ? AND (e.season > ? OR (e.season = ? AND e.episode > ?)) AND e.path != ? "
                "AND COALESCE(p.watched, 0) = 0 ORDER BY e.season, e.episode LIMIT 1",
                (ctx.profile_id, mid, l["season"], l["season"], l["episode"], l["path"])).fetchone()
            if not n:
                continue
            m = conn.execute("SELECT library_id, title, original_title, year FROM media WHERE id = ?", (mid,)).fetchone()
            tot, seen_n = conn.execute(  # barra do pôster: episódios assistidos da série (como na referência 118)
                "SELECT COUNT(*), COALESCE(SUM(COALESCE(p.watched, 0)), 0) FROM episodes e LEFT JOIN progress p ON p.profile_id = ? "
                "AND p.item_type = 'episode' AND p.item_id = e.id WHERE e.media_id = ?", (ctx.profile_id, mid)).fetchone()
            out.append({"uid": f"m:{mid}", "id": mid, "type": "show", "title": display_title(m["library_id"], m["title"], m["original_title"]),
                        "year": m["year"], "lib": m["library_id"], "season": n["season"], "episode": n["episode"], "ep_title": n["title"], "episode_id": n["id"],
                        "still": f"/still/{n['id']}", "pct": max(1, int(seen_n * 100 / tot)) if tot else 0, "watched": False})
    return out


@row("new_episodes", "home.row.new_episodes")
def new_episodes(ctx):
    """Séries que o perfil já assistiu e que ganharam episódio (ainda não visto) nos últimos 14 dias; mais recente primeiro."""
    libs = _show_libs(ctx)
    if not libs:
        return []
    ql = ",".join("?" * len(libs))
    with get_db() as conn:
        rows = conn.execute(
            "SELECT m.id, COUNT(*) AS n, MAX(e.added_at) AS last FROM episodes e JOIN media m ON m.id = e.media_id "
            f"LEFT JOIN progress me ON me.profile_id = ? AND me.item_type = 'episode' AND me.item_id = e.id "
            f"WHERE m.library_id IN ({ql}) AND e.added_at >= datetime('now', ?) AND COALESCE(me.watched, 0) = 0 "
            "AND EXISTS (SELECT 1 FROM episodes e2 JOIN progress p ON p.item_type = 'episode' AND p.item_id = e2.id AND p.profile_id = ? "
            "WHERE e2.media_id = m.id AND (p.watched = 1 OR p.position > ?) AND e2.added_at < e.added_at) "
            "GROUP BY m.id ORDER BY last DESC, m.id DESC",
            (ctx.profile_id, *libs, f"-{NEW_EP_DAYS} days", ctx.profile_id, RESUME_MIN)).fetchall()
        items = poster_items(conn, ctx, [r["id"] for r in rows])
    count = {r["id"]: r["n"] for r in rows}
    return [dict(i, new=count[i["id"]]) for i in items]


@row("because_watched", lambda ctx, items: i18n.tr("home.row.because", name=ctx.because))
def because_watched(ctx):
    """Relacionados do TMDB (tabela `related`, 23.17) do último item concluído; só o que existe no servidor."""
    with get_db() as conn:
        done = conn.execute(
            "SELECT p.item_type, p.item_id FROM progress p WHERE p.profile_id = ? AND p.watched = 1 ORDER BY p.updated_at DESC, p.rowid DESC LIMIT 30",
            (ctx.profile_id,)).fetchall()
        tried = set()
        for d in done:
            if d["item_type"] == "movie":
                src = d["item_id"]
            else:
                e = conn.execute("SELECT media_id FROM episodes WHERE id = ?", (d["item_id"],)).fetchone()
                src = e["media_id"] if e else None
            if src is None or src in tried:
                continue
            tried.add(src)
            if len(tried) > 5:
                break
            m = conn.execute("SELECT library_id, title, original_title FROM media WHERE id = ?", (src,)).fetchone()
            if not m or m["library_id"] not in ctx.libs:
                continue
            ids = [r["id"] for r in conn.execute(
                "SELECT m.id FROM related r JOIN media m ON m.tmdb_id = r.tmdb_id WHERE r.media_id = ? AND m.id != ? "
                "ORDER BY r.ord, m.id", (src, src))]
            items = poster_items(conn, ctx, ids)
            if items:
                ctx.because = display_title(m["library_id"], m["title"], m["original_title"])
                return items
    return []


@row("top_server", "home.row.top_server")
def top_server(ctx):
    """Reproduções (todos os perfis) nos últimos 30 dias; episódios contam para a série."""
    if not ctx.libs:
        return []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT mid, COUNT(*) AS n, MAX(u) AS last FROM ("
            " SELECT p.item_id AS mid, p.updated_at AS u FROM progress p WHERE p.item_type = 'movie' AND (p.watched = 1 OR p.position > ?) "
            "  AND p.updated_at >= datetime('now', ?)"
            " UNION ALL"
            " SELECT e.media_id, p.updated_at FROM progress p JOIN episodes e ON e.id = p.item_id WHERE p.item_type = 'episode' "
            "  AND (p.watched = 1 OR p.position > ?) AND p.updated_at >= datetime('now', ?)"
            ") GROUP BY mid ORDER BY n DESC, last DESC, mid DESC LIMIT 60",
            (RESUME_MIN, f"-{TOP_DAYS} days", RESUME_MIN, f"-{TOP_DAYS} days")).fetchall()
        return poster_items(conn, ctx, [r["mid"] for r in rows])
