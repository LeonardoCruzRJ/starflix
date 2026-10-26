import os
import secrets

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session

from server.auth import login_required
from server.db import get_db
from server.i18n import jerr

bp = Blueprint("profiles", __name__)

COLORS = ["#e5a00d", "#e74c3c", "#3498db", "#2ecc71", "#9b59b6", "#1abc9c"]


def _own(conn, pid):
    p = conn.execute(
        "SELECT * FROM profiles WHERE id = ? AND user_id = ?", (pid, session["user_id"])
    ).fetchone()
    if not p:
        abort(404)
    return p


@bp.route("/profiles")
@login_required
def list_profiles():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM profiles WHERE user_id = ? ORDER BY fold(name), id", (session["user_id"],)
        ).fetchall()
    from server.account import profile_photo_url
    rows = [dict(r, photo_url=profile_photo_url(r["id"], r["photo"])) for r in rows]
    return render_template("profiles.html", profiles=rows, colors=COLORS, manage=(request.args.get("manage") == "1" or not rows),
                           can_back=bool(session.get("profile_id")))


@bp.route("/profiles/new", methods=["GET"])
@login_required
def new_page():
    """Tela de criação (54.23): nome + foto, Salvar no rodapé."""
    return render_template("profile_new.html")


@bp.route("/profiles/create", methods=["POST"])
@login_required
def create():
    d = request.get_json(silent=True)
    name = " ".join(str(d.get("name", "")).split())[:30].strip() if isinstance(d, dict) else ""
    if not name:
        return jerr("err.digite_nome", 400)
    with get_db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM profiles WHERE user_id = ?", (session["user_id"],)).fetchone()[0]
        cur = conn.execute("INSERT INTO profiles (user_id, name, avatar) VALUES (?, ?, ?)", (session["user_id"], name, COLORS[n % len(COLORS)]))
        pid = cur.lastrowid
    return jsonify(ok=True, id=pid)


@bp.route("/profiles/<int:pid>/edit")
@login_required
def edit(pid):
    """Mesma tela de Editar perfil, aberta para um perfil da lista (54.23)."""
    from server.account import render_profile_edit
    with get_db() as conn:
        p = _own(conn, pid)
    return render_profile_edit(p)


@bp.route("/profiles/<int:pid>/name", methods=["POST"])
@login_required
def rename(pid):
    d = request.get_json(silent=True)
    name = " ".join(str(d.get("value", "")).split())[:30].strip() if isinstance(d, dict) else ""
    if not name:
        return jerr("err.digite_nome", 400)
    with get_db() as conn:
        _own(conn, pid)
        conn.execute("UPDATE profiles SET name = ? WHERE id = ?", (name, pid))
    return jsonify(ok=True, value=name)


@bp.route("/profiles/<int:pid>/avatar", methods=["POST", "DELETE"])
@login_required
def avatar(pid):
    from server.account import profile_photo_url, _remove_avatar_file
    from server.admin_edit import MAX_IMG, _sniff
    import config
    with get_db() as conn:
        old = _own(conn, pid)
    if request.method == "DELETE":
        with get_db() as conn:
            conn.execute("UPDATE profiles SET photo = NULL WHERE id = ?", (pid,))
        _remove_avatar_file(old["photo"])
        return jsonify(ok=True)
    f = request.files.get("file")
    if not f:
        return jerr("err.escolha_foto", 400)
    data = f.read(MAX_IMG + 1)
    if len(data) > MAX_IMG:
        return jerr("err.imagem_maior_que_10_mb", 400)
    ext = _sniff(data)
    if not ext:
        return jerr("err.use_jpg_png_ou_webp", 400)
    name = f"p{pid}-{secrets.token_hex(4)}{ext}"
    os.makedirs(config.AVATARS_DIR, exist_ok=True)
    with open(os.path.join(config.AVATARS_DIR, name), "wb") as fh:
        fh.write(data)
    with get_db() as conn:
        conn.execute("UPDATE profiles SET photo = ? WHERE id = ?", (name, pid))
    _remove_avatar_file(old["photo"])
    return jsonify(ok=True, url=profile_photo_url(pid, name))


@bp.route("/profiles/new", methods=["POST"])
@login_required
def new():
    name = request.form.get("name", "").strip()[:30].strip()
    color = request.form.get("avatar", COLORS[0])
    if name:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO profiles (user_id, name, avatar) VALUES (?, ?, ?)",
                (session["user_id"], name, color if color in COLORS else COLORS[0]),
            )
    return redirect("/profiles")


@bp.route("/profiles/<int:pid>/select", methods=["POST"])
@login_required
def select(pid):
    with get_db() as conn:
        _own(conn, pid)
    session["profile_id"] = pid
    return redirect("/")


@bp.route("/profiles/<int:pid>/delete", methods=["POST"])
@login_required
def delete(pid):
    with get_db() as conn:
        old = _own(conn, pid)
        if conn.execute("SELECT is_admin FROM users WHERE id = ?", (session["user_id"],)).fetchone()["is_admin"]:
            abort(403)  # 54.24: administrador não exclui perfil
        conn.execute("DELETE FROM profiles WHERE id = ?", (pid,))
    from server.account import _remove_avatar_file
    _remove_avatar_file(old["photo"])
    if session.get("profile_id") == pid:
        session.pop("profile_id")
    return redirect("/profiles")
