import json
import time
import os

from xml.sax.saxutils import escape

from flask import Blueprint, Response, abort, jsonify, redirect, render_template, request, send_from_directory, session

import config
from server import i18n
from server.i18n import E, jerr, tr
from server.auth import admin_required, login_required
from server.library_access import library_users
from server.db import PREF_DEFAULTS, fold, get_db, invalidate_lib_prefs, lib_prefs, library_folders, prune_stars, set_primary_folder
from server.scanner import cancel_library, exclusive, is_scanning, progress, prune_missing, scan_async

bp = Blueprint("libraries", __name__)
TYPES = {"movie": "lm.type.movie", "show": "lm.type.show", "video": "lm.type.video"}  # chaves; traduzidas na saída


def visible_libraries(user_id):
    """Admin vê todas; demais usuários só as liberadas em user_libraries."""
    with get_db() as conn:
        u = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if u and u["is_admin"]:
            return conn.execute("SELECT * FROM libraries ORDER BY fold(name), id").fetchall()
        return conn.execute(
            "SELECT l.* FROM libraries l JOIN user_libraries ul ON ul.library_id = l.id "
            "WHERE ul.user_id = ? ORDER BY fold(l.name), l.id",
            (user_id,),
        ).fetchall()


def can_access(user_id, library_id):
    return any(l["id"] == library_id for l in visible_libraries(user_id))


def pinned_libraries(user_id):
    """Bibliotecas liberadas e fixadas na barra lateral (29.2); as desafixadas seguem no Início, na busca e por URL."""
    libs = visible_libraries(user_id)
    with get_db() as conn:
        off = {r["library_id"] for r in conn.execute("SELECT library_id FROM library_unpinned WHERE user_id = ?", (user_id,))}
        pos = {r["library_id"]: r["position"] for r in conn.execute("SELECT library_id, position FROM library_order WHERE user_id = ?", (user_id,))}
    libs = [l for l in libs if l["id"] not in off]
    # 45.3: ordem escolhida pelo usuário (web); as sem posição (bibliotecas novas) ficam no fim, na ordem por nome de visible_libraries
    return sorted(libs, key=lambda l: pos.get(l["id"], 1 << 30))  # sorted é estável


@bp.route("/library/<int:lid>/info")
@login_required
def info(lid):
    """29.4: estado da biblioteca para o menu ⋮ (examinando, última atualização, fixada) e, para admin, usuários do modal de acesso."""
    uid = session["user_id"]
    if not can_access(uid, lid):
        return jerr("err.biblioteca_nao_encontrada", 404)
    with get_db() as conn:
        lib = conn.execute("SELECT scanned_at FROM libraries WHERE id = ?", (lid,)).fetchone()
        off = conn.execute("SELECT 1 FROM library_unpinned WHERE user_id = ? AND library_id = ?", (uid, lid)).fetchone()
        adm = conn.execute("SELECT is_admin FROM users WHERE id = ?", (uid,)).fetchone()
        users = library_users(conn, lid) if adm and adm["is_admin"] else []
    pr = progress() if is_scanning() else {}
    return jsonify(scanning=is_scanning(), scanned_at=lib["scanned_at"], pinned=not off, users=users,
                   stage=pr.get("stage"), stage_lib=pr.get("lib"), stage_secs=int(time.time() - pr["since"]) if pr else None)


@bp.route("/admin/scan-state")
@admin_required
def scan_state():
    """35.8: exame em andamento e ids dos itens em processamento agora (ícones girando)."""
    from server import scanstate
    on = is_scanning()
    since = request.args.get("since", type=int)
    seq, done = scanstate.done_since(since)
    return jsonify(scanning=on or scanstate.busy(), ids=scanstate.snapshot() if (on or scanstate.busy()) else [], seq=seq, done=done)


@bp.route("/admin/scan-cards")
@admin_required
def scan_cards():
    """35.15: título e ano atuais dos itens que acabaram de ser examinados (a grade atualiza o card na hora)."""
    ids = [int(x) for x in request.args.get("ids", "").split(",") if x.strip().isdigit()][:200]
    if not ids:
        return jsonify(items={})
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT id, dtitle(library_id, title, original_title) AS shown, year FROM media WHERE id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()
    return jsonify(items={str(r["id"]): {"title": r["shown"], "year": r["year"]} for r in rows})


@bp.route("/library/order", methods=["POST"])
@login_required
def order():
    """45.3: grava a ordem das bibliotecas na barra lateral do usuário (web, app do celular e TV leem pinned_libraries)."""
    d = request.get_json(silent=True)
    ids = d.get("ids") if isinstance(d, dict) else None
    if not isinstance(ids, list) or len(ids) > 500 or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        return jerr("err.dados_invalidos", 400)
    uid = session["user_id"]
    ok = {l["id"] for l in visible_libraries(uid)}
    seen = []
    for i in ids:
        if i in ok and i not in seen:
            seen.append(i)
    with get_db() as conn:
        conn.execute("DELETE FROM library_order WHERE user_id = ?", (uid,))
        conn.executemany("INSERT INTO library_order (user_id, library_id, position) VALUES (?, ?, ?)", [(uid, lid, n) for n, lid in enumerate(seen)])
    return jsonify(ok=True)


@bp.route("/library/<int:lid>/pin", methods=["POST"])
@login_required
def pin(lid):
    d = request.get_json(silent=True)
    if not isinstance(d, dict) or not isinstance(d.get("pinned"), bool):
        return jerr("err.dados_invalidos", 400)
    uid = session["user_id"]
    if not can_access(uid, lid):
        return jerr("err.biblioteca_nao_encontrada", 404)
    with get_db() as conn:
        if d["pinned"]:
            conn.execute("DELETE FROM library_unpinned WHERE user_id = ? AND library_id = ?", (uid, lid))
        else:
            conn.execute("INSERT OR IGNORE INTO library_unpinned (user_id, library_id) VALUES (?, ?)", (uid, lid))
    return jsonify(ok=True, pinned=d["pinned"])


