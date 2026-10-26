import json
import os

from flask import Blueprint, abort, jsonify, request

from server.auth import admin_required
from server.db import get_db
from server.library_access import grant_library
from server.i18n import E, jerr

bp = Blueprint("admin_edit", __name__)

TABS = {
    "movie": ["general", "tags", "labels", "poster", "backdrop", "logo", "square", "info", "advanced"],
    "show": ["general", "tags", "labels", "poster", "backdrop", "logo", "square", "info", "advanced"],
    "video": ["general", "poster"],  # 34.6: só título e miniatura
    "season": ["general", "poster", "backdrop", "info", "advanced"],
    "episode": ["general", "tags", "poster", "info"],
    "collection": ["general", "labels", "poster", "backdrop", "logo", "square", "info", "advanced"],
}
CREDIT_KEYS = {"director": "directors", "writer": "writers", "producer": "producers"}


def _json(v):
    try:
        return json.loads(v) if v else {}
    except ValueError:
        return {}


def _tags(conn, mid):
    out = {"genres": [], "country": [], "label": []}
    for r in conn.execute("SELECT kind, name FROM tags WHERE media_id = ? ORDER BY id", (mid,)):
        out["genres" if r["kind"] == "genre" else r["kind"]].append(r["name"])
    return out


def _credits(conn, mid, eid=None):
    out = {v: [] for v in CREDIT_KEYS.values()}
    q = "AND c.episode_id = ?" if eid else "AND c.episode_id IS NULL"
    rows = conn.execute(
        f"SELECT c.role, p.name FROM credits c JOIN people p ON p.id = c.person_id "
        f"WHERE c.media_id = ? {q} AND c.role != 'cast' ORDER BY c.ord", (mid, eid) if eid else (mid,))
    for r in rows:
        out[CREDIT_KEYS[r["role"]]].append(r["name"])
    return out


def _files(rows):
    out = []
    for r in rows:
        info = _json(r["info"])
        try:
            size = os.path.getsize(r["path"])
        except OSError:
            size = None
        out.append({"path": r["path"], "info": info, "size": size})
    return out


@bp.route("/admin/item/<kind>/<ref>/edit")
@admin_required
def item_edit(kind, ref):
    if kind not in TABS:
        abort(404)
    with get_db() as conn:
        if kind == "video":
            m = conn.execute("SELECT m.*, l.type FROM media m JOIN libraries l ON l.id = m.library_id WHERE m.id = ?",
                             (ref,)).fetchone()
            if not m or m["type"] != "video":
                abort(404)
            data = {"title": f"Editar {m['title']}", "fields": {"title": m["title"]}, "locks": _json(m["locks"]), "prefs": {},
                    "tags": {}, "images": {"poster": m["poster"]}, "tmdb_id": None, "files": []}
        elif kind in ("movie", "show"):
            m = conn.execute("SELECT m.*, l.type FROM media m JOIN libraries l ON l.id = m.library_id WHERE m.id = ?",
                             (ref,)).fetchone()
            if not m or m["type"] != kind:
                abort(404)
            title = m["title"]
            fields = {k: m[k] for k in ("title", "sort_title", "original_title", "release_date", "content_rating",
                                        "rating", "overview")}
            tags = {**_tags(conn, m["id"]), **_credits(conn, m["id"])}
            if kind == "movie":
                files = _files([m]) if m["path"] else []
            else:
                files = _files(conn.execute("SELECT path, info FROM episodes WHERE media_id = ? ORDER BY season, episode",
                                            (m["id"],)).fetchall())
            data = {"title": f"Editar {title}", "fields": fields, "locks": _json(m["locks"]), "prefs": _json(m["prefs"]),
                    "tags": tags, "images": {k: m[k] for k in ("poster", "backdrop", "logo", "square")},
                    "tmdb_id": m["tmdb_id"], "files": files}
        elif kind == "season":
            try:
                mid, n = (int(x) for x in ref.split("-"))
            except ValueError:
                abort(404)
            m = conn.execute("SELECT id, title FROM media WHERE id = ?", (mid,)).fetchone()
            if not m:
                abort(404)
            conn.execute("INSERT OR IGNORE INTO seasons (media_id, season) VALUES (?, ?)", (mid, n))
            s = conn.execute("SELECT * FROM seasons WHERE media_id = ? AND season = ?", (mid, n)).fetchone()
            files = _files(conn.execute("SELECT path, info FROM episodes WHERE media_id = ? AND season = ? "
                                        "ORDER BY episode", (mid, n)).fetchall())
            data = {"title": f"Editar {m['title']} - {'Especiais' if n == 0 else f'Temporada {n}'}",
                    "fields": {"title": s["title"], "overview": s["overview"]}, "locks": _json(s["locks"]),
                    "prefs": _json(s["prefs"]), "tags": {}, "images": {"poster": s["poster"], "backdrop": s["backdrop"]},
                    "tmdb_id": None, "files": files}
        elif kind == "collection":
            c = conn.execute("SELECT * FROM collections WHERE id = ?", (ref,)).fetchone()
            if not c:
                abort(404)
            files = []  # Informações: caminho de cada item (filme = arquivo; série = pasta comum dos episódios)
            from server.collections import collection_media
            for m in collection_media(conn, ref):
                if m["path"]:
                    files += _files([m])
                    continue
                eps = conn.execute("SELECT path, info FROM episodes WHERE media_id = ?", (m["id"],)).fetchall()
                if not eps:
                    continue
                try:
                    folder = os.path.commonpath([e["path"] for e in eps])
                except ValueError:
                    folder = eps[0]["path"]
                got = _files(eps)
                files.append({"path": folder, "size": sum(f["size"] or 0 for f in got),
                              "info": {"duration": sum((f["info"] or {}).get("duration") or 0 for f in got)}})
            data = {"title": E("ae.title_collection", title=c["title"]),
                    "fields": {"title": c["title"], "sort_title": c["sort_title"], "content_rating": c["content_rating"],
                               "overview": c["summary"]},
                    "locks": _json(c["locks"]), "prefs": _json(c["prefs"]),
                    "tags": {"label": json.loads(c["labels"]) if c["labels"] else []},
                    "images": {k: c[k] for k in ("poster", "backdrop", "logo", "square")}, "tmdb_id": None, "files": files}
        else:
            e = conn.execute("SELECT e.*, m.title AS show, m.tmdb_id FROM episodes e JOIN media m ON m.id = e.media_id "
                             "WHERE e.id = ?", (ref,)).fetchone()
            if not e:
                abort(404)
            fields = {k: e[k] for k in ("title", "sort_title", "air_date", "content_rating", "rating", "overview")}
            data = {"title": E("ae.title_episode", show=e["show"], title=e["title"] or E("det.episode_n", n=e["episode"]), s=e["season"], e=e["episode"]),
                    "fields": fields, "locks": _json(e["locks"]), "prefs": {},
                    "tags": _credits(conn, e["media_id"], e["id"]), "images": {"poster": e["still"], "backdrop": None},
                    "tmdb_id": e["tmdb_id"], "files": _files([e])}
    data.update(kind=kind, ref=ref, tabs=TABS[kind])
    if kind in ("movie", "show"):
        data["library_id"] = m["library_id"]  # usado por "Adicionar à coleção…" (25.2)
    return jsonify(data)


