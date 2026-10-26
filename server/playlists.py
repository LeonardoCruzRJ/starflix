"""31.4: listas de reprodução (por usuário, de UMA biblioteca; manuais ou inteligentes via server/smart.py)."""
import json

from flask import Blueprint, abort, jsonify, render_template, request, session

from server import i18n
from server.i18n import E, jerr
from server.auth import login_required
from server.collections import _int_list, _json, _valid_media, clean_title, smart_ids
from server.db import get_db
from server.images import _send
from server.libraries import can_access

bp = Blueprint("playlists", __name__)


def playlist_ids(conn, p):
    """Ids da mídia da lista, na ordem de reprodução (manual = `ord`; inteligente = recalculado pelas regras)."""
    if p["smart"]:
        return smart_ids(conn, p)
    return [r["media_id"] for r in conn.execute(
        "SELECT pi.media_id FROM playlist_items pi JOIN media m ON m.id = pi.media_id "
        "WHERE pi.playlist_id = ? ORDER BY pi.ord, pi.media_id", (p["id"],))]


def get_playlist(conn, pid):
    """Lista do usuário da sessão (biblioteca ainda liberada) ou 404."""
    p = conn.execute("SELECT * FROM playlists WHERE id = ? AND user_id = ?", (pid, session["user_id"])).fetchone()
    if not p or not can_access(session["user_id"], p["library_id"]):
        abort(404)
    return p


@bp.route("/playlists")
@login_required
def list_json():
    try:
        lid = int(request.args.get("library", ""))
    except ValueError:
        return jerr("err.biblioteca_invalida", 400)
    if not can_access(session["user_id"], lid):
        abort(404)
    smart_too = request.args.get("smart") == "1"  # o modal "Adicionar à lista" só lista as manuais
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM playlists WHERE user_id = ? AND library_id = ? ORDER BY fold(title), id",
                            (session["user_id"], lid)).fetchall()
        out = [{"id": p["id"], "title": p["title"], "smart": bool(p["smart"]), "n": len(playlist_ids(conn, p))}
               for p in rows if smart_too or not p["smart"]]
    return jsonify(playlists=out)


@bp.route("/playlists", methods=["POST"])
@login_required
def create():
    j = _json()
    title = clean_title(j.get("title"))
    lid = j.get("library_id")
    if not title:
        return jerr("err.informe_nome_lista", 400)
    if not isinstance(lid, int) or isinstance(lid, bool):
        return jerr("err.biblioteca_invalida", 400)
    if not can_access(session["user_id"], lid):
        return jerr("err.biblioteca_invalida", 404)
    uid = session["user_id"]
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM playlists WHERE user_id = ? AND library_id = ? AND casefold(title) = casefold(?)",
                        (uid, lid, title)).fetchone():
            return jerr("err.ja_existe_lista_esse_nome", 409)
        if j.get("smart") is True:
            from server.smart import parse_spec
            try:
                spec = parse_spec({"match": j.get("match", "all"), "rules": j.get("rules"), "limit": j.get("limit")})
            except ValueError as e:
                return jerr(e, 400)
            cur = conn.execute("INSERT INTO playlists (user_id, library_id, title, smart, rules, limit_n) VALUES (?, ?, ?, 1, ?, ?)",
                               (uid, lid, title, json.dumps({"match": spec["match"], "rules": spec["rules"]}), spec["limit"]))
            n = len(playlist_ids(conn, get_playlist(conn, cur.lastrowid)))
            return jsonify(ok=True, id=cur.lastrowid, title=title, n=n, smart=True)
        ids = _valid_media(conn, lid, _int_list(j.get("media_ids")))
        cur = conn.execute("INSERT INTO playlists (user_id, library_id, title) VALUES (?, ?, ?)", (uid, lid, title))
        conn.executemany("INSERT OR IGNORE INTO playlist_items (playlist_id, media_id, ord) VALUES (?, ?, ?)",
                         [(cur.lastrowid, m, n) for n, m in enumerate(ids)])
    return jsonify(ok=True, id=cur.lastrowid, title=title, n=len(ids), smart=False)


@bp.route("/playlists/<int:pid>/items", methods=["POST"])
@login_required
def add_items(pid):
    with get_db() as conn:
        p = get_playlist(conn, pid)
        if p["smart"]:
            return jerr("err.lista_inteligente_os_itens_vem", 400)
        ids = _valid_media(conn, p["library_id"], _int_list(_json().get("media_ids")))
        before = len(playlist_ids(conn, p))
        nxt = conn.execute("SELECT COALESCE(MAX(ord), -1) + 1 FROM playlist_items WHERE playlist_id = ?", (pid,)).fetchone()[0]
        conn.executemany("INSERT OR IGNORE INTO playlist_items (playlist_id, media_id, ord) VALUES (?, ?, ?)",
                         [(pid, m, nxt + n) for n, m in enumerate(ids)])
        n = len(playlist_ids(conn, p))
    return jsonify(ok=True, added=n - before, n=n)