def _render(error=None):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM libraries ORDER BY fold(name), id").fetchall()
    return render_template("admin_libraries.html", libs=rows, types={k: tr(v) for k, v in TYPES.items()}, error=error, scanning=is_scanning())


def _inside(path, parent):
    """True se `path` é `parent` ou está dentro dele."""
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


def check_folder(conn, path, own_id=0, siblings=()):
    """Valida uma pasta (já absoluta): existe, não repete nem aninha com outra biblioteca (12.3/16.11)
    nem com `siblings` (outras pastas da mesma biblioteca). Devolve a mensagem de erro ou None."""
    if not os.path.isdir(path):
        return E("err.pasta_nao_encontrada_servidor")
    others = [r[0] for r in conn.execute(
        "SELECT path FROM library_folders WHERE library_id != ? UNION SELECT path FROM libraries WHERE id != ?", (own_id, own_id)
    )]
    if path in others:
        return E("err.essa_pasta_ja_usada_por")
    mine = os.path.realpath(path)
    for o in others:
        other = os.path.realpath(o)
        if _inside(mine, other) or _inside(other, mine):
            return E("msg.essa_pasta_esta_dentro_outro")
    for sib in siblings:
        other = os.path.realpath(sib)
        if path == sib or _inside(mine, other) or _inside(other, mine):
            return E("err.essa_pasta_ja_esta_biblioteca")
    return None


def clean_folders(paths, own_id=0):
    """Lista de pastas (28.2): caminhos absolutos sem repetição, ≥ 1, cada uma validada. Devolve (lista, erro)."""
    out = []
    for p in paths or []:
        p = (p or "").strip()
        if p:
            out.append(os.path.abspath(p))
    if not out:
        return None, E("msg.adicione_menos_pasta")
    with get_db() as conn:
        for i, p in enumerate(out):
            err = check_folder(conn, p, own_id, out[:i])
            if err:
                return None, err
    return out, None


def _clean(form, own_id=0):
    name = form.get("name", "").strip()
    type_ = form.get("type", "")
    path = os.path.abspath(form.get("path", "").strip()) if form.get("path", "").strip() else ""
    if not name or type_ not in TYPES:
        return None, E("err.informe_nome_tipo")
    with get_db() as conn:
        primary = conn.execute("SELECT path FROM libraries WHERE id = ?", (own_id,)).fetchone()
        siblings = [p for p in library_folders(conn, own_id) if not primary or p != primary["path"]] if own_id else []
        err = check_folder(conn, path, own_id, siblings)
    if err:
        return None, err
    return (name, type_, path), None


@bp.route("/admin/libraries", methods=["GET", "POST"])
@admin_required
def libraries():
    if request.method == "POST":
        data, error = _clean(request.form)
        if error:
            return _render(error)
        with get_db() as conn:
            lid = conn.execute("INSERT INTO libraries (name, type, path) VALUES (?, ?, ?)", data).lastrowid
            set_primary_folder(conn, lid, data[2])
        return redirect("/admin/libraries")
    return _render()


def _purge_media(conn, lid):
    """Apaga mídia/episódios da biblioteca e o progresso órfão; devolve os pôsteres locais a remover do disco."""
    posters = [
        r[k] for r in conn.execute(
            "SELECT poster, backdrop, logo, square FROM media WHERE library_id = ?", (lid,)
        ) for k in ("poster", "backdrop", "logo", "square") if r[k] and not r[k].startswith("/")
    ]
    from server.metadata import collection_image_names, show_image_names
    posters += show_image_names(conn, "m.library_id = ?", (lid,))
    posters += collection_image_names(conn, "c.library_id = ?", (lid,))
    conn.execute("DELETE FROM collections WHERE library_id = ?", (lid,))  # itens saem por cascata
    conn.execute("DELETE FROM media WHERE library_id = ?", (lid,))  # episódios saem por cascata
    conn.execute("DELETE FROM progress WHERE item_type = 'movie' AND item_id NOT IN (SELECT id FROM media)")
    conn.execute("DELETE FROM progress WHERE item_type = 'episode' AND item_id NOT IN (SELECT id FROM episodes)")
    prune_stars(conn)
    return posters


def _remove_posters(names):
    from server.metadata import prune_people, remove_local
    for name in names:
        remove_local(name)
    prune_people()