# campos editáveis por tipo (aba Geral); tipo -> (tabela, {campo: conversor})
def _txt(v):
    v = (v or "").strip() if isinstance(v, str) else v
    return v or None


def _rate(v):
    if v in (None, ""):
        return None
    f = float(v)
    if not 0 <= f <= 10:
        raise ValueError
    return round(f, 1)


def _date(v):
    v = _txt(v)
    if v and not (len(v) == 10 and v[4] == "-" and v[7] == "-" and v[:4].isdigit()):
        raise ValueError
    return v


LANGS = ["", "pt", "en", "es", "fr", "de", "it", "ja", "ko", "zh", "ru"]
PREFS = {  # chave -> valores aceitos ("" = padrão); consumidos pelo player (23.27)
    "audio_lang": LANGS, "sub_lang": LANGS, "sub_mode": ["", "off", "forced", "foreign"],
    "mode": ["", "hide", "both"],  # Modo de Coleta da coleção (24.11)
    "meta_lang": ["", "pt-BR", "en-US", "es-ES", "fr-FR", "de-DE", "it-IT", "ja-JP"], "use_original": ["", "1", "0"],
}
TAG_LOCKS = {"genres", "country", "director", "writer", "producer"}
ROLE_OF = {"directors": "director", "writers": "writer", "producers": "producer"}


def _names(v):
    out = []
    for n in v if isinstance(v, list) else []:
        n = str(n).strip()[:120]
        if n and n not in out:
            out.append(n)
    return out[:100]


