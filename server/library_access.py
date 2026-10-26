import re

from flask import Blueprint, abort, jsonify, render_template, request

from server.auth import admin_required
from server.db import get_db
from server.i18n import jerr

bp = Blueprint("library_access", __name__)

SERVER_NAME = "StarFlix"
MAX_IDS = 1000


def grant_library(conn, uid, lid):
    """Libera uma biblioteca a um usuário (ignora se já liberada ou se a biblioteca não existe)."""
    conn.execute(
        "INSERT OR IGNORE INTO user_libraries (user_id, library_id) SELECT ?, id FROM libraries WHERE id = ?",
        (uid, lid),
    )


def set_user_libraries(conn, uid, ids):
    """Troca o conjunto de bibliotecas do usuário (ids inexistentes são ignorados)."""
    conn.execute("DELETE FROM user_libraries WHERE user_id = ?", (uid,))
    for lid in ids:
        grant_library(conn, uid, lid)


def parse_ids(raw):
    """Aceita só inteiros ou strings [0-9]+; devolve lista sem repetição, ou None se inválida."""
    if not isinstance(raw, list) or len(raw) > MAX_IDS:
        return None
    out = []
    for v in raw:
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            v = str(v)
        if not isinstance(v, str) or not re.fullmatch(r"[0-9]{1,18}", v):
            return None
        if int(v) not in out:
            out.append(int(v))
    return out


def _row(u, libs):
    return {"id": u["id"], "username": u["username"], "full_name": u["full_name"] or "", "libraries": libs}


def _user_libs(conn, uid):
    return [r[0] for r in conn.execute(
        "SELECT ul.library_id FROM user_libraries ul JOIN libraries l ON l.id = ul.library_id "
        "WHERE ul.user_id = ? ORDER BY fold(l.name), l.id", (uid,))]


def library_users(conn, lid):
    """Usuários não-admin para o modal de acesso de uma biblioteca (29.4): quem já tem acesso e as bibliotecas de cada um."""
    order = [r[0] for r in conn.execute("SELECT id FROM libraries ORDER BY fold(name), id")]
    access = {}
    for r in conn.execute("SELECT user_id, library_id FROM user_libraries"):
        access.setdefault(r["user_id"], set()).add(r["library_id"])
    out = []
    for u in conn.execute("SELECT id, username, full_name FROM users WHERE is_admin = 0 ORDER BY fold(username), id"):
        row = _row(u, [i for i in order if i in access.get(u["id"], ())])
        row["has_access"] = lid in access.get(u["id"], ())
        out.append(row)
    return out


@bp.route("/admin/access")
@admin_required
def page():
    """Página Gerenciar acesso à biblioteca (a lista é montada no navegador a partir de /admin/access/data)."""
    return render_template("admin_library_access.html")


@bp.route("/admin/access/data")
@admin_required
def data():
    """Dados da página Gerenciar acesso à biblioteca: servidor, bibliotecas e usuários não-admin com seus acessos."""
    with get_db() as conn:
        libs = [{"id": r["id"], "name": r["name"], "type": r["type"]} for r in conn.execute(
            "SELECT id, name, type FROM libraries ORDER BY fold(name), id")]
        access = {}
        for r in conn.execute("SELECT user_id, library_id FROM user_libraries"):
            access.setdefault(r["user_id"], set()).add(r["library_id"])
        order = [l["id"] for l in libs]
        users = [
            _row(u, [i for i in order if i in access.get(u["id"], ())])
            for u in conn.execute(
                "SELECT id, username, full_name FROM users WHERE is_admin = 0 ORDER BY fold(username), id")
        ]
    return jsonify(server=SERVER_NAME, libraries=libs, users=users)


@bp.route("/admin/access/user/<int:uid>", methods=["POST"])
@admin_required
def save(uid):
    """Substitui as bibliotecas liberadas ao usuário; devolve a linha atualizada."""
    body = request.get_json(silent=True)
    ids = parse_ids(body.get("libraries")) if isinstance(body, dict) else None
    if ids is None:
        return jerr("err.lista_bibliotecas_invalida", 400)
    with get_db() as conn:
        u = conn.execute("SELECT id, username, full_name, is_admin FROM users WHERE id = ?", (uid,)).fetchone()
        if not u:
            abort(404)
        if u["is_admin"]:
            return jerr("err.administradores_ja_acessam_todas_as", 400)
        set_user_libraries(conn, uid, ids)
        libs = _user_libs(conn, uid)
    return jsonify(ok=True, user=_row(u, libs))