def _under(path, folder):
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def _sync_items(conn, lid, keep, remap=None):
    """Pastas da biblioteca mudaram: itens sob alguma pasta de `keep` ficam; com `remap=(antiga, nova)` os que existem no
    mesmo lugar relativo sob a nova (remontagem) são reapontados e mantêm progresso; o resto sai.
    Devolve os pôsteres locais a apagar."""
    def fix(path):
        if any(_under(path, k) for k in keep):
            return path
        if remap and _under(path, remap[0]):
            cand = os.path.join(remap[1], os.path.relpath(path, remap[0]))
            if os.path.exists(cand):
                return cand
        return None

    posters = []
    for r in conn.execute("SELECT id, path, poster, backdrop, logo, square FROM media WHERE library_id = ? AND path IS NOT NULL", (lid,)).fetchall():
        np = fix(r["path"])
        if np is None:
            conn.execute("DELETE FROM media WHERE id = ?", (r["id"],))
            posters += [r[k] for k in ("poster", "backdrop", "logo", "square") if r[k] and not r[k].startswith("/")]
        elif np != r["path"]:
            conn.execute("UPDATE media SET path = ? WHERE id = ?", (np, r["id"]))
    for r in conn.execute(
        "SELECT e.id, e.path, e.still FROM episodes e JOIN media m ON m.id = e.media_id WHERE m.library_id = ?", (lid,)
    ).fetchall():
        np = fix(r["path"])
        if np is None:
            if r["still"] and not r["still"].startswith("/"):
                posters.append(r["still"])
            conn.execute("DELETE FROM episodes WHERE id = ?", (r["id"],))
        elif np != r["path"]:
            conn.execute("UPDATE episodes SET path = ? WHERE id = ?", (np, r["id"]))
    for r in conn.execute(
        "SELECT id, poster, backdrop, logo, square FROM media WHERE library_id = ? AND path IS NULL AND id NOT IN (SELECT media_id FROM episodes)",
        (lid,),
    ).fetchall():
        from server.metadata import show_image_names
        posters += show_image_names(conn, "m.id = ?", (r["id"],))
        conn.execute("DELETE FROM media WHERE id = ?", (r["id"],))
        posters += [r[k] for k in ("poster", "backdrop", "logo", "square") if r[k] and not r[k].startswith("/")]
    conn.execute("DELETE FROM progress WHERE item_type = 'movie' AND item_id NOT IN (SELECT id FROM media)")
    conn.execute("DELETE FROM progress WHERE item_type = 'episode' AND item_id NOT IN (SELECT id FROM episodes)")
    prune_stars(conn)
    return posters


def _repath(conn, lid, old, new):
    """Caminho (primeira pasta) mudou, mesmo tipo: mantém as demais pastas da biblioteca."""
    others = [p for p in library_folders(conn, lid) if p != old]
    return _sync_items(conn, lid, [new] + others, (old, new))


def set_folders(conn, lid, folders):
    """Troca o conjunto de pastas (já validadas por clean_folders): a 1ª vira libraries.path; itens de pasta removida saem
    do banco (progresso do resto fica). Devolve os pôsteres locais a apagar."""
    old = library_folders(conn, lid)
    posters = _sync_items(conn, lid, folders) if set(old) - set(folders) else []
    conn.execute("DELETE FROM library_folders WHERE library_id = ?", (lid,))
    for i, p in enumerate(folders):
        conn.execute("INSERT INTO library_folders (library_id, path, ord) VALUES (?, ?, ?)", (lid, p, i))
    conn.execute("UPDATE libraries SET path = ? WHERE id = ?", (folders[0], lid))
    return posters


@bp.route("/admin/libraries/<int:lid>/edit", methods=["POST"])
@admin_required
def edit(lid):
    with get_db() as conn:
        old = conn.execute("SELECT type, path FROM libraries WHERE id = ?", (lid,)).fetchone()
    if not old:
        abort(404)
    data, error = _clean(request.form, lid)
    if error:
        return _render(error)
    posters = []
    with get_db() as conn:
        if old["type"] != data[1]:  # filmes <-> séries: os itens do tipo antigo não servem; o próximo scan refaz
            posters = _purge_media(conn, lid)
        elif old["path"] != data[2]:  # mesmo tipo, outra pasta: não deixar itens da pasta antiga
            posters = _repath(conn, lid, old["path"], data[2])
        conn.execute("UPDATE libraries SET name = ?, type = ?, path = ? WHERE id = ?", (*data, lid))
        set_primary_folder(conn, lid, data[2])
    _remove_posters(posters)
    return redirect("/admin/libraries")


@bp.route("/admin/libraries/<int:lid>/delete", methods=["POST"])
@admin_required
def delete(lid):
    cancel_library(lid)  # 35.22: exame em andamento nesta biblioteca termina antes de apagar
    with get_db() as conn:
        posters = _purge_media(conn, lid)
        conn.execute("DELETE FROM libraries WHERE id = ?", (lid,))
    _remove_posters(posters)
    return jsonify(ok=True) if request.args.get("json") else redirect("/admin/libraries")


@bp.route("/admin/browse")
@admin_required
def browse():
    path = os.path.abspath(request.args.get("path") or "/")
    missing = not os.path.isdir(path)
    if missing:
        path = "/"
    try:
        dirs = sorted(
            d for d in os.listdir(path)
            if not d.startswith(".") and os.path.isdir(os.path.join(path, d))
        )
    except PermissionError:
        dirs = []
    parent = os.path.dirname(path) if path != "/" else None
    return jsonify(path=path, parent=parent, dirs=dirs, missing=missing, **_browse_roots())


@bp.route("/admin/libraries/check-folder", methods=["POST"])
@admin_required
def check_folder_api():
    """Valida uma pasta antes de entrar na lista (28.11): regras 12.3/16.11 + pastas já escolhidas."""
    d = _body()
    if d is None:
        return jerr("err.dados_invalidos", 400)
    path = str(d.get("path", "")).strip()
    if not path:
        return jerr("err.informe_pasta", 400)
    path = os.path.abspath(path)
    chosen = [os.path.abspath(p) for p in d.get("folders", []) if isinstance(p, str) and p.strip()]
    try:
        own = int(d.get("library_id") or 0)
    except (TypeError, ValueError):
        own = 0
    with get_db() as conn:
        err = check_folder(conn, path, own, chosen)
    if err:
        return jerr(err, 400)
    return jsonify(ok=True, path=path)