def _save_tags(conn, kind, rid, tags):
    """Grava chips das abas Tags/Rótulos: gêneros/país/rótulos em `tags`, equipe em `credits` (pessoa por nome)."""
    if kind == "episode":
        mid = conn.execute("SELECT media_id FROM episodes WHERE id = ?", (rid,)).fetchone()["media_id"]
        eid = rid
    else:
        mid, eid = rid, None
    for key, kindname in (("genres", "genre"), ("country", "country"), ("label", "label")):
        if key in tags and eid is None:
            names = _names(tags[key])
            conn.execute("DELETE FROM tags WHERE media_id = ? AND kind = ?", (mid, kindname))
            for n in names:
                conn.execute("INSERT OR IGNORE INTO tags (media_id, kind, name) VALUES (?, ?, ?)", (mid, kindname, n))
            if key == "genres":
                conn.execute("UPDATE media SET genres = ? WHERE id = ?", (", ".join(names) or None, mid))
    for key, role in ROLE_OF.items():
        if key not in tags:
            continue
        if eid:
            conn.execute("DELETE FROM credits WHERE episode_id = ? AND role = ?", (eid, role))
        else:
            conn.execute("DELETE FROM credits WHERE media_id = ? AND episode_id IS NULL AND role = ?", (mid, role))
        for i, n in enumerate(_names(tags[key])):
            p = conn.execute("SELECT id FROM people WHERE name = ? ORDER BY tmdb_id IS NULL, id LIMIT 1", (n,)).fetchone()
            pid = p["id"] if p else conn.execute("INSERT INTO people (name) VALUES (?)", (n,)).lastrowid
            conn.execute("INSERT INTO credits (media_id, episode_id, person_id, role, ord) VALUES (?, ?, ?, ?, ?)",
                         (mid, eid, pid, role, i))
    metadata.prune_people()


GENERAL = {
    "video": ("media", {"title": _txt}),
    "movie": ("media", {"title": _txt, "sort_title": _txt, "original_title": _txt, "release_date": _date,
                        "content_rating": _txt, "rating": _rate, "overview": _txt}),
    "show": ("media", {"title": _txt, "sort_title": _txt, "original_title": _txt, "release_date": _date,
                       "content_rating": _txt, "rating": _rate, "overview": _txt}),
    "season": ("seasons", {"title": _txt, "overview": _txt}),
    "episode": ("episodes", {"title": _txt, "sort_title": _txt, "air_date": _date, "content_rating": _txt,
                             "rating": _rate, "overview": _txt}),
    "collection": ("collections", {"title": _txt, "sort_title": _txt, "content_rating": _txt, "overview": _txt}),
}
COLUMN = {"collection": {"overview": "summary"}}  # campo do formulário -> coluna


@bp.route("/admin/item/<kind>/<ref>/edit", methods=["POST"])
@admin_required
def item_save(kind, ref):
    if kind not in GENERAL:
        abort(404)
    body = request.get_json(silent=True) or {}
    table, allowed = GENERAL[kind]
    fields, locks_in = body.get("fields") or {}, body.get("locks") or {}
    with get_db() as conn:
        if kind == "season":
            try:
                mid, n = (int(x) for x in ref.split("-"))
            except ValueError:
                abort(404)
            row = conn.execute("SELECT id, locks FROM seasons WHERE media_id = ? AND season = ?", (mid, n)).fetchone()
        else:
            row = conn.execute(f"SELECT id, locks FROM {table} WHERE id = ?", (ref,)).fetchone()
        if not row:
            abort(404)
        locks = _json(row["locks"])
        sets, vals = [], []
        try:
            for k, v in fields.items():
                if k not in allowed:
                    continue
                v = allowed[k](v)
                if k == "title" and v is None:
                    continue  # título nunca fica vazio
                if kind == "collection" and k == "title":
                    from server.collections import clean_title
                    v = clean_title(v)
                    if conn.execute("SELECT 1 FROM collections WHERE library_id = (SELECT library_id FROM collections WHERE id = ?) "
                                    "AND casefold(title) = casefold(?) AND id != ?", (row["id"], v, row["id"])).fetchone():
                        return jerr("err.ja_existe_colecao_esse_nome", 409)
                sets.append(f"{COLUMN.get(kind, {}).get(k, k)} = ?")
                vals.append(v)
                if k == "release_date" and table == "media":
                    sets.append("year = ?")
                    vals.append(int(v[:4]) if v else None)
        except (ValueError, TypeError):
            return jerr("err.valor_invalido", 400)
        for k, v in locks_in.items():
            if k in allowed or k in TAG_LOCKS:
                if v:
                    locks[k] = 1
                else:
                    locks.pop(k, None)
        sets.append("locks = ?")
        vals.append(json.dumps(locks) if locks else None)
        conn.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id = ?", (*vals, row["id"]))
        if isinstance(body.get("prefs"), dict) and table in ("media", "seasons", "collections"):
            prefs = _json(conn.execute(f"SELECT prefs FROM {table} WHERE id = ?", (row["id"],)).fetchone()["prefs"])
            for k, v in body["prefs"].items():
                if k in PREFS and str(v) in PREFS[k]:
                    if v:
                        prefs[k] = str(v)
                    else:
                        prefs.pop(k, None)
            conn.execute(f"UPDATE {table} SET prefs = ? WHERE id = ?", (json.dumps(prefs) if prefs else None, row["id"]))
        if kind == "collection" and isinstance(body.get("tags"), dict) and "label" in body["tags"]:
            conn.execute("UPDATE collections SET labels = ? WHERE id = ?",
                         (json.dumps(_names(body["tags"]["label"]), ensure_ascii=False) or None, row["id"]))
        elif isinstance(body.get("tags"), dict) and kind not in ("season", "collection"):
            _save_tags(conn, kind, row["id"], body["tags"])
    return jsonify(ok=True)


