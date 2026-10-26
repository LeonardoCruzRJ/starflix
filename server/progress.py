import json
import math

from flask import Blueprint, abort, jsonify, request, session

from server.auth import login_required
from server.db import display_title, get_db, lib_prefs
from server.libraries import visible_libraries
from server.stream import get_item, warm_next

bp = Blueprint("progress", __name__)

SAVE_INTERVAL = 10  # segundos entre salvamentos (o player chama o endpoint nesse intervalo)
RESUME_MIN = 5  # segundos: abaixo disso não há "continuar" (o player também começa do zero)
WATCHED_RATIO = 0.9  # acima disso o item é marcado como assistido


def _data():
    j = request.get_json(force=True, silent=True)
    return j if isinstance(j, dict) else request.form  # corpo JSON que não é objeto (ex.: lista) não pode dar 500


def _number(value, required=True):
    try:
        n = float(value)
    except (TypeError, ValueError):
        if required:
            abort(400)
        return None
    if not math.isfinite(n) or n < 0:  # NaN e infinito (1e999) viram 400
        abort(400)
    return n


def _same_file(conn, kind, item_id):
    """Ids do item e dos demais episódios do mesmo arquivo (S01E01E02 grava duas linhas para um arquivo)."""
    if kind != "episode":
        return [item_id]
    rows = conn.execute(
        "SELECT id FROM episodes WHERE path = (SELECT path FROM episodes WHERE id = ?)", (item_id,)
    ).fetchall()
    return [r["id"] for r in rows] or [item_id]