def _browse_roots():
    """Atalhos do navegador de pastas (28.3): pasta pessoal, `/` e subpastas de /mnt e /media."""
    home = os.path.expanduser("~")
    roots = [{"name": "/", "path": "/"}]
    for base in ("/mnt", "/media"):
        try:
            for d in sorted(os.listdir(base)):
                if not d.startswith(".") and os.path.isdir(os.path.join(base, d)):
                    roots.append({"name": d, "path": os.path.join(base, d)})
        except OSError:
            pass
    return {"home": {"name": os.path.basename(home.rstrip("/")) or "~", "path": home}, "roots": roots}


# ---- 28.3: API JSON do gerenciador de bibliotecas (opções por biblioteca em libraries.lang + libraries.prefs)
LANGS = {"pt-BR": "Português", "en-US": "English", "es-ES": "Español", "fr-FR": "Français", "de-DE": "Deutsch", "it-IT": "Italiano", "ja-JP": "日本語"}
CERT_COUNTRIES = {"BR": "cc.br", "US": "cc.us", "GB": "cc.gb", "PT": "cc.pt", "ES": "cc.es", "FR": "cc.fr",
                  "DE": "cc.de", "IT": "cc.it", "JP": "cc.jp", "CA": "cc.ca", "AU": "cc.au", "MX": "cc.mx"}
PREF_CHOICES = {"agent": ("tmdb", "none"), "visibility": ("all", "hide_home", "hide_all"), "cert_country": tuple(CERT_COUNTRIES),
                "rating_source": ("tmdb", "imdb", "rt"), "collection_mode": ("default", "hide", "both")}


def _prefs_clean(data, base=None):
    """Valida `prefs` vindas do cliente; chaves desconhecidas são ignoradas. Devolve (prefs, erro)."""
    if not isinstance(data, dict):
        return None, E("err.opcoes_invalidas")
    out = dict(base or PREF_DEFAULTS)
    for k, v in data.items():
        if k not in PREF_DEFAULTS:
            continue
        if isinstance(PREF_DEFAULTS[k], bool):
            if not isinstance(v, bool):
                return None, E("err.opcao_invalida_k", k=k)
        elif v not in PREF_CHOICES[k]:
            return None, E("err.opcao_invalida_k", k=k)
        if k == "rating_source" and v != "tmdb" and not config.OMDB_API_KEY:
            return None, E("msg.notas_imdb_rotten_tomatoes_exigem")
        out[k] = v
    return out, None


def _lib_json(conn, row):
    return {"id": row["id"], "name": row["name"], "type": row["type"], "lang": row["lang"], "folders": library_folders(conn, row["id"]),
            "prefs": lib_prefs(row), "scanned_at": row["scanned_at"]}


def get_setting(conn, key, default=None):
    r = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return r["value"] if r and r["value"] is not None else default


def _body():
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else None


def _name_clean(d):
    name = str(d.get("name", "")).strip()[:100]
    return name or None


@bp.route("/admin/libraries/data")
@admin_required
def libraries_data():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM libraries ORDER BY fold(name), id").fetchall()
        libs = [_lib_json(conn, r) for r in rows]
        merge = get_setting(conn, "merge_recent", "0") == "1"
    return jsonify(server_name="StarFlix", scanning=is_scanning(), libraries=libs, settings={"merge_recent": merge},
                   types={k: tr(v) for k, v in TYPES.items()}, langs=LANGS, cert_countries={k: tr(v) for k, v in CERT_COUNTRIES.items()}, defaults=PREF_DEFAULTS, omdb=bool(config.OMDB_API_KEY))


@bp.route("/admin/libraries/add", methods=["POST"])
@admin_required
def libraries_add():
    d = _body()
    if d is None:
        return jerr("err.dados_invalidos", 400)
    name, type_, lang = _name_clean(d), d.get("type"), d.get("lang") or None
    if not name or type_ not in TYPES:
        return jerr("err.informe_nome_tipo", 400)
    if lang is not None and lang not in LANGS:
        return jerr("err.idioma_invalido", 400)
    prefs, error = _prefs_clean(d.get("prefs", {}))
    if error:
        return jerr(error, 400)
    folders, error = clean_folders(d.get("folders"))
    if error:
        return jerr(error, 400)
    with get_db() as conn:
        lid = conn.execute("INSERT INTO libraries (name, type, path, lang, prefs) VALUES (?, ?, ?, ?, ?)",
                           (name, type_, folders[0], lang, json.dumps(prefs))).lastrowid
        set_folders(conn, lid, folders)
        lib = _lib_json(conn, conn.execute("SELECT * FROM libraries WHERE id = ?", (lid,)).fetchone())
    invalidate_lib_prefs()
    scan_async(lid)
    return jsonify(library=lib), 201


def _refresh_metadata(conn, lid):
    """Idioma/país mudou (28.4): o próximo exame refaz os metadados; campos travados (locks) e edições de episódio ficam."""
    conn.execute("UPDATE media SET meta_ok = NULL WHERE library_id = ? AND tmdb_id > 0", (lid,))
    conn.execute(
        "UPDATE episodes SET title = NULL, overview = NULL WHERE (locks IS NULL OR locks IN ('', '{}')) "
        "AND media_id IN (SELECT id FROM media WHERE library_id = ? AND tvdb_id > 0)", (lid,))


