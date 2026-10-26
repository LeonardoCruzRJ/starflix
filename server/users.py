import os
import re

import config
from flask import Blueprint, abort, jsonify, redirect, render_template, request, session
from werkzeug.security import generate_password_hash

from server.auth import admin_required
from server.db import get_db
from server.library_access import set_user_libraries
from server.i18n import E, jerr

bp = Blueprint("users", __name__)


def _json():
    """Chamadas da página de usuários (JSON); os formulários antigos seguem funcionando."""
    return request.is_json or request.args.get("json") == "1"


def _user_json(conn, uid):
    u = conn.execute("SELECT id, username, full_name, is_admin FROM users WHERE id = ?", (uid,)).fetchone()
    n = conn.execute("SELECT COUNT(*) FROM user_libraries WHERE user_id = ?", (uid,)).fetchone()[0]
    return {"id": u["id"], "username": u["username"], "full_name": u["full_name"] or "", "is_admin": bool(u["is_admin"]), "libraries": n}


def _create(conn, username, password, is_admin):
    """Cria o usuário; devolve (erro, id)."""
    if not username or len(password) < 4:
        return E("err.informe_usuario_senha_minimo_4"), None
    if conn.execute("SELECT 1 FROM users WHERE casefold(username) = casefold(?)", (username,)).fetchone():
        return E("err.usuario_ja_existe"), None
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
        (username, generate_password_hash(password), is_admin),
    )
    return None, cur.lastrowid


@bp.route("/admin/users", methods=["GET", "POST"])
@admin_required
def users():
    error = None
    if request.method == "POST":
        if _json():
            d = request.get_json(silent=True) or {}
            username = str(d.get("username", "")).strip()
            password = str(d.get("password", ""))
            with get_db() as conn:
                error, uid = _create(conn, username, password, 1 if d.get("is_admin") else 0)
                if error:
                    return jerr(error, 400)
                return jsonify(user=_user_json(conn, uid)), 201
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        is_admin = 1 if request.form.get("is_admin") else 0
        with get_db() as conn:
            error, _ = _create(conn, username, password, is_admin)
    return render_template("admin_users.html", me=session["user_id"], error=error)


@bp.route("/admin/users/data")
@admin_required
def users_data():
    """Lista da página Usuários: contas, se são administradoras e quantas bibliotecas cada uma acessa."""
    with get_db() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM users ORDER BY fold(username), id")]
        rows = [_user_json(conn, i) for i in ids]
    return jsonify(me=session["user_id"], users=rows)


@bp.route("/admin/users/<int:uid>/edit", methods=["POST"])
@admin_required
def edit(uid):
    if _json():
        d = request.get_json(silent=True) or {}
        password = str(d.get("password", ""))
        if password and len(password) < 4:
            return jerr("err.senha_deve_ter_pelo_menos", 400)
        with get_db() as conn:
            if not conn.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
                return jerr("err.usuario_nao_encontrado", 404)
            if password:
                conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(password), uid))
            if "is_admin" in d and uid != session["user_id"]:
                conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if d.get("is_admin") else 0, uid))
            return jsonify(user=_user_json(conn, uid))
    password = request.form.get("password", "")
    if password and len(password) < 4:
        abort(400)
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
            abort(404)
        if password:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(password), uid))
        if uid != session["user_id"]:
            conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if request.form.get("is_admin") else 0, uid))
    return redirect("/admin/users")


@bp.route("/admin/users/<int:uid>/delete", methods=["POST"])
@admin_required
def delete(uid):
    if _json():
        if uid == session["user_id"]:
            return jerr("err.voce_nao_pode_remover_propria", 400)
        with get_db() as conn:
            if not conn.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
                return jerr("err.usuario_nao_encontrado", 404)
    if uid != session["user_id"]:
        with get_db() as conn:
            u = conn.execute("SELECT avatar FROM users WHERE id = ?", (uid,)).fetchone()
            photos = [r["photo"] for r in conn.execute("SELECT photo FROM profiles WHERE user_id = ? AND photo IS NOT NULL", (uid,))]  # 44.1: foto é do perfil
            conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        for name in ([u["avatar"]] if u and u["avatar"] else []) + photos:  # 26.1: apaga as fotos do usuário removido (a antiga da conta e as dos perfis)
            try:
                os.remove(os.path.join(config.AVATARS_DIR, os.path.basename(name)))
            except OSError:
                pass
    if _json():
        return jsonify(ok=True)
    return redirect("/admin/users")


@bp.route("/admin/users/<int:uid>/access", methods=["GET", "POST"])
@admin_required
def access(uid):
    """Rota antiga (27.4): GET abre o modal em /admin/access; POST segue gravando o conjunto de bibliotecas."""
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
            abort(404)
        if request.method == "POST":
            ids = [int(i) for i in request.form.getlist("library") if re.fullmatch(r"[0-9]{1,18}", i)]
            set_user_libraries(conn, uid, ids)
            return redirect("/admin/users")
    return redirect(f"/admin/access?user={uid}")