@bp.route("/playlists/<int:pid>/items/<int:mid>", methods=["DELETE"])
@login_required
def remove_item(pid, mid):
    with get_db() as conn:
        p = get_playlist(conn, pid)
        if p["smart"]:
            return jerr("err.lista_inteligente_os_itens_vem", 400)
        conn.execute("DELETE FROM playlist_items WHERE playlist_id = ? AND media_id = ?", (pid, mid))
        n = len(playlist_ids(conn, p))
    return jsonify(ok=True, n=n)


@bp.route("/playlists/<int:pid>", methods=["DELETE"])
@login_required
def delete(pid):
    """Exclui só a lista (itens e arquivos de vídeo ficam)."""
    from server import metadata

    with get_db() as conn:
        p = get_playlist(conn, pid)
        old = [p[k] for k in SLOTS if p[k]]
        conn.execute("DELETE FROM playlists WHERE id = ?", (pid,))
    for name in old:
        metadata.remove_local(name)
    return jsonify(ok=True)


# ---------- 31.9: aba e página da lista de reprodução (visual Plex) ----------

SLOTS = {"poster": "", "backdrop": "-bd", "logo": "-logo", "square": "-sq"}  # arquivos em data/posters/pl/


def library_playlists(conn, lid):
    """Listas do usuário na biblioteca (aba \"Listas de reprodução\"): id, título, n, capa própria e até 4 mídias para a capa em grade."""
    rows = conn.execute("SELECT * FROM playlists WHERE user_id = ? AND library_id = ? ORDER BY fold(title), id",
                        (session["user_id"], lid)).fetchall()
    lt = conn.execute("SELECT type FROM libraries WHERE id = ?", (lid,)).fetchone()
    out = []
    for p in rows:
        ids = playlist_ids(conn, p)
        out.append({"id": p["id"], "title": p["title"], "n": len(ids), "poster": bool(p["poster"]), "thumbs": ids[:4],
                    "dur": total_text(playlist_seconds(conn, ids, lt["type"] if lt else "movie"))})  # 32.9: mesmo formato do Início
    return out


def _fmt_dur(sec):
    sec = int(sec or 0)
    h, m = sec // 3600, sec % 3600 // 60
    return f"{h}:{m:02d}:{sec % 60:02d}" if h else f"{m}:{sec % 60:02d}"


def total_text(sec):
    """Duração total da lista: \"5min\", \"3h 05min\" e, a partir de 24 h, \"N dias, Hh\"."""
    sec = int(sec or 0)
    if sec <= 0:
        return ""
    d, h, m = sec // 86400, sec % 86400 // 3600, sec % 3600 // 60
    if d:
        return f"{d} {'dia' if d == 1 else 'dias'}, {h}h"
    return f"{sec // 3600}h {m:02d}min" if sec >= 3600 else f"{m}min"


def _dur(info):
    try:
        return (json.loads(info) if info else {}).get("duration") or 0
    except ValueError:
        return 0


def playlist_seconds(conn, ids, lib_type):
    """Duração total (s) dos itens da lista: filme = arquivo; série = soma dos episódios."""
    if not ids:
        return 0
    qi = ",".join("?" * len(ids))
    if lib_type == "movie":
        return sum(_dur(r["info"]) for r in conn.execute(f"SELECT info FROM media WHERE id IN ({qi})", ids))
    return sum(_dur(r["info"]) for r in conn.execute(f"SELECT info FROM episodes WHERE media_id IN ({qi})", ids))


