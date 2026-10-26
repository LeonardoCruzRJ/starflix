"""Coleções manuais (Fase 24): grupos de itens de UMA biblioteca, criados e editados só pelo admin."""
import json

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session

from server.auth import admin_required, login_required
from server.db import get_db, prune_stars
from server.images import _send
from server.libraries import _placeholder, can_access
from server.i18n import jerr

bp = Blueprint("collections", __name__)

TITLE_MAX = 100
IDS_MAX = 2000
ITEM_ORDER = "m.year IS NULL, m.year, fold(m.title), m.id"  # ano (mais antigo primeiro) e título sem acento


def _json():
    j = request.get_json(silent=True)
    return j if isinstance(j, dict) else {}


def _int_list(v):
    """Lista de ids inteiros positivos, sem repetição (aceita só int; ignora o resto)."""
    if not isinstance(v, list):
        return []
    out, seen = [], set()
    for x in v[:IDS_MAX]:
        if isinstance(x, int) and not isinstance(x, bool) and x > 0 and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def clean_title(t):
    return " ".join(str(t or "").split())[:TITLE_MAX]


def _valid_media(conn, library_id, ids):
    """Mantém só os ids que são mídia da biblioteca (na ordem recebida)."""
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    ok = {r["id"] for r in conn.execute(f"SELECT id FROM media WHERE library_id = ? AND id IN ({marks})", (library_id, *ids))}
    return [i for i in ids if i in ok]