def next_episode(episode_id):
    """Próximo episódio da mesma série (ordem temporada/episódio); None se for o último."""
    with get_db() as conn:
        cur = conn.execute("SELECT media_id, season, episode FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if not cur:
            return None
        n = conn.execute(
            "SELECT id, season, episode, title FROM episodes WHERE media_id = ? AND (season > ? OR (season = ? AND episode > ?)) "
            "AND path != (SELECT path FROM episodes WHERE id = ?) "  # S01E01E02: o próximo não pode ser o mesmo arquivo
            "ORDER BY season, episode LIMIT 1",
            (cur["media_id"], cur["season"], cur["season"], cur["episode"], episode_id),
        ).fetchone()
    if not n:
        return None
    return {
        "id": n["id"], "season": n["season"], "episode": n["episode"], "title": n["title"],
        "play": f"/stream/episode/{n['id']}/play",
    }


@bp.route("/next/episode/<int:item_id>")
@login_required
def next_ep(item_id):
    get_item("episode", item_id)  # valida acesso
    return jsonify(next=next_episode(item_id))


@bp.route("/progress/<kind>/<int:item_id>", methods=["GET"])
@login_required
def get_progress(kind, item_id):
    get_item(kind, item_id)  # valida acesso à biblioteca
    with get_db() as conn:
        r = conn.execute(
            "SELECT position, watched FROM progress WHERE profile_id = ? AND item_type = ? AND item_id = ?",
            (session["profile_id"], kind, item_id),
        ).fetchone()
    return jsonify(position=r["position"] if r else 0, watched=bool(r["watched"]) if r else False, interval=SAVE_INTERVAL)


@bp.route("/progress/<kind>/<int:item_id>", methods=["POST"])
@login_required
def save_progress(kind, item_id):
    """Salva a posição (segundos) do perfil atual; o player envia a cada SAVE_INTERVAL s."""
    _, info = get_item(kind, item_id)
    data = _data()
    pos = _number(data.get("position"))
    # a duração do ffprobe vale mais que a do cliente (em HLS o <video> só conhece o trecho já gerado)
    duration = (info or {}).get("duration") or _number(data.get("duration"), required=False) or 0
    done = duration > 0 and pos / duration > WATCHED_RATIO
    with get_db() as conn:
        if done:  # >90%: marca como assistido (inclusive os outros episódios do mesmo arquivo) e zera a posição
            for i in _same_file(conn, kind, item_id):
                conn.execute(
                    "INSERT INTO progress (profile_id, item_type, item_id, position, watched) VALUES (?, ?, ?, 0, 1) "
                    "ON CONFLICT(profile_id, item_type, item_id) DO UPDATE SET position = 0, watched = 1, "
                    "updated_at = CURRENT_TIMESTAMP",
                    (session["profile_id"], kind, i),
                )
        else:
            conn.execute(
                "INSERT INTO progress (profile_id, item_type, item_id, position) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(profile_id, item_type, item_id) DO UPDATE SET position = excluded.position, "
                "watched = CASE WHEN excluded.position > ? THEN 0 ELSE watched END, "
                "updated_at = CURRENT_TIMESTAMP",
                (session["profile_id"], kind, item_id, pos, RESUME_MIN),
            )
    if kind == "episode":
        warm_next(session["user_id"], item_id, pos, duration)  # 52.12: aquece o próximo episódio perto do fim (engole qualquer falha)
    nxt = next_episode(item_id) if done and kind == "episode" else None
    return jsonify(ok=True, position=0 if done else pos, watched=done, next=nxt)


@bp.route("/progress/<kind>/<int:item_id>/watched", methods=["POST"])
@login_required
def set_watched(kind, item_id):
    """Marca manualmente como assistido (watched=1, padrão) ou não assistido (watched=0); zera a posição."""
    get_item(kind, item_id)
    flag = str(_data().get("watched", 1)).lower() not in ("0", "false", "")
    with get_db() as conn:
        for i in _same_file(conn, kind, item_id):
            conn.execute(
                "INSERT INTO progress (profile_id, item_type, item_id, position, watched) VALUES (?, ?, ?, 0, ?) "
                "ON CONFLICT(profile_id, item_type, item_id) DO UPDATE SET position = 0, watched = excluded.watched, "
                "updated_at = CURRENT_TIMESTAMP",
                (session["profile_id"], kind, i, int(flag)),
            )
    return jsonify(ok=True, watched=flag)


def continue_watching(user_id, profile_id, limit=20, home=False):
    """Itens começados e não terminados do perfil, mais recentes primeiro (só bibliotecas liberadas;
    `home=True` tira as bibliotecas com visibilidade \"Excluir do Início\", 28.6)."""
    allowed = {l["id"] for l in visible_libraries(user_id) if not home or lib_prefs(l)["visibility"] == "all"}
    out = []
    shows = set()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT item_type, item_id, position, updated_at FROM progress "
            "WHERE profile_id = ? AND watched = 0 AND position > ? ORDER BY updated_at DESC, rowid DESC",
            (profile_id, RESUME_MIN),
        ).fetchall()
        for r in rows:
            if r["item_type"] == "movie":
                m = conn.execute(
                    "SELECT id, library_id, title, original_title, year, info FROM media WHERE id = ?", (r["item_id"],)
                ).fetchone()
                if not m:
                    continue
                item = {"kind": "movie", "id": m["id"], "media_id": m["id"], "lib": m["library_id"], "title": display_title(m["library_id"], m["title"], m["original_title"]), "year": m["year"]}
            else:
                m = conn.execute(
                    "SELECT m.id AS media_id, m.library_id, m.title AS show, m.original_title AS orig, e.id, e.season, e.episode, e.title, e.info "
                    "FROM episodes e JOIN media m ON m.id = e.media_id WHERE e.id = ?",
                    (r["item_id"],),
                ).fetchone()
                if not m:
                    continue
                item = {
                    "kind": "episode", "id": m["id"], "media_id": m["media_id"], "lib": m["library_id"], "show": display_title(m["library_id"], m["show"], m["orig"]),
                    "season": m["season"], "episode": m["episode"], "title": m["title"],
                }
            if m["library_id"] not in allowed:
                continue
            if item["kind"] == "episode":
                if item["media_id"] in shows:
                    continue
                shows.add(item["media_id"])
            try:
                duration = (json.loads(m["info"]) if m["info"] else {}).get("duration") or 0
            except ValueError:
                duration = 0
            item.update(
                position=r["position"], duration=duration, poster=f"/poster/{item['media_id']}",
                updated_at=r["updated_at"],
            )
            out.append(item)
            if len(out) >= limit:
                break
    return out


@bp.route("/continue")
@login_required
def continue_list():
    return jsonify(items=continue_watching(session["user_id"], session["profile_id"]))
