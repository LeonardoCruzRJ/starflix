import requests
from flask import Blueprint, abort, jsonify, render_template, request

import config
from server import metadata
from server.auth import admin_required
from server.db import get_db
from server.i18n import jerr

bp = Blueprint("admin_media", __name__)


@bp.route("/admin/tmdb-search")
@admin_required
def tmdb_search():
    if not config.TMDB_API_KEY:
        return jerr("err.chave_tmdb_nao_configurada_configuracoes", 400)
    kind = "movie" if request.args.get("type") == "movie" else "tv"
    params = {"query": request.args.get("q", "")}
    year = request.args.get("year", "").strip()
    if year.isdigit() and len(year) == 4:
        params["year" if kind == "movie" else "first_air_date_year"] = year
    try:
        results = metadata.tmdb_get(f"/search/{kind}", **params).get("results", [])
    except requests.RequestException:
        return jerr("err.falha_consultar_tmdb", 502)
    return jsonify(results=[
        {
            "id": r["id"],
            "title": r.get("title") or r.get("name"),
            "year": (r.get("release_date") or r.get("first_air_date") or "")[:4],
            "overview": (r.get("overview") or "")[:400],
            "poster": (metadata.TMDB_IMG + "w154" + r["poster_path"]) if r.get("poster_path") else None,
        }
        for r in results[:10]
    ])


@bp.route("/admin/media/<int:mid>/match-info")
@admin_required
def match_info(mid):
    """Dados do modal Corrigir Correspondência (25.5): local no disco e título/ano deduzidos do nome (Auto Corresponder)."""
    import os
    from server.scanner import _parse, parse_movie_name
    with get_db() as conn:
        m = conn.execute("SELECT m.title, m.year, m.path, l.type FROM media m JOIN libraries l ON l.id = m.library_id "
                         "WHERE m.id = ?", (mid,)).fetchone()
        if not m:
            abort(404)
        if m["type"] == "movie":
            path = m["path"] or ""
            auto = parse_movie_name(path) if path else (m["title"], m["year"])
        else:
            paths = [r["path"] for r in conn.execute("SELECT path FROM episodes WHERE media_id = ?", (mid,)).fetchall()]
            try:
                path = os.path.commonpath([os.path.dirname(p) for p in paths]) if paths else ""
            except ValueError:
                path = os.path.dirname(paths[0]) if paths else ""
            auto = _parse(os.path.basename(path)) if path else (m["title"], m["year"])
    return jsonify(kind=m["type"], title=m["title"], year=m["year"], path=path, auto={"title": auto[0], "year": auto[1]})


@bp.route("/admin/media/<int:mid>/match", methods=["POST"])
@admin_required
def match(mid):
    try:
        tmdb_id = int(request.form.get("tmdb_id", ""))
    except ValueError:
        abort(400)
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM media WHERE id = ?", (mid,)).fetchone():
            abort(404)
    return match_async(mid, tmdb_id)


def match_async(mid, tmdb_id):
    """35.16/35.19: aplica a correspondência em segundo plano (capa girando) e responde 202 na hora."""
    # 35.16: o modal fecha na hora; a correção roda em segundo plano e a capa gira até ficar pronta
    import threading
    from flask import current_app
    from server import scanstate
    app = current_app._get_current_object()
    scanstate.manual_start(mid)

    def job():
        try:
            with app.app_context():
                do_match(mid, tmdb_id)
        except Exception:
            import logging
            logging.getLogger("starflix.scan").exception("falha ao corrigir a correspondência do item %s", mid)
        finally:
            scanstate.manual_end(mid)

    threading.Thread(target=job, daemon=True).start()
    return jsonify(ok=True, pending=True), 202


def do_match(mid, tmdb_id):
    with get_db() as conn:
        lib = conn.execute("SELECT library_id FROM media WHERE id = ?", (mid,)).fetchone()
    if not lib:
        abort(404)
    with metadata.library_context(lib["library_id"]):  # idioma/país da biblioteca (28.4)
        return _do_match(mid, tmdb_id)


def _do_match(mid, tmdb_id):
    with get_db() as conn:
        m = conn.execute(
            "SELECT m.library_id, l.type FROM media m JOIN libraries l ON l.id = m.library_id WHERE m.id = ?",
            (mid,),
        ).fetchone()
    if not m:
        abort(404)
    is_movie = m["type"] == "movie"
    try:
        d = metadata.tmdb_details("movie" if is_movie else "tv", tmdb_id)
    except requests.RequestException:
        return jerr("err.falha_consultar_tmdb", 502)
    with get_db() as conn:
        if is_movie:
            metadata.apply_movie(conn, mid, d)
        else:
            conn.execute("DELETE FROM seasons WHERE media_id = ? AND locks IS NULL", (mid,))
            conn.execute("UPDATE episodes SET still = NULL, air_date = NULL, rating = NULL WHERE media_id = ? "
                         "AND (locks IS NULL OR locks NOT LIKE '%\"still\"%')", (mid,))
            metadata.apply_show(conn, mid, d)
            conn.execute("UPDATE media SET tvdb_id = NULL WHERE id = ?", (mid,))
            conn.execute("UPDATE episodes SET title = NULL, overview = NULL WHERE media_id = ?", (mid,))
    from server.dedupe import merge_movies, merge_shows  # 35.3/35.4: a correção pode igualar este item a outro já existente; o corrigido é o que fica
    (merge_movies if is_movie else merge_shows)(m["library_id"], prefer=mid)
    metadata.apply_local_art(m["library_id"], mid)
    metadata.download_posters(m["library_id"], mid)
    metadata.download_images(m["library_id"], mid)
    if not is_movie:
        metadata.identify_episodes(m["library_id"], mid)
        metadata.identify_seasons(m["library_id"], mid)
        metadata.download_images(m["library_id"], mid)
    return jsonify(ok=True)