def library_collections(conn, library_id):
    """Coleções da biblioteca com a contagem de itens, por título (ou 'ordenar por') sem acento."""
    rows = conn.execute(
        "SELECT c.*, COUNT(ci.media_id) AS n FROM collections c "
        "LEFT JOIN collection_items ci ON ci.collection_id = c.id WHERE c.library_id = ? "
        "GROUP BY c.id ORDER BY fold(COALESCE(NULLIF(c.sort_title, ''), c.title)), c.id",
        (library_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d["smart"]:  # 31.3: coleção inteligente recalcula os itens ao abrir
            d["n"] = len(smart_ids(conn, d))
        out.append(d)
    return out


def _spec_of(c):
    """Spec salvo (rules/limit_n) da coleção inteligente."""
    from server.smart import parse_spec
    try:
        data = json.loads(c["rules"]) if c["rules"] else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["limit"] = c["limit_n"]
    try:
        return parse_spec(data)
    except ValueError:
        return {"match": "all", "rules": [], "limit": None}


def smart_ids(conn, c):
    """Ids da mídia que casam com as regras da coleção inteligente (nunca grava collection_items)."""
    from server.smart import smart_items
    lib = conn.execute("SELECT type FROM libraries WHERE id = ?", (c["library_id"],)).fetchone()
    return [i["id"] for i in smart_items(c["library_id"], lib["type"], _spec_of(c))] if lib else []


def collection_media(conn, cid):
    """Itens (mídia) da coleção, na ordem de exibição."""
    c = conn.execute("SELECT * FROM collections WHERE id = ?", (cid,)).fetchone()
    if c and c["smart"]:
        ids = smart_ids(conn, c)
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        return conn.execute(f"SELECT m.* FROM media m WHERE m.id IN ({marks}) ORDER BY {ITEM_ORDER}", ids).fetchall()
    return conn.execute(
        "SELECT m.* FROM collection_items ci JOIN media m ON m.id = ci.media_id "
        f"WHERE ci.collection_id = ? ORDER BY {ITEM_ORDER}",
        (cid,),
    ).fetchall()


def get_collection(conn, cid):
    """Coleção acessível ao usuário da sessão (biblioteca liberada) ou 404."""
    c = conn.execute("SELECT * FROM collections WHERE id = ?", (cid,)).fetchone()
    if not c or not can_access(session["user_id"], c["library_id"]):
        abort(404)
    return c


def _admin_collection(conn, cid):
    c = conn.execute("SELECT * FROM collections WHERE id = ?", (cid,)).fetchone()
    if not c:
        abort(404)
    return c


def _count(conn, cid):
    return conn.execute("SELECT COUNT(*) FROM collection_items WHERE collection_id = ?", (cid,)).fetchone()[0]


# ---------- API do admin (JSON) ----------

@bp.route("/admin/collections")
@admin_required
def list_json():
    try:
        lid = int(request.args.get("library", ""))
    except ValueError:
        return jerr("err.biblioteca_invalida", 400)
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM libraries WHERE id = ?", (lid,)).fetchone():
            abort(404)
        rows = library_collections(conn, lid)
    if request.args.get("smart") != "1":  # o modal "Adicionar à coleção" só lista coleções manuais
        rows = [r for r in rows if not r["smart"]]
    return jsonify(collections=[{"id": r["id"], "title": r["title"], "n": r["n"], "smart": bool(r["smart"])} for r in rows])


@bp.route("/admin/collections", methods=["POST"])
@admin_required
def create():
    j = _json()
    title = clean_title(j.get("title"))
    lid = j.get("library_id")
    if not title:
        return jerr("err.informe_nome_colecao", 400)
    if not isinstance(lid, int) or isinstance(lid, bool):
        return jerr("err.biblioteca_invalida", 400)
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM libraries WHERE id = ?", (lid,)).fetchone():
            return jerr("err.biblioteca_invalida", 404)
        if conn.execute("SELECT 1 FROM collections WHERE library_id = ? AND casefold(title) = casefold(?)", (lid, title)).fetchone():
            return jerr("err.ja_existe_colecao_esse_nome", 409)
        if j.get("smart") is True:  # 31.3: coleção inteligente = só regras, sem collection_items
            from server.smart import parse_spec
            try:
                spec = parse_spec({"match": j.get("match", "all"), "rules": j.get("rules"), "limit": j.get("limit")})
            except ValueError as e:
                return jerr(e, 400)
            cur = conn.execute("INSERT INTO collections (library_id, title, smart, rules, limit_n) VALUES (?, ?, 1, ?, ?)",
                               (lid, title, json.dumps({"match": spec["match"], "rules": spec["rules"]}), spec["limit"]))
            n = len(smart_ids(conn, conn.execute("SELECT * FROM collections WHERE id = ?", (cur.lastrowid,)).fetchone()))
            return jsonify(ok=True, id=cur.lastrowid, title=title, n=n, smart=True)
        ids = _valid_media(conn, lid, _int_list(j.get("media_ids")))
        cur = conn.execute("INSERT INTO collections (library_id, title) VALUES (?, ?)", (lid, title))
        cid = cur.lastrowid
        conn.executemany("INSERT OR IGNORE INTO collection_items (collection_id, media_id) VALUES (?, ?)", [(cid, i) for i in ids])
    return jsonify(ok=True, id=cid, title=title, n=len(ids))


@bp.route("/admin/collections/<int:cid>/rules", methods=["GET", "POST"])
@admin_required
def rules(cid):
    """31.3: lê/edita as regras da coleção inteligente (reabre o painel de filtros)."""
    with get_db() as conn:
        c = _admin_collection(conn, cid)
        if not c["smart"]:
            return jerr("err.colecao_nao_inteligente", 400)
        if request.method == "POST":
            from server.smart import parse_spec
            j = _json()
            try:
                spec = parse_spec({"match": j.get("match", "all"), "rules": j.get("rules"), "limit": j.get("limit")})
            except ValueError as e:
                return jerr(e, 400)
            conn.execute("UPDATE collections SET rules = ?, limit_n = ? WHERE id = ?",
                         (json.dumps({"match": spec["match"], "rules": spec["rules"]}), spec["limit"], cid))
            c = _admin_collection(conn, cid)
        spec = _spec_of(c)
        return jsonify(ok=True, **spec, n=len(smart_ids(conn, c)))


@bp.route("/admin/collections/<int:cid>/items", methods=["POST"])
@admin_required
def add_items(cid):
    j = _json()
    with get_db() as conn:
        c = _admin_collection(conn, cid)
        if c["smart"]:
            return jerr("err.colecao_inteligente_os_itens_vem", 400)
        ids = _valid_media(conn, c["library_id"], _int_list(j.get("media_ids")))
        before = _count(conn, cid)
        conn.executemany("INSERT OR IGNORE INTO collection_items (collection_id, media_id) VALUES (?, ?)", [(cid, i) for i in ids])
        n = _count(conn, cid)
    return jsonify(ok=True, added=n - before, n=n)


@bp.route("/admin/collections/<int:cid>/items/<int:mid>", methods=["DELETE"])
@admin_required
def remove_item(cid, mid):
    with get_db() as conn:
        if _admin_collection(conn, cid)["smart"]:
            return jerr("err.colecao_inteligente_os_itens_vem", 400)
        conn.execute("DELETE FROM collection_items WHERE collection_id = ? AND media_id = ?", (cid, mid))
        n = _count(conn, cid)
    return jsonify(ok=True, n=n)


@bp.route("/admin/collections/<int:cid>", methods=["DELETE"])
@admin_required
def delete(cid):
    """Exclui só a coleção (itens e arquivos de vídeo ficam)."""
    from server.metadata import collection_image_names, remove_local
    with get_db() as conn:
        _admin_collection(conn, cid)
        names = collection_image_names(conn, "c.id = ?", (cid,))
        conn.execute("DELETE FROM collections WHERE id = ?", (cid,))  # itens saem por cascata
        prune_stars(conn)
    for n in names:
        remove_local(n)
    return jsonify(ok=True)


# ---------- página de detalhe (24.7) ----------

@bp.route("/collection/<int:cid>")
@login_required
def detail(cid):
    from server.libraries import _items
    from server.mylist import get_stars

    with get_db() as conn:
        c = get_collection(conn, cid)
        lib = conn.execute("SELECT id, name, type FROM libraries WHERE id = ?", (c["library_id"],)).fetchone()
        rows = collection_media(conn, cid)
    state = {i["id"]: i for i in _items(lib["id"], lib["type"], "title", "asc", "all", "")}
    items = [state[r["id"]] for r in rows if r["id"] in state]
    kind = "movie" if lib["type"] == "movie" else "show"
    nxt = next((i for i in items if not i["watched"]), items[0] if items else None)
    return render_template(
        "collection.html", c=c, lib=lib, items=items, kind=kind, nxt=nxt, stars=get_stars("collection", cid),
        has_bd=bool(c["backdrop"]) or any(r["backdrop"] for r in rows),
    )


# ---------- imagens (qualquer usuário com acesso à biblioteca) ----------

def _first(conn, cid, need=None):
    """Primeiro item (na ordem de exibição) da coleção; `need` = coluna que precisa estar preenchida."""
    return next((m for m in collection_media(conn, cid) if not need or m[need]), None)


def _col_image(cid, column):
    with get_db() as conn:
        c = get_collection(conn, cid)
        first = _first(conn, cid, "poster" if column in ("poster", "square") else column)
    return c, (first["id"] if first else None)


@bp.route("/collection-poster/<int:cid>")
@login_required
def poster(cid):
    c, mid = _col_image(cid, "poster")
    r = _send(c["poster"])
    if r:
        return r
    return redirect(f"/poster/{mid}") if mid else _placeholder(c["title"])


@bp.route("/collection-backdrop/<int:cid>")
@login_required
def backdrop(cid):
    c, mid = _col_image(cid, "backdrop")
    r = _send(c["backdrop"])
    if r:
        return r
    return redirect(f"/backdrop/{mid}") if mid else abort(404)


@bp.route("/collection-logo/<int:cid>")
@login_required
def logo(cid):
    c, _ = _col_image(cid, "logo")
    return _send(c["logo"]) or abort(404)


@bp.route("/collection-square/<int:cid>")
@login_required
def square(cid):
    c, mid = _col_image(cid, "square")
    r = _send(c["square"]) or _send(c["poster"])
    if r:
        return r
    return redirect(f"/square/{mid}") if mid else _placeholder(c["title"])
