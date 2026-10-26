import math

from flask import Blueprint, abort, jsonify, render_template, request, session

from server.auth import login_required
from server.db import display_title, get_db, lib_prefs
from server.libraries import can_access, visible_libraries

bp = Blueprint("mylist", __name__)

STAR_KINDS = ("movie", "show", "season", "episode", "collection")


def _media_ok(conn, mid):
    m = conn.execute("SELECT library_id FROM media WHERE id = ?", (mid,)).fetchone()
    if not m or not can_access(session["user_id"], m["library_id"]):
        abort(404)


def in_list(mid):
    with get_db() as conn:
        return bool(conn.execute(
            "SELECT 1 FROM my_list WHERE profile_id = ? AND media_id = ?", (session["profile_id"], mid)
        ).fetchone())


def get_stars(kind, item_id):
    """Avaliação do perfil atual (0–10, meia estrela = 1)."""
    with get_db() as conn:
        r = conn.execute(
            "SELECT stars FROM stars WHERE profile_id = ? AND item_type = ? AND item_id = ?",
            (session["profile_id"], kind, item_id),
        ).fetchone()
    return r["stars"] if r else 0


def my_list_items(pid, user_id, home=False):
    """Itens da Minha Lista do perfil (só de bibliotecas liberadas), mais recentes primeiro."""
    libs = {l["id"]: l["type"] for l in visible_libraries(user_id) if not home or lib_prefs(l)["visibility"] == "all"}  # 28.6
    if not libs:
        return []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT m.id, m.title, m.original_title, m.year, m.library_id, COALESCE(p.watched, 0) AS seen FROM my_list l "
            "JOIN media m ON m.id = l.media_id "
            "LEFT JOIN progress p ON p.profile_id = l.profile_id AND p.item_type = 'movie' AND p.item_id = m.id "
            "WHERE l.profile_id = ? ORDER BY l.added_at DESC, m.id DESC",
            (pid,),
        ).fetchall()
    return [
        {"id": r["id"], "title": display_title(r["library_id"], r["title"], r["original_title"]), "year": r["year"], "type": libs[r["library_id"]], "lib": r["library_id"],
         "watched": bool(r["seen"]) and libs[r["library_id"]] == "movie"}
        for r in rows if r["library_id"] in libs
    ]


@bp.route("/mylist")
@login_required
def page():
    """56.2: página Minha Lista (link \"Minhas Listas\" do painel lateral)."""
    items = my_list_items(session["profile_id"], session["user_id"])
    return render_template("mylist.html", items=items)


@bp.route("/list/<int:mid>", methods=["POST", "DELETE"])
@login_required
def toggle(mid):
    with get_db() as conn:
        _media_ok(conn, mid)
        if request.method == "POST":
            conn.execute("INSERT OR IGNORE INTO my_list (profile_id, media_id) VALUES (?, ?)", (session["profile_id"], mid))
        else:
            conn.execute("DELETE FROM my_list WHERE profile_id = ? AND media_id = ?", (session["profile_id"], mid))
    return jsonify(ok=True, on=request.method == "POST")


@bp.route("/stars/<kind>/<int:item_id>", methods=["POST"])
@login_required
def set_stars(kind, item_id):
    if kind not in STAR_KINDS:
        abort(404)
    j = request.get_json(force=True, silent=True)
    try:
        v = float((j if isinstance(j, dict) else request.form).get("stars"))
    except (TypeError, ValueError):
        abort(400)
    if not math.isfinite(v) or v != int(v) or not 0 <= v <= 10:
        abort(400)
    v = int(v)
    with get_db() as conn:
        if kind in ("movie", "show"):
            _media_ok(conn, item_id)
        elif kind == "collection":
            r = conn.execute("SELECT library_id FROM collections WHERE id = ?", (item_id,)).fetchone()
            if not r or not can_access(session["user_id"], r["library_id"]):
                abort(404)
        else:
            table = "seasons s JOIN media m ON m.id = s.media_id" if kind == "season" else "episodes s JOIN media m ON m.id = s.media_id"
            r = conn.execute(f"SELECT m.library_id FROM {table} WHERE s.id = ?", (item_id,)).fetchone()
            if not r or not can_access(session["user_id"], r["library_id"]):
                abort(404)
        if v == 0:
            conn.execute("DELETE FROM stars WHERE profile_id = ? AND item_type = ? AND item_id = ?",
                         (session["profile_id"], kind, item_id))
        else:
            conn.execute(
                "INSERT INTO stars (profile_id, item_type, item_id, stars) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(profile_id, item_type, item_id) DO UPDATE SET stars = excluded.stars",
                (session["profile_id"], kind, item_id, v),
            )
    return jsonify(ok=True, stars=v)