@bp.route("/admin/libraries/<int:lid>/update", methods=["POST"])
@admin_required
def libraries_update(lid):
    d = _body()
    if d is None:
        return jerr("err.dados_invalidos", 400)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM libraries WHERE id = ?", (lid,)).fetchone()
    if not row:
        return jerr("err.biblioteca_nao_encontrada", 404)
    if "type" in d and d["type"] != row["type"]:
        return jerr("err.tipo_biblioteca_nao_pode_ser", 400)
    name = row["name"]
    if "name" in d:
        name = _name_clean(d)
        if not name:
            return jerr("err.informe_nome", 400)
    lang = row["lang"]
    if "lang" in d:
        lang = d["lang"] or None
        if lang is not None and lang not in LANGS:
            return jerr("err.idioma_invalido", 400)
    prefs = lib_prefs(row)
    if "prefs" in d:
        prefs, error = _prefs_clean(d["prefs"], prefs)
        if error:
            return jerr(error, 400)
    folders = None
    if "folders" in d:
        folders, error = clean_folders(d["folders"], lid)
        if error:
            return jerr(error, 400)
    posters = []
    with get_db() as conn:
        conn.execute("UPDATE libraries SET name = ?, lang = ?, prefs = ? WHERE id = ?", (name, lang, json.dumps(prefs), lid))
        if lang != row["lang"] or prefs["cert_country"] != lib_prefs(row)["cert_country"]:
            _refresh_metadata(conn, lid)
        elif prefs["lang_art"] != lib_prefs(row)["lang_art"]:  # 28.5: refaz só a arte no próximo exame
            conn.execute("UPDATE media SET meta_ok = NULL WHERE library_id = ? AND tmdb_id > 0", (lid,))
        if folders:
            posters = set_folders(conn, lid, folders)
        lib = _lib_json(conn, conn.execute("SELECT * FROM libraries WHERE id = ?", (lid,)).fetchone())
    _remove_posters(posters)
    invalidate_lib_prefs()
    return jsonify(library=lib)


@bp.route("/admin/libraries/settings", methods=["GET", "POST"])
@admin_required
def libraries_settings():
    with get_db() as conn:
        if request.method == "POST":
            d = _body()
            if d is None or not isinstance(d.get("merge_recent"), bool):
                return jerr("err.dados_invalidos", 400)
            conn.execute("INSERT INTO settings (key, value) VALUES ('merge_recent', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", ("1" if d["merge_recent"] else "0",))
        merge = get_setting(conn, "merge_recent", "0") == "1"
    return jsonify(merge_recent=merge)


@bp.route("/admin/libraries/<int:lid>/scan", methods=["POST"])
@admin_required
def scan(lid):
    scan_async(lid, manual=True)
    if request.args.get("json"):
        return jsonify(ok=True, scanning=True)
    nxt = request.form.get("next")
    return redirect("/admin" if nxt == "panel" else f"/library/{lid}" if nxt == "library" else "/admin/libraries")


def _lib_action(lid):
    with get_db() as conn:
        return conn.execute("SELECT id FROM libraries WHERE id = ?", (lid,)).fetchone()


def _busy():
    return jerr("err.biblioteca_esta_sendo_examinada_aguarde", 409, scanning=True)


def _do_refresh(lid):
    with get_db() as conn:
        _refresh_metadata(conn, lid)


@bp.route("/admin/libraries/<int:lid>/analyze", methods=["POST"])
@admin_required
def lib_analyze(lid):
    """29.3 Analisar = escanear (arquivos + probe)."""
    if not _lib_action(lid):
        return jerr("err.biblioteca_nao_encontrada", 404)
    if not scan_async(lid, manual=True):
        return _busy()
    return jsonify(ok=True, scanning=True)


@bp.route("/admin/libraries/<int:lid>/refresh-info", methods=["POST"])
@admin_required
def lib_refresh_info(lid):
    """29.3 Atualizar todas as Informações = refaz a correspondência da biblioteca (locks intactos)."""
    if not _lib_action(lid):
        return jerr("err.biblioteca_nao_encontrada", 404)
    if not scan_async(lid, before=lambda: _do_refresh(lid)):
        return _busy()
    return jsonify(ok=True, scanning=True)


@bp.route("/admin/libraries/<int:lid>/examine", methods=["POST"])
@admin_required
def lib_examine(lid):
    """29.3/35.14 Examinar arquivos da biblioteca = procura arquivos novos e completa o que falta; quem já tem dados não é tocado
    (refazer tudo é \"Atualizar todas as Informações\")."""
    if not _lib_action(lid):
        return jerr("err.biblioteca_nao_encontrada", 404)
    if not scan_async(lid, manual=True):  # 35.14: item com capa e dados completos não é tocado; só o que for novo
        return _busy()
    return jsonify(ok=True, scanning=True)


@bp.route("/admin/libraries/<int:lid>/trickplay", methods=["POST"])
@admin_required
def lib_trickplay(lid):
    """49.2: Gerar miniaturas da biblioteca (mesmo com a opção desligada); segue em segundo plano."""
    if not _lib_action(lid):
        return jerr("err.biblioteca_nao_encontrada", 404)
    from server.scanner import trickplay_async
    if not trickplay_async(lid):
        return _busy()
    return jsonify(ok=True, scanning=True)


@bp.route("/admin/libraries/<int:lid>/optimize", methods=["POST"])
@admin_required
def lib_optimize(lid):
    """52.10: Otimizar biblioteca: todos os itens sem versão otimizada válida entram na fila (fora da janela de horário)."""
    if not _lib_action(lid):
        return jerr("err.biblioteca_nao_encontrada", 404)
    from server import optimize
    return jsonify(ok=True, queued=optimize.enqueue(optimize.refs_for_library(lid)))


@bp.route("/admin/libraries/examine", methods=["POST"])
@admin_required
def lib_examine_all():
    """29.6: Examinar arquivos de todas as bibliotecas (botão de /admin/libraries) = o mesmo exame de /<id>/examine."""
    if not scan_async(None, manual=True):
        return _busy()
    return jsonify(ok=True, scanning=True)


