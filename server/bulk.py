"""Ações em lote da seleção múltipla (24.4): POST /bulk/<ação> com {"ids": [media_id, ...]}."""
import json
import threading

from flask import Blueprint, abort, current_app, jsonify, request, session

from server import probe as probe_mod
from server.admin_edit import _scope, item_delete
from server.admin_media import do_match
from server.auth import login_required
from server.collections import _int_list
from server.db import get_db
from server.libraries import visible_libraries
from server.i18n import jerr

bp = Blueprint("bulk", __name__)

ADMIN_ACTIONS = ("analyze", "refresh", "delete")
ACTIONS = ("watched", "list", "unresume") + ADMIN_ACTIONS


def _is_admin():
    with get_db() as conn:
        u = conn.execute("SELECT is_admin FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return bool(u and u["is_admin"])


def _items(ids):
    """[(kind, media_id)] só dos ids que existem e de bibliotecas liberadas ao usuário."""
    libs = {l["id"]: l["type"] for l in visible_libraries(session["user_id"])}
    if not ids or not libs:
        return []
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT id, library_id FROM media WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
    found = {r["id"]: libs.get(r["library_id"]) for r in rows}
    return [("movie" if found[i] == "movie" else "show", i) for i in ids if found.get(i)]


def _progress_rows(conn, items):
    """[(item_type, item_id)] de progresso: o próprio filme ou todos os episódios da série."""
    out = []
    for kind, mid in items:
        if kind == "movie":
            out.append(("movie", mid))
        else:
            out += [("episode", r["id"]) for r in conn.execute("SELECT id FROM episodes WHERE media_id = ?", (mid,))]
    return out


def _analyze(items):
    for kind, mid in items:
        try:
            with get_db() as conn:
                _, files = _scope(conn, kind, str(mid))
        except Exception:
            continue
        for table, id_, path in files:
            try:
                info = probe_mod.probe(path)
            except Exception:
                info = None
            if info:
                with get_db() as conn:
                    conn.execute(f"UPDATE {table} SET info = ? WHERE id = ?", (json.dumps(info), id_))


def _refresh(app, pairs):
    with app.app_context():
        for mid, tmdb_id in pairs:
            try:
                do_match(mid, tmdb_id)
            except Exception:
                continue


QUEUE_MAX = 200  # igual ao limite de js/queue.js


@bp.route("/bulk/queue", methods=["POST"])
@login_required
def queue_items():
    """31.9: itens reproduzíveis para a fila (filme = ele mesmo; série = episódios na ordem, especiais por último,
    um por arquivo). Devolve [{k, id}] só de bibliotecas liberadas, até QUEUE_MAX."""
    j = request.get_json(silent=True)
    j = j if isinstance(j, dict) else {}
    out = []
    with get_db() as conn:
        for kind, mid in _items(_int_list(j.get("ids"))):
            if kind == "movie":
                out.append({"k": "movie", "id": mid})
                continue
            seen = set()
            for e in conn.execute("SELECT id, path FROM episodes WHERE media_id = ? ORDER BY season = 0, season, episode, id", (mid,)):
                if e["path"] in seen:  # arquivo de vários episódios (S01E01E02) entra uma vez
                    continue
                seen.add(e["path"])
                out.append({"k": "episode", "id": e["id"]})
            if len(out) >= QUEUE_MAX:
                break
    return jsonify(items=out[:QUEUE_MAX], n=len(out[:QUEUE_MAX]))


@bp.route("/bulk/<action>", methods=["POST"])
@login_required
def bulk(action):
    if action not in ACTIONS:
        abort(404)
    if action in ADMIN_ACTIONS and not _is_admin():
        abort(403)
    j = request.get_json(silent=True)
    j = j if isinstance(j, dict) else {}
    items = _items(_int_list(j.get("ids")))
    if not items:
        abort(404)
    pid = session["profile_id"]

    if action == "watched":
        flag = 1 if j.get("watched", True) else 0
        with get_db() as conn:
            conn.executemany(
                "INSERT INTO progress (profile_id, item_type, item_id, position, watched) VALUES (?, ?, ?, 0, ?) "
                "ON CONFLICT(profile_id, item_type, item_id) DO UPDATE SET position = 0, watched = excluded.watched, "
                "updated_at = CURRENT_TIMESTAMP",
                [(pid, t, i, flag) for t, i in _progress_rows(conn, items)])
        return jsonify(ok=True, n=len(items), watched=bool(flag))

    if action == "list":
        mids = [m for _, m in items]
        marks = ",".join("?" * len(mids))
        with get_db() as conn:
            have = {r["media_id"] for r in conn.execute(
                f"SELECT media_id FROM my_list WHERE profile_id = ? AND media_id IN ({marks})", (pid, *mids))}
            on = len(have) < len(mids)  # todos já na lista → remove; senão adiciona
            if on:
                conn.executemany("INSERT OR IGNORE INTO my_list (profile_id, media_id) VALUES (?, ?)",
                                 [(pid, m) for m in mids])
            else:
                conn.execute(f"DELETE FROM my_list WHERE profile_id = ? AND media_id IN ({marks})", (pid, *mids))
        return jsonify(ok=True, n=len(mids), on=on)

    if action == "unresume":  # Remover de Continuar Assistindo: zera a posição dos não terminados
        with get_db() as conn:
            conn.executemany(
                "UPDATE progress SET position = 0, updated_at = CURRENT_TIMESTAMP "
                "WHERE profile_id = ? AND item_type = ? AND item_id = ? AND watched = 0 AND position > 0",
                [(pid, t, i) for t, i in _progress_rows(conn, items)])
        return jsonify(ok=True, n=len(items))

    if action == "analyze":
        threading.Thread(target=_analyze, args=(items,), daemon=True).start()
        return jsonify(ok=True, n=len(items))

    if action == "refresh":
        with get_db() as conn:
            pairs = [(m, r["tmdb_id"]) for _, m in items
                     for r in [conn.execute("SELECT tmdb_id FROM media WHERE id = ?", (m,)).fetchone()] if r and r["tmdb_id"]]
        if not pairs:
            return jerr("err.nenhum_item_selecionado_tem_correspondencia", 400)
        threading.Thread(target=_refresh, args=(current_app._get_current_object(), pairs), daemon=True).start()
        return jsonify(ok=True, n=len(pairs))

    for kind, mid in items:  # delete
        item_delete(kind, str(mid))
    return jsonify(ok=True, n=len(items))
