import json
import os
import subprocess
import threading
from xml.sax.saxutils import escape

from flask import Blueprint, Response, abort, request, send_from_directory, session

import config
from server.auth import login_required
from server.db import get_db
from server.libraries import _placeholder, can_access

bp = Blueprint("images", __name__)


def _local(name):
    """Arquivo local em data/posters (relativo, sem sair da pasta); remoto '/...' ou ausente = None."""
    if not name or name.startswith("/"):
        return None
    rel = os.path.normpath(name)
    if os.path.isabs(rel) or rel.startswith(".."):
        return None
    folder = os.path.abspath(config.POSTERS_DIR)
    return (folder, rel) if os.path.isfile(os.path.join(folder, rel)) else None


def _send(name, max_age=0):
    f = _local(name)
    return send_from_directory(f[0], f[1], max_age=max_age) if f else None  # ETag/Last-Modified revalidam


def _media(mid):
    with get_db() as conn:
        m = conn.execute(
            "SELECT library_id, title, poster, backdrop, logo, square FROM media WHERE id = ?", (mid,)
        ).fetchone()
    if not m or not can_access(session["user_id"], m["library_id"]):
        abort(404)
    return m


@bp.route("/backdrop/<int:mid>")
@login_required
def backdrop(mid):
    return _send(_media(mid)["backdrop"]) or abort(404)  # sem imagem: a página não mostra o bloco


@bp.route("/logo/<int:mid>")
@login_required
def logo(mid):
    return _send(_media(mid)["logo"]) or abort(404)


@bp.route("/square/<int:mid>")
@login_required
def square(mid):
    m = _media(mid)
    # sem arte quadrada própria: usa o pôster (a interface recorta com CSS) e, sem ele, o placeholder
    return _send(m["square"]) or _send(m["poster"]) or _placeholder(m["title"])


@bp.route("/person/<int:pid>")
@login_required
def person(pid):
    with get_db() as conn:
        p = conn.execute("SELECT name, photo, photo_big FROM people WHERE id = ?", (pid,)).fetchone()
        libs = [r["library_id"] for r in conn.execute(
            "SELECT DISTINCT m.library_id FROM credits c JOIN media m ON m.id = c.media_id WHERE c.person_id = ?", (pid,)
        )]
    if not p or not any(can_access(session["user_id"], lid) for lid in libs):
        abort(404)
    r = (_send(p["photo_big"], max_age=604800) if request.args.get("big") else None) or _send(p["photo"], max_age=604800)
    if r:
        return r
    name = (p["name"] or "?").strip() or "?"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><rect width="120" height="120" fill="#2a2a2a"/>'
        '<text x="60" y="78" font-family="sans-serif" font-size="52" font-weight="bold" fill="#9b9b9b" '
        f'text-anchor="middle">{escape(name[0].upper())}</text></svg>'
    )
    return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "private, max-age=300"})


@bp.route("/season-poster/<int:mid>/<int:n>")
@login_required
def season_poster(mid, n):
    m = _media(mid)
    with get_db() as conn:
        sr = conn.execute("SELECT poster FROM seasons WHERE media_id = ? AND season = ?", (mid, n)).fetchone()
    # sem pôster da temporada: usa o da série e, sem ele, o placeholder
    return (sr and _send(sr["poster"])) or _send(m["poster"]) or _placeholder(m["title"])


_frame_lock = threading.Lock()  # um ffmpeg de frame por vez (evita sobrecarregar NAS/CPU)


def _make_frame(e, rel=None):
    """Gera um frame a ~10 % da duração em data/posters/still/<id>.jpg; devolve o caminho relativo ou None."""
    rel = rel or f"still/{e['id']}.jpg"
    out = os.path.join(os.path.abspath(config.POSTERS_DIR), rel)
    try:
        dur = float((json.loads(e["info"]) if e["info"] else {}).get("duration") or 0)
    except (ValueError, TypeError, AttributeError):
        dur = 0
    if not os.path.exists(e["path"]):
        return None
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = f"{out}.{os.getpid()}.{threading.get_ident()}.tmp.jpg"
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", str(int(dur * 0.1)), "-i", e["path"],
             "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", tmp],
            capture_output=True, timeout=45,
        )
        if r.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            return None
        os.replace(tmp, out)
        return rel
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


@bp.route("/still/<int:eid>")
@login_required
def still(eid):
    with get_db() as conn:
        e = conn.execute(
            "SELECT e.id, e.path, e.info, e.still, m.library_id FROM episodes e JOIN media m ON m.id = e.media_id WHERE e.id = ?",
            (eid,),
        ).fetchone()
    if not e or not can_access(session["user_id"], e["library_id"]):
        abort(404)
    r = _send(e["still"])
    if r:
        return r
    rel = f"still/{eid}.jpg"
    if e["still"] is None or e["still"].startswith("/"):
        abort(404)  # TMDB ainda não consultado/baixado: sem imagem por enquanto (placeholder 16:9 na página)
    with _frame_lock:
        if not _local(rel):
            rel = _make_frame(e)
    if not rel:
        abort(404)
    with get_db() as conn:
        conn.execute("UPDATE episodes SET still = ? WHERE id = ? AND (still = '' OR still IS NULL)", (rel, eid))
    return _send(rel) or abort(404)


@bp.route("/thumb/<int:mid>")
@login_required
def thumb(mid):
    """34.3: miniatura 16:9 de item `video` = frame do arquivo (cache em data/posters/still/v<id>.jpg, fallback placeholder)."""
    with get_db() as conn:
        m = conn.execute(
            "SELECT m.id, m.title, m.path, m.info, m.poster, m.library_id, l.type FROM media m "
            "JOIN libraries l ON l.id = m.library_id WHERE m.id = ?", (mid,)
        ).fetchone()
    if not m or m["type"] != "video" or not can_access(session["user_id"], m["library_id"]):
        abort(404)
    r = _send(m["poster"])
    if r:
        return r
    rel = f"still/v{mid}.jpg"
    with _frame_lock:
        if not _local(rel):
            rel = _make_frame(m, rel)
    if not rel:
        return _placeholder(m["title"])
    with get_db() as conn:
        conn.execute("UPDATE media SET poster = ? WHERE id = ? AND (poster = '' OR poster IS NULL)", (rel, mid))
    return _send(rel) or _placeholder(m["title"])