# ---------- Imagens (23.20) ----------
import ipaddress
import os
import socket
from urllib.parse import urlparse

import requests

import config
from server import metadata

MAX_IMG = 10 * 1024 * 1024
SLOTS = {"poster", "backdrop", "logo", "square"}
SIZES = {"poster": config.TMDB_IMG_SIZE, "backdrop": "w1280", "logo": "w500", "square": "w500"}


def _sniff(b):
    if b[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return ".webp"
    return None


def _target(conn, kind, ref, slot):
    """-> dict(table, id, col, base, lock, tmdb, tv_path, library_id) do item/slot; 404 se não existe/não suportado."""
    if kind in ("movie", "show", "video"):
        if slot not in SLOTS or (kind == "video" and slot != "poster"):
            abort(404)
        m = conn.execute("SELECT m.id, m.tmdb_id, m.library_id, m.locks, l.type FROM media m "
                         "JOIN libraries l ON l.id = m.library_id WHERE m.id = ?", (ref,)).fetchone()
        if not m or m["type"] != kind:
            abort(404)
        sub = {"poster": "", "backdrop": "bd/", "logo": "logo/", "square": "square/"}[slot]
        base = f"{sub}{m['id']}"
        return dict(table="media", id=m["id"], col=slot, base=base, lock=slot, tmdb=m["tmdb_id"], kind=kind,
                    locks=m["locks"], size=SIZES[slot], list={"poster": "posters", "backdrop": "backdrops",
                                                              "logo": "logos", "square": "posters"}[slot])
    if kind == "collection":
        if slot not in SLOTS:
            abort(404)
        c = conn.execute("SELECT id, locks FROM collections WHERE id = ?", (ref,)).fetchone()
        if not c:
            abort(404)
        sub = {"poster": "", "backdrop": "-bd", "logo": "-logo", "square": "-sq"}[slot]
        return dict(table="collections", id=c["id"], col=slot, base=f"col/{c['id']}{sub}", lock=slot, tmdb=None,
                    kind="collection", locks=c["locks"], size=None, list=None)
    if kind == "season":
        if slot not in ("poster", "backdrop"):
            abort(404)
        try:
            mid, n = (int(x) for x in ref.split("-"))
        except ValueError:
            abort(404)
        m = conn.execute("SELECT id, tmdb_id FROM media WHERE id = ?", (mid,)).fetchone()
        conn.execute("INSERT OR IGNORE INTO seasons (media_id, season) VALUES (?, ?)", (mid, n))
        s = conn.execute("SELECT id, locks FROM seasons WHERE media_id = ? AND season = ?", (mid, n)).fetchone()
        if not m or not s:
            abort(404)
        return dict(table="seasons", id=s["id"], col=slot, base=f"season/{mid}-{n}" + ("-bd" if slot == "backdrop" else ""),
                    lock=slot, tmdb=m["tmdb_id"], kind="season", season=n, locks=s["locks"],
                    size="w342" if slot == "poster" else "w1280", list="posters" if slot == "poster" else "backdrops")
    if kind == "episode":
        if slot != "poster":
            abort(404)
        e = conn.execute("SELECT e.id, e.season, e.episode, e.locks, m.tmdb_id FROM episodes e "
                         "JOIN media m ON m.id = e.media_id WHERE e.id = ?", (ref,)).fetchone()
        if not e:
            abort(404)
        return dict(table="episodes", id=e["id"], col="still", base=f"still/{e['id']}", lock="still", tmdb=e["tmdb_id"],
                    kind="episode", season=e["season"], episode=e["episode"], locks=e["locks"], size="w300", list="stills")
    abort(404)


@bp.route("/admin/item/<kind>/<ref>/images/<slot>")
@admin_required
def item_images(kind, ref, slot):
    """Candidatas do TMDB para o slot (lista de {thumb, path})."""
    with get_db() as conn:
        t = _target(conn, kind, ref, slot)
        if t["kind"] == "collection":  # candidatas = imagens dos próprios itens da coleção
            from server.collections import collection_media
            route = {"poster": "poster", "backdrop": "backdrop", "logo": "logo", "square": "square"}[slot]
            rows = collection_media(conn, t["id"])
            return jsonify(items=[{"thumb": f"/{route}/{r['id']}", "media": r["id"]} for r in rows if r[slot]])
    if not config.TMDB_API_KEY or not t["tmdb"]:
        return jsonify(items=[])
    try:
        if t["kind"] == "episode":
            d = metadata.tmdb_get(f"/tv/{t['tmdb']}/season/{t['season']}/episode/{t['episode']}/images", language=None)
        elif t["kind"] == "season" and slot == "poster":
            d = metadata.tmdb_get(f"/tv/{t['tmdb']}/season/{t['season']}/images", language=None,
                                  include_image_language="pt,en,null")
        else:
            d = metadata.tmdb_get(f"/{'movie' if t['kind'] == 'movie' else 'tv'}/{t['tmdb']}/images", language=None,
                                  include_image_language="pt,en,null")
    except requests.RequestException:
        return jerr("err.falha_consultar_tmdb", 502)
    items = d.get(t["list"]) or []
    return jsonify(items=[{"thumb": metadata.TMDB_IMG + "w300" + i["file_path"], "path": i["file_path"]}
                          for i in items[:60] if i.get("file_path")])


def _public_ip(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


def _fetch_url(url):
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname or not _public_ip(u.hostname):
        raise ValueError(E("err.url_invalida_ou_nao_permitida"))
    r = requests.get(url, timeout=15, stream=True, allow_redirects=False, headers={"User-Agent": "StarFlix"})
    try:
        if r.status_code != 200:
            raise ValueError(E("err.nao_foi_possivel_baixar_imagem"))
        buf = b""
        for chunk in r.iter_content(65536):
            buf += chunk
            if len(buf) > MAX_IMG:
                raise ValueError(E("err.imagem_maior_que_10_mb"))
        return buf
    finally:
        r.close()


def _store(rel, data):
    path = os.path.join(config.POSTERS_DIR, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


@bp.route("/admin/item/<kind>/<ref>/image/<slot>", methods=["POST"])
@admin_required
def item_image_set(kind, ref, slot):
    """Define a imagem do slot: upload (file), URL (url), candidata do TMDB (path) ou limpa (clear=1). Trava o campo."""
    with get_db() as conn:
        t = _target(conn, kind, ref, slot)
        old = conn.execute(f"SELECT {t['col']} AS v FROM {t['table']} WHERE id = ?", (t["id"],)).fetchone()["v"]
        new = None
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
                new = t["base"] + ext
                _store(new, data)
            elif request.form.get("media") and t["kind"] == "collection":
                from server.images import _local
                from server.collections import collection_media
                src = next((m for m in collection_media(conn, t["id"]) if m["id"] == int(request.form["media"])), None)
                src = {"v": src[slot]} if src else None
                f = _local(src["v"]) if src else None
                if not f:
                    raise ValueError(E("msg.imagem_indisponivel"))
                with open(os.path.join(f[0], f[1]), "rb") as fh:
                    data = fh.read(MAX_IMG + 1)
                ext = _sniff(data)
                if not ext or len(data) > MAX_IMG:
                    raise ValueError(E("err.use_jpg_png_ou_webp"))
                new = t["base"] + ext
                _store(new, data)
            elif request.form.get("url"):
                data = _fetch_url(request.form["url"].strip())
                ext = _sniff(data)
                if not ext:
                    raise ValueError(E("err.use_jpg_png_ou_webp"))
                new = t["base"] + ext
                _store(new, data)
            elif request.form.get("path", "").startswith("/"):
                if not t["tmdb"]:
                    raise ValueError(E("err.item_sem_ligacao_tmdb"))
                new = t["base"] + (os.path.splitext(request.form["path"])[1].lower() or ".jpg")
                if metadata._download(request.form["path"], t["size"], new) is not True:
                    raise ValueError(E("err.falha_baixar_tmdb"))
            else:
                raise ValueError(E("err.nada_aplicar"))
        except ValueError as ex:
            return jerr(ex, 400)
        except (requests.RequestException, OSError):
            return jerr("err.falha_obter_imagem", 502)
        if old and old != new:
            metadata.remove_local(old)
        locks = _json(t["locks"])
        locks[t["lock"]] = 1
        # episódio: '' (não NULL) = "sem imagem, não gerar frame"; demais: NULL
        empty = "" if t["table"] == "episodes" else None
        conn.execute(f"UPDATE {t['table']} SET {t['col']} = ?, locks = ? WHERE id = ?",
                     (new if new else empty, json.dumps(locks), t["id"]))
    return jsonify(ok=True, name=new)


# ---------- Ações do menu "⋯" (23.25) ----------
from server import markers as markers_mod, probe as probe_mod
from server.admin_media import do_match


def _scope(conn, kind, ref):
    """-> (media_id|None, [(table, id, path)]) dos arquivos do item; 404 se não existe."""
    if kind in ("movie", "video"):
        m = conn.execute("SELECT id, path FROM media WHERE id = ?", (ref,)).fetchone()
        if not m:
            abort(404)
        return m["id"], [("media", m["id"], m["path"])] if m["path"] else []
    if kind == "episode":
        e = conn.execute("SELECT id, media_id, path FROM episodes WHERE id = ?", (ref,)).fetchone()
        if not e:
            abort(404)
        return e["media_id"], [("episodes", e["id"], e["path"])]
    if kind == "show":
        if not conn.execute("SELECT 1 FROM media WHERE id = ?", (ref,)).fetchone():
            abort(404)
        rows = conn.execute("SELECT id, path FROM episodes WHERE media_id = ?", (ref,)).fetchall()
        return int(ref), [("episodes", r["id"], r["path"]) for r in rows]
    if kind == "season":
        try:
            mid, n = (int(x) for x in ref.split("-"))
        except ValueError:
            abort(404)
        rows = conn.execute("SELECT id, path FROM episodes WHERE media_id = ? AND season = ?", (mid, n)).fetchall()
        return mid, [("episodes", r["id"], r["path"]) for r in rows]
    abort(404)


@bp.route("/admin/item/<kind>/<ref>/analyze", methods=["POST"])
@admin_required
def item_analyze(kind, ref):
    """Refaz o ffprobe dos arquivos do item."""
    with get_db() as conn:
        _, files = _scope(conn, kind, ref)
    ok = 0
    for table, id_, path in files:
        try:
            info = probe_mod.probe(path)
        except (OSError, ValueError, Exception):
            info = None
        if info:
            with get_db() as conn:
                conn.execute(f"UPDATE {table} SET info = ? WHERE id = ?", (json.dumps(info), id_))
                if table == "episodes":
                    markers_mod.sync_episode(conn, id_, info)  # 48.1
            ok += 1
    return jsonify(ok=True, analyzed=ok, total=len(files))


@bp.route("/admin/item/<kind>/<ref>/refresh", methods=["POST"])
@admin_required
def item_refresh(kind, ref):
    """Atualizar metadados: refaz a correspondência com o tmdb_id atual."""
    if kind not in ("movie", "show"):
        abort(404)
    with get_db() as conn:
        m = conn.execute("SELECT tmdb_id FROM media WHERE id = ?", (ref,)).fetchone()
    if not m:
        abort(404)
    if not m["tmdb_id"]:
        return jerr("err.item_sem_correspondencia_tmdb_use", 400)
    from server.admin_media import match_async  # 35.19: sem modal; a capa gira e atualiza sozinha
    return match_async(int(ref), m["tmdb_id"])


@bp.route("/admin/item/<kind>/<ref>/examine", methods=["POST"])
@admin_required
def item_examine(kind, ref):
    """46.4: Examinar arquivos de um filme/série (só ele); 202 e segue em segundo plano, a capa gira até terminar."""
    if kind not in ("movie", "show"):
        abort(404)
    with get_db() as conn:
        m = conn.execute("SELECT m.id, m.library_id FROM media m JOIN libraries l ON l.id = m.library_id "
                         "WHERE m.id = ? AND l.type IN ('movie', 'show')", (ref,)).fetchone()
    if not m:
        abort(404)
    from server.scanner import examine_item_async
    if not examine_item_async(m["library_id"], m["id"]):
        return jerr("err.ja_ha_exame_andamento", 409)
    return jsonify(ok=True, pending=True), 202


@bp.route("/admin/item/<kind>/<ref>/trickplay", methods=["POST"])
@admin_required
def item_trickplay(kind, ref):
    """49.2: Gerar miniaturas de um filme/série (só ele); 202 e segue em segundo plano."""
    if kind not in ("movie", "show"):
        abort(404)
    with get_db() as conn:
        m = conn.execute("SELECT id, library_id FROM media WHERE id = ?", (ref,)).fetchone()
    if not m:
        abort(404)
    from server.scanner import trickplay_async
    if not trickplay_async(m["library_id"], m["id"]):
        return jerr("err.ja_ha_exame_andamento", 409)
    return jsonify(ok=True, pending=True), 202


@bp.route("/admin/item/<kind>/<ref>/optimize", methods=["POST"])
@admin_required
def item_optimize(kind, ref):
    """52.10: Otimizar este item (filme, série, temporada ou episódio): entra na fila na hora, fora da janela de horário."""
    from server import optimize
    with get_db() as conn:
        _, files = _scope(conn, kind, ref)
    return jsonify(ok=True, queued=optimize.enqueue(optimize.refs_from_files(files)))


@bp.route("/admin/item/<kind>/<ref>/optimize/remove", methods=["POST"])
@admin_required
def item_optimize_remove(kind, ref):
    """52.10: Remover versão otimizada (arquivo e linha) do item."""
    from server import optimize
    with get_db() as conn:
        _, files = _scope(conn, kind, ref)
    return jsonify(ok=True, removed=optimize.remove_refs(optimize.refs_from_files(files)))


@bp.route("/admin/item/<kind>/<ref>/history")
@admin_required
def item_history(kind, ref):
    with get_db() as conn:
        _, files = _scope(conn, kind, ref)
        ids = {"movie": [], "episode": []}
        for table, id_, _p in files:
            ids["movie" if table == "media" else "episode"].append(id_)
        rows = []
        for typ, lst in ids.items():
            for i in range(0, len(lst), 500):
                part = lst[i:i + 500]
                rows += conn.execute(
                    f"SELECT p.item_type, p.item_id, p.position, p.watched, p.updated_at, pr.name AS profile, "
                    f"e.season, e.episode, e.title FROM progress p JOIN profiles pr ON pr.id = p.profile_id "
                    f"LEFT JOIN episodes e ON p.item_type = 'episode' AND e.id = p.item_id "
                    f"WHERE p.item_type = ? AND p.item_id IN ({','.join('?' * len(part))})", (typ, *part)).fetchall()
    rows.sort(key=lambda r: r["updated_at"] or "", reverse=True)
    return jsonify(items=[{"profile": r["profile"], "watched": bool(r["watched"]), "position": r["position"],
                           "at": r["updated_at"],
                           "episode": (f"T{r['season']} E{r['episode']}" + (f" — {r['title']}" if r["title"] else ""))
                           if r["item_type"] == "episode" else None} for r in rows[:300]])


@bp.route("/admin/matched")
@admin_required
def matched_ids():
    """35.2: ids de filmes/séries com correspondência (tmdb_id > 0); o menu só oferece Remover Correspondência a eles."""
    with get_db() as conn:
        return jsonify(ids=[r[0] for r in conn.execute("SELECT id FROM media WHERE tmdb_id > 0")])


@bp.route("/admin/item/<kind>/<ref>/unmatch", methods=["POST"])
@admin_required
def item_unmatch(kind, ref):
    """Remover Correspondência (25.4): desvincula do TMDB (tmdb_id = 0 = sem correspondência, o scan não busca de novo)
    e limpa os dados que vieram dele; campos travados e a Arte Quadrada ficam. Não mexe em arquivos do disco."""
    if kind not in ("movie", "show"):
        abort(404)
    names = []
    with get_db() as conn:
        m = conn.execute("SELECT m.*, l.type FROM media m JOIN libraries l ON l.id = m.library_id WHERE m.id = ?",
                         (ref,)).fetchone()
        if not m or m["type"] != kind:
            abort(404)
        if (m["tmdb_id"] or 0) <= 0:
            return jerr("err.este_item_nao_tem_correspondencia", 400)
        mid, locks = m["id"], _json(m["locks"])
        sets, vals = ["tmdb_id = 0", "tvdb_id = NULL", "meta_ok = NULL"], []
        for col in ("overview", "genres", "original_title", "release_date", "content_rating", "rating", "tagline",
                    "imdb_id", "imdb_rating", "rt_rating"):
            if not locks.get(col):
                sets.append(f"{col} = NULL")
        for col in ("poster", "backdrop", "logo"):
            if not locks.get(col):
                sets.append(f"{col} = NULL")
                names.append(m[col])
        if kind == "movie":  # filme volta ao título/ano do nome do arquivo; série mantém título e ano (chave de ligação dos episódios)
            from server.scanner import parse_movie_name
            title, year = parse_movie_name(m["path"]) if m["path"] else (m["title"], m["year"])
            if not locks.get("title"):
                sets.append("title = ?")
                vals.append(title)
            if not locks.get("release_date"):
                sets.append("year = ?")
                vals.append(year)
        conn.execute(f"UPDATE media SET {', '.join(sets)} WHERE id = ?", (*vals, mid))
        for kind_tag, lock in (("genre", "genres"), ("country", "country")):
            if not locks.get(lock):
                conn.execute("DELETE FROM tags WHERE media_id = ? AND kind = ?", (mid, kind_tag))
        for role in ("cast", "director", "writer", "producer"):
            if not locks.get(role):
                conn.execute("DELETE FROM credits WHERE media_id = ? AND episode_id IS NULL AND role = ?", (mid, role))
        conn.execute("DELETE FROM reviews WHERE media_id = ?", (mid,))
        conn.execute("DELETE FROM related WHERE media_id = ?", (mid,))
        if kind == "show":
            names += [r[0] for r in conn.execute("SELECT poster FROM seasons WHERE media_id = ? AND locks IS NULL", (mid,))]
            names += [r[0] for r in conn.execute("SELECT backdrop FROM seasons WHERE media_id = ? AND locks IS NULL", (mid,))]
            conn.execute("DELETE FROM seasons WHERE media_id = ? AND locks IS NULL", (mid,))
            names += [r[0] for r in conn.execute("SELECT still FROM episodes WHERE media_id = ? AND locks IS NULL", (mid,))]
            conn.execute("DELETE FROM credits WHERE media_id = ? AND episode_id IN "
                         "(SELECT id FROM episodes WHERE media_id = ? AND locks IS NULL)", (mid, mid))
            conn.execute("UPDATE episodes SET title = NULL, overview = NULL, still = NULL, air_date = NULL, "
                         "content_rating = NULL, rating = NULL WHERE media_id = ? AND locks IS NULL", (mid,))
    for name in names:
        metadata.remove_local(name)
    metadata.prune_people()
    return jsonify(ok=True)


@bp.route("/admin/item/<kind>/<ref>/delete", methods=["POST"])
@admin_required
def item_delete(kind, ref):
    """Remove do banco (não do disco) e apaga as imagens locais; o próximo scan readiciona o que ainda estiver no disco."""
    with get_db() as conn:
        mid, files = _scope(conn, kind, ref)
        names = []
        if kind in ("movie", "show", "video"):
            names = [r[0] for r in conn.execute(
                "SELECT poster FROM media WHERE id = ? UNION ALL SELECT backdrop FROM media WHERE id = ? "
                "UNION ALL SELECT logo FROM media WHERE id = ? UNION ALL SELECT square FROM media WHERE id = ?",
                (mid, mid, mid, mid))]
            names += metadata.show_image_names(conn, "m.id = ?", (mid,))
            conn.execute("DELETE FROM media WHERE id = ?", (mid,))
        elif kind == "episode":
            names = [conn.execute("SELECT still FROM episodes WHERE id = ?", (ref,)).fetchone()["still"]]
            conn.execute("DELETE FROM episodes WHERE id = ?", (ref,))
        else:
            n = int(ref.split("-")[1])
            names = [r[0] for r in conn.execute("SELECT still FROM episodes WHERE media_id = ? AND season = ?", (mid, n))]
            s = conn.execute("SELECT poster, backdrop FROM seasons WHERE media_id = ? AND season = ?", (mid, n)).fetchone()
            names += [s["poster"], s["backdrop"]] if s else []
            conn.execute("DELETE FROM episodes WHERE media_id = ? AND season = ?", (mid, n))
            conn.execute("DELETE FROM seasons WHERE media_id = ? AND season = ?", (mid, n))
    for name in names:
        metadata.remove_local(name)
    metadata.prune_people()
    return jsonify(ok=True, next="/" if kind in ("movie", "show", "video") else f"/show/{mid}")


def _access_data(conn, kind, ref):
    if kind not in ("movie", "show", "video"):
        abort(404)
    m = conn.execute("SELECT m.id, m.title, m.library_id, l.name AS library, l.type FROM media m "
                     "JOIN libraries l ON l.id = m.library_id WHERE m.id = ?", (ref,)).fetchone()
    if not m or m["type"] != kind:
        abort(404)
    rows = conn.execute(
        "SELECT u.id, u.username, u.is_admin, EXISTS(SELECT 1 FROM user_libraries ul WHERE ul.user_id = u.id "
        "AND ul.library_id = ?) AS has FROM users u ORDER BY fold(u.username), u.id", (m["library_id"],)).fetchall()
    return m, {
        "title": m["title"], "library": m["library"],
        "with_access": [{"id": r["id"], "username": r["username"], "admin": bool(r["is_admin"])}
                        for r in rows if r["has"] or r["is_admin"]],
        "others": [{"id": r["id"], "username": r["username"]} for r in rows if not (r["has"] or r["is_admin"])],
    }


@bp.route("/admin/item/<kind>/<ref>/access", methods=["GET", "POST"])
@admin_required
def item_access(kind, ref):
    """Conceder Acesso (25.6): lista quem vê a biblioteca do item e libera a biblioteca a outro usuário local."""
    with get_db() as conn:
        m, data = _access_data(conn, kind, ref)
        if request.method == "POST":
            name = (request.form.get("user") or "").strip()
            u = conn.execute("SELECT id FROM users WHERE lower(username) = lower(?)", (name,)).fetchone() if name else None
            if not u:
                return jerr("err.usuario_nao_encontrado", 404)
            grant_library(conn, u["id"], m["library_id"])
            _, data = _access_data(conn, kind, ref)
    return jsonify(ok=True, **data)