@bp.route("/admin/libraries/<int:lid>/empty-trash", methods=["POST"])
@admin_required
def lib_empty_trash(lid):
    """29.3 Esvaziar Lixeira = remove itens cujos arquivos sumiram (prune_missing, com a trava da 9.5)."""
    if not _lib_action(lid):
        return jerr("err.biblioteca_nao_encontrada", 404)
    with exclusive() as ok:
        if not ok:
            return _busy()
        removed = prune_missing(lid)
    return jsonify(ok=True, scanning=False, removed=removed)


@bp.route("/admin/libraries/scan", methods=["POST"])
@admin_required
def scan_all():
    scan_async(manual=True)
    if request.args.get("json"):
        return jsonify(ok=True, scanning=True)
    return redirect("/admin" if request.form.get("next") == "panel" else "/admin/libraries")


def _placeholder(title):
    title = (title or "?").strip()
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 450">'
        '<rect width="300" height="450" fill="#282a2d"/>'
        f'<text x="150" y="240" font-family="sans-serif" font-size="120" font-weight="bold" '
        f'fill="#e5a00d" text-anchor="middle">{escape(title[0].upper())}</text>'
        f'<text x="150" y="400" font-family="sans-serif" font-size="22" fill="#eee" '
        f'text-anchor="middle">{escape(title[:26])}</text></svg>'
    )
    return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "private, no-cache"})


@bp.route("/poster/<int:mid>")
@login_required
def poster(mid):
    with get_db() as conn:
        m = conn.execute("SELECT library_id, title, poster FROM media WHERE id = ?", (mid,)).fetchone()
    if not m or not can_access(session["user_id"], m["library_id"]):
        abort(404)
    folder = os.path.abspath(config.POSTERS_DIR)
    if m["poster"] and not m["poster"].startswith("/") and os.path.exists(os.path.join(folder, m["poster"])):
        return send_from_directory(folder, m["poster"], max_age=0)
    return _placeholder(m["title"])  # sem pôster: imagem genérica com o título (nome do arquivo)


# chave -> (chave do rótulo no catálogo, ORDER BY com {d} = ASC|DESC, sentido padrão)
SORTS = {
    "title": ("lib.sort.title", "fold(title) {d}, id {d}", "asc"),
    "year": ("lib.sort.year", "year IS NULL, year {d}, fold(title)", "desc"),
    "added": ("lib.sort.added", "COALESCE((SELECT MAX(e.added_at) FROM episodes e WHERE e.media_id = media.id), added_at) {d}, id {d}", "desc"),
    "played": ("lib.sort.played", "COALESCE((SELECT MAX(p.updated_at) FROM progress p WHERE p.profile_id = :pid AND ((p.item_type = 'movie' AND p.item_id = media.id) OR (p.item_type = 'episode' AND p.item_id IN (SELECT id FROM episodes WHERE media_id = media.id)))), '') {d}, id {d}", "desc"),
}
FILTERS = {"all": "lib.filter.all", "unwatched": "lib.filter.unwatched", "watched": "lib.filter.watched", "progress": "lib.filter.progress"}


def _clean_view(a):
    """Valida ordenação/filtros vindos da URL, do banco ou do cookie antigo -> (sort, dir, filter, genre)."""
    sort = a.get("sort", "title")
    if sort not in SORTS:
        sort = "title"
    d = a.get("dir")
    if d not in ("asc", "desc"):
        d = SORTS[sort][2]
    flt = a.get("filter", "all")
    if flt not in FILTERS:
        flt = "all"
    return sort, d, flt, (a.get("genre") or "").strip()[:100]


def _saved_view(lid):
    """Últimas escolhas deste perfil nesta biblioteca (tabela library_view_prefs) ou None.
    Migração do cookie antigo (38.1): sem linha no banco, usa o cookie sf_lib_<perfil>_<id> uma vez e o grava no banco;
    o library-bar.js apaga o cookie no navegador."""
    pid = session.get("profile_id")
    if not pid:
        return None
    with get_db() as conn:
        r = conn.execute("SELECT sort, dir, filter, genre FROM library_view_prefs WHERE profile_id = ? AND library_id = ?",
                         (pid, lid)).fetchone()
        if r:
            return dict(r)
        from urllib.parse import parse_qs, unquote
        raw = unquote(request.cookies.get(f"sf_lib_{pid}_{lid}") or "")  # o JS gravava com encodeURIComponent
        if not raw:
            return None
        old = {k: v[0] for k, v in parse_qs(raw).items()}
        _store_view(conn, pid, lid, *_clean_view(old))
        return old


def _store_view(conn, pid, lid, sort, d, flt, genre):
    conn.execute(
        "INSERT INTO library_view_prefs (profile_id, library_id, sort, dir, filter, genre) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (profile_id, library_id) DO UPDATE SET sort = excluded.sort, dir = excluded.dir, "
        "filter = excluded.filter, genre = excluded.genre",
        (pid, lid, sort, d, flt, genre),
    )


def _args(lid=None):
    """Ordenação e filtros: da URL; sem nenhum deles na URL, os últimos escolhidos por este perfil nesta biblioteca
    (banco: library_view_prefs, gravado por POST /library/<id>/view-prefs quando o usuário escolhe na barra)."""
    a = request.args
    if lid is not None and not any(k in a for k in ("sort", "dir", "filter", "genre")):
        a = _saved_view(lid) or {}
    return _clean_view(a)


@bp.route("/library/<int:lid>/view-prefs", methods=["POST"])
@login_required
def view_prefs(lid):
    """Salva ordenação/filtros escolhidos na barra da biblioteca para o perfil atual (vale em qualquer dispositivo)."""
    _get_lib(lid)  # 404 se a biblioteca não existe ou o usuário não tem acesso
    pid = session.get("profile_id")
    if not pid:
        return jerr("err.nenhum_perfil_selecionado", 400)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    view = _clean_view({k: v for k, v in body.items() if isinstance(v, str)})
    with get_db() as conn:
        _store_view(conn, pid, lid, *view)
    return jsonify(ok=True)