@bp.route("/playlist/<int:pid>")
@login_required
def detail(pid):
    from server.libraries import _items

    with get_db() as conn:
        p = get_playlist(conn, pid)
        lib = conn.execute("SELECT id, name, type FROM libraries WHERE id = ?", (p["library_id"],)).fetchone()
        ids = playlist_ids(conn, p)
        movie = lib["type"] == "movie"
        dur = {}
        for r in conn.execute("SELECT id, info FROM media WHERE library_id = ?", (lib["id"],)):
            dur[r["id"]] = _dur(r["info"]) if movie else 0
        if not movie:
            for r in conn.execute("SELECT e.media_id, e.info FROM episodes e JOIN media m ON m.id = e.media_id WHERE m.library_id = ?",
                                  (lib["id"],)):
                dur[r["media_id"]] = dur.get(r["media_id"], 0) + _dur(r["info"])
    state = {i["id"]: i for i in _items(lib["id"], lib["type"], "title", "asc", "all", "")}
    kind = "movie" if movie else "show"
    rows = []
    for n, mid in enumerate((i for i in ids if i in state), 1):
        i = state[mid]
        rows.append({"n": n, "id": mid, "title": i["title"], "year": i["year"], "pct": i["pct"], "watched": i["watched"],
                     "dur": _fmt_dur(dur.get(mid)) if dur.get(mid) else "", "sec": dur.get(mid) or 0})
    total = sum(r["sec"] for r in rows)
    total_txt = total_text(total)  # 32.9: "7h 56min" e, a partir de 24 h, "5 dias, 12h"
    nxt = next((r for r in rows if not r["watched"]), rows[0] if rows else None)
    return render_template("playlist.html", p=p, lib=lib, kind=kind, rows=rows, total_txt=total_txt, nxt=nxt,
                           covers=[r["id"] for r in rows[:4]])


@bp.route("/playlist-image/<int:pid>/<slot>")
@login_required
def image(pid, slot):
    if slot not in SLOTS:
        abort(404)
    with get_db() as conn:
        p = get_playlist(conn, pid)
    return _send(p[slot]) or abort(404)


@bp.route("/playlist/<int:pid>/edit")
@login_required
def edit_data(pid):
    with get_db() as conn:
        p = get_playlist(conn, pid)
    return jsonify(title=f"{i18n.tr('pl.edit_title')} {p['title']}", ref=pid, smart=bool(p["smart"]),
                   fields={"title": p["title"], "summary": p["summary"] or ""}, images={k: p[k] for k in SLOTS})


@bp.route("/playlist/<int:pid>/edit", methods=["POST"])
@login_required
def edit_save(pid):
    f = _json().get("fields")
    f = f if isinstance(f, dict) else {}
    with get_db() as conn:
        p = get_playlist(conn, pid)
        title, summary = p["title"], p["summary"]
        if "title" in f:
            title = clean_title(f.get("title"))
            if not title:
                return jerr("err.informe_nome_lista", 400)
            if conn.execute("SELECT 1 FROM playlists WHERE user_id = ? AND library_id = ? AND id != ? AND casefold(title) = casefold(?)",
                            (p["user_id"], p["library_id"], pid, title)).fetchone():
                return jerr("err.ja_existe_lista_esse_nome", 409)
        if "summary" in f:
            summary = (f.get("summary") or "").strip()[:4000] if isinstance(f.get("summary"), str) else summary
        conn.execute("UPDATE playlists SET title = ?, summary = ? WHERE id = ?", (title, summary or None, pid))
    return jsonify(ok=True, title=title)


@bp.route("/playlist/<int:pid>/image/<slot>", methods=["POST"])
@login_required
def image_set(pid, slot):
    """Imagem da lista: upload (file), URL (url) ou limpar (clear=1); mesmas validações da 23.20 (tipo, 10 MB, SSRF)."""
    import requests

    from server import metadata
    from server.admin_edit import MAX_IMG, _fetch_url, _sniff, _store

    if slot not in SLOTS:
        abort(404)
    with get_db() as conn:
        p = get_playlist(conn, pid)
        old, new = p[slot], None
        try:
            if request.form.get("clear") == "1":
                pass
            elif request.files.get("file"):
                data = request.files["file"].read(MAX_IMG + 1)
                if len(data) > MAX_IMG:
                    raise ValueError(E("err.imagem_maior_que_10_mb"))
                ext = _sniff(data)
                if not ext:
                    raise ValueError(E("err.use_jpg_png_ou_webp"))
                new = f"pl/{pid}{SLOTS[slot]}{ext}"
                _store(new, data)
            elif request.form.get("url"):
                data = _fetch_url(request.form["url"].strip())
                ext = _sniff(data)
                if not ext:
                    raise ValueError(E("err.use_jpg_png_ou_webp"))
                new = f"pl/{pid}{SLOTS[slot]}{ext}"
                _store(new, data)
            else:
                raise ValueError(E("err.nada_aplicar"))
        except ValueError as ex:
            return jerr(ex, 400)
        except (requests.RequestException, OSError):
            return jerr("err.falha_obter_imagem", 502)
        if old and old != new:
            metadata.remove_local(old)
        conn.execute(f"UPDATE playlists SET {slot} = ? WHERE id = ?", (new, pid))
    return jsonify(ok=True, name=new)