def _items(lid, lib_type, sort, d, flt, genre):
    """Itens da biblioteca com estado do perfil (assistido, em andamento, pct), já filtrados e ordenados."""
    from server.progress import RESUME_MIN

    pid = session["profile_id"]
    order = SORTS[sort][1].format(d=d.upper())
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, dtitle(library_id, title, original_title) AS shown, year, genres, info, "
            "(SELECT COUNT(*) FROM episodes e WHERE e.media_id = media.id) AS eps, "
            "(SELECT COUNT(*) FROM episodes e JOIN progress p ON p.item_type = 'episode' AND p.item_id = e.id "
            " AND p.profile_id = :pid WHERE e.media_id = media.id AND p.watched = 1) AS eps_seen, "
            "(SELECT COUNT(*) FROM episodes e JOIN progress p ON p.item_type = 'episode' AND p.item_id = e.id "
            " AND p.profile_id = :pid WHERE e.media_id = media.id AND p.watched = 0 AND p.position > :rm) AS eps_part, "
            "COALESCE((SELECT watched FROM progress p WHERE p.profile_id = :pid AND p.item_type = 'movie' AND p.item_id = media.id), 0) AS seen, "
            "COALESCE((SELECT position FROM progress p WHERE p.profile_id = :pid AND p.item_type = 'movie' AND p.item_id = media.id), 0) AS pos "
            f"FROM media WHERE library_id = :lid ORDER BY {order}",
            {"pid": pid, "rm": RESUME_MIN, "lid": lid},
        ).fetchall()
    out = []
    for r in rows:
        gs = [g.strip() for g in (r["genres"] or "").split(",") if g.strip()]
        pct = 0
        if lib_type in ("movie", "video"):
            watched = bool(r["seen"])
            part = not watched and r["pos"] > RESUME_MIN
            if part:
                try:
                    dur = (json.loads(r["info"]) if r["info"] else {}).get("duration") or 0
                except ValueError:
                    dur = 0
                pct = min(100, r["pos"] / dur * 100) if dur else 0
        else:
            watched = bool(r["eps"]) and r["eps_seen"] == r["eps"]
            part = not watched and (r["eps_seen"] > 0 or r["eps_part"] > 0)
            pct = r["eps_seen"] / r["eps"] * 100 if r["eps"] and 0 < r["eps_seen"] < r["eps"] else 0  # 35.20
        out.append({"id": r["id"], "title": r["shown"], "year": r["year"], "genres": gs,
                    "watched": watched, "progress": part, "pct": pct})
    return out


def _filtered(items, flt, genre):
    if flt == "watched":
        items = [i for i in items if i["watched"]]
    elif flt == "unwatched":
        items = [i for i in items if not i["watched"] and not i["progress"]]
    elif flt == "progress":
        items = [i for i in items if i["progress"]]
    if genre:
        items = [i for i in items if genre in i["genres"]]
    return items


def _get_lib(lid):
    if not can_access(session["user_id"], lid):
        abort(404)
    with get_db() as conn:
        lib = conn.execute("SELECT * FROM libraries WHERE id = ?", (lid,)).fetchone()
    if not lib:
        abort(404)
    return lib


@bp.route("/library/<int:lid>")
@login_required
def library(lid):
    """Biblioteca: abas Recomendado/Biblioteca, filtros, ordenação (?sort=&dir=&filter=&genre=&tab=) e contador."""
    from server.progress import continue_watching

    lib = _get_lib(lid)
    sort, d, flt, genre = _args(lid)
    sorts = SORTS
    if lib["type"] == "video":  # 34.5: só Título, Adicionado e Por Último assistido; sem filtro de gênero
        sorts = {k: v for k, v in SORTS.items() if k in ("title", "added", "played")}
        if sort not in sorts:
            sort, d = "title", "asc"
        genre = ""
    from server.collections import library_collections
    from server.playlists import library_playlists

    with get_db() as conn:
        cols = library_collections(conn, lid)
        pls = library_playlists(conn, lid)  # 31.9: listas do usuário nesta biblioteca
        u = conn.execute("SELECT is_admin FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        # 54.15: bibliotecas da barra do celular que têm coleção (o popup só mostra Coleções nelas; admin vê sempre)
        cols_libs = {l["id"] for l in pinned_libraries(session["user_id"]) if library_collections(conn, l["id"])} | ({lid} if cols else set())
    show_cols = bool(u and u["is_admin"]) or bool(cols)  # aba Coleções: admin sempre; usuário só se existir coleção
    tab = request.args.get("tab")
    if tab is None and request.cookies.get("sf_m") == "1":  # 54.14: no celular a página principal de qualquer biblioteca é o Recomendado
        tab = "recommended"
    tab = tab if tab in ("recommended", "collections", "playlists") else "library"
    if (tab == "collections" and not show_cols) or (tab == "playlists" and not pls):
        tab = "library"
    allitems = _items(lid, lib["type"], sort, d, flt, genre)
    if tab == "recommended" and not allitems:  # 56.5: biblioteca sem itens abre direto em Explorar
        tab = "library"
    genres = sorted({g for i in allitems for g in i["genres"]}, key=fold)
    items = _filtered(allitems, flt, genre)
    lib_cols = []  # Modo de Coleta (24.11): "hide" tira os itens da grade e mostra a coleção; "both" mostra a coleção e os itens
    if tab == "library":
        hide = set()
        with get_db() as conn:
            for c in cols:
                mode = (json.loads(c["prefs"]) if c["prefs"] else {}).get("mode")
                if mode not in ("hide", "both"):
                    mode = lib_prefs(lib)["collection_mode"]  # 28.5: "Padrão da biblioteca"
                if mode not in ("hide", "both"):
                    continue
                if flt == "all" and not genre:
                    lib_cols.append(c)
                if mode == "hide":
                    from server.collections import collection_media
                    hide |= {m["id"] for m in collection_media(conn, c["id"])}
        if hide:
            items = [i for i in items if i["id"] not in hide]
    rec = []
    hero = []
    if tab == "recommended":
        from server.home_rows import _left, hero_items

        ids = {i["id"] for i in allitems}
        cont = [c for c in continue_watching(session["user_id"], session["profile_id"]) if c["media_id"] in ids]
        for c in cont:
            c["left"] = _left(c)
        if cont:
            rec.append((i18n.tr("lib.row.continue"), "cont", cont))
        added = _items(lid, lib["type"], "added", "desc", "all", "")[:20]
        if lib["type"] in ("movie", "show"):  # 54.14: destaque do celular = os 8 adicionados mais recentemente nesta biblioteca
            hero = hero_items({"type": "poster", "items": [{"id": i["id"], "type": lib["type"], "title": i["title"], "year": i["year"]} for i in added[:8]]})
        rec.append((i18n.tr("lib.row.recent"), "items", added))
        if cols:
            rec.append((i18n.tr("home.tab.collections"), "cols", cols))
        counts = {}
        for i in allitems:
            for g in i["genres"]:
                counts[g] = counts.get(g, 0) + 1
        for g in sorted(counts, key=lambda g: (-counts[g], fold(g)))[:3]:
            rec.append((g, "items", [i for i in allitems if g in i["genres"]][:20]))
    return render_template(
        "library.html", lib=lib, items=items, lib_cols=lib_cols, total=len(items) + len(lib_cols), tab=tab, sort=sort, dir=d, flt=flt, genre=genre,
        sorts=sorts, filters=FILTERS, genres=genres, rec=rec, server_name="StarFlix", cols=cols, show_cols=show_cols, pls=pls, hero=hero, cols_libs=cols_libs,
    )


@bp.route("/library/<int:lid>/rows")
@login_required
def rows(lid):
    """31.10: dados extras dos itens para a Visualização em Detalhes e a Exibição em Tabela (id -> campos)."""
    lib = _get_lib(lid)
    kind = "movie" if lib["type"] in ("movie", "video") else "show"

    def info(raw):
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}

    out = {}
    with get_db() as conn:
        for m in conn.execute("SELECT id, overview, rating, release_date, content_rating, added_at, info FROM media WHERE library_id = ?", (lid,)):
            i = info(m["info"])
            out[m["id"]] = {"o": m["overview"] or "", "d": i.get("duration") or 0, "rt": m["rating"], "rd": m["release_date"] or "",
                            "cc": m["content_rating"] or "", "ad": (m["added_at"] or "")[:10], "res": (i.get("video") or {}).get("height") or 0, "s": 0}
        if kind == "show":
            for e in conn.execute("SELECT e.media_id, e.info FROM episodes e JOIN media m ON m.id = e.media_id WHERE m.library_id = ?", (lid,)):
                i = info(e["info"])
                r = out.get(e["media_id"])
                if r:
                    r["d"] += i.get("duration") or 0
                    r["res"] = max(r["res"], (i.get("video") or {}).get("height") or 0)
        for st in conn.execute("SELECT item_id, stars FROM stars WHERE profile_id = ? AND item_type = ?", (session["profile_id"], kind)):
            if st["item_id"] in out:
                out[st["item_id"]]["s"] = st["stars"] or 0
    return jsonify(rows=out)


@bp.route("/library/<int:lid>/play")
@login_required
def library_play(lid):
    """▶ Reproduzir tudo / ⤮ Aleatório (?random=1) respeitando filtros e ordenação atuais."""
    import random

    lib = _get_lib(lid)
    sort, d, flt, genre = _args(lid)
    items = _filtered(_items(lid, lib["type"], sort, d, flt, genre), flt, genre)
    pl = request.args.get("playlist", "")
    if pl.isascii() and pl.isdigit():  # 31.4: ?playlist=<id> reproduz a lista (ordem da lista; só do próprio usuário)
        from server.playlists import get_playlist, playlist_ids
        with get_db() as conn:
            p = get_playlist(conn, int(pl))
            if p["library_id"] != lid:
                abort(404)
            order = playlist_ids(conn, p)
        state = {i["id"]: i for i in _items(lid, lib["type"], "title", "asc", "all", "")}
        items = [state[m] for m in order if m in state]
    if not items:
        return redirect(f"/library/{lid}")
    rnd = request.args.get("random") == "1"
    if lib["type"] in ("movie", "video"):
        m = random.choice(items) if rnd else next((i for i in items if not i["watched"]), items[0])
        return redirect(f"/watch/movie/{m['id']}")
    show = random.choice(items) if rnd else next((i for i in items if not i["watched"]), items[0])
    with get_db() as conn:
        eps = conn.execute(
            "SELECT e.id, COALESCE(p.watched, 0) AS watched FROM episodes e "
            "LEFT JOIN progress p ON p.item_type = 'episode' AND p.item_id = e.id AND p.profile_id = ? "
            "WHERE e.media_id = ? ORDER BY e.season = 0, e.season, e.episode",
            (session["profile_id"], show["id"]),
        ).fetchall()
    if not eps:
        return redirect(f"/show/{show['id']}")
    ep = random.choice(eps) if rnd else next((e for e in eps if not e["watched"]), eps[0])
    return redirect(f"/watch/episode/{ep['id']}")
