import hashlib
import math
import os
import re
import subprocess
import time
import uuid

from flask import Blueprint, Response, abort, jsonify, request

import config
from server.auth import admin_required, login_required
from server.db import get_db
from server.stream import get_item
from server.i18n import E, jerr

bp = Blueprint("subtitles", __name__)

_LANG_NAMES = (
    "english|portuguese|brazilian|portugues|português|spanish|espanol|español|french|german|italian|japanese|korean|"
    "chinese|russian|arabic|dutch|polish|turkish|swedish|norwegian|danish|finnish|greek|hebrew|hindi|thai|czech|hungarian"
)
_LANG_TOKEN = re.compile(
    r"^(?!ii$|iii$)(?:[a-z]{2,3}(?:-[a-z0-9]{2,4})?|" + _LANG_NAMES + r"|forced|sdh|cc|hi|default)$", re.I
)
_TS = re.compile(r"(\d{1,2}:\d{2}:\d{2}),(\d{3})")


def srt_to_vtt(text):
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\{\\[^}]*\}", "", _TS.sub(r"\1.\2", text))  # tags de posição do ASS ({\an8}) viram texto solto no player
    return "WEBVTT\n\n" + text.strip() + "\n"


def _read(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def external_subs(video_path):
    """Lista .srt ao lado do vídeo (mesmo nome base): [{id, lang, file}]."""
    folder, name = os.path.split(video_path)
    base = os.path.splitext(name)[0]
    found = []
    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith(".srt") or not f.lower().startswith(base.lower()):
            continue
        rest = f[len(base):-4]
        if rest and rest[0] not in "._ -":  # nome base exato: S01E1 não pega S01E10
            continue
        if rest and not all(_LANG_TOKEN.match(t) for t in re.split(r"[._ ]+", rest.strip("._ -"))):
            continue  # resto que não é idioma/flag ("Toy Story 2.srt" não é legenda de "Toy Story")
        lang = rest.strip(". _-") or None
        found.append({"file": os.path.join(folder, f), "lang": lang, "title": f})
    for i, s in enumerate(found):
        s["id"] = i
    return found


def vtt_path(srt_path):
    key = hashlib.sha1(f"{srt_path}:{os.path.getmtime(srt_path)}".encode()).hexdigest()[:16]
    out = os.path.join(config.SUBS_DIR, f"ext_{key}.vtt")
    if not os.path.exists(out):
        tmp = f"{out}.{uuid.uuid4().hex}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(srt_to_vtt(_read(srt_path)))
            os.replace(tmp, out)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    return out


SUBS_MAX_AGE = 30 * 86400


def clean_subs(max_age=SUBS_MAX_AGE):
    """Apaga do cache (data/subs) os .vtt com mais de `max_age` segundos; são recriados sob demanda."""
    removed = 0
    limit = time.time() - max_age
    try:
        names = os.listdir(config.SUBS_DIR)
    except OSError:
        return 0
    for n in names:
        if not n.startswith(("ext_", "emb_")):
            continue
        full = os.path.join(config.SUBS_DIR, n)
        try:
            if os.path.isfile(full) and os.path.getmtime(full) < limit:
                os.remove(full)
                removed += 1
        except OSError:
            pass
    return removed


TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}


def embedded_subs(info):
    """Legendas de texto embutidas (as de imagem, como PGS/VobSub, não são convertíveis)."""
    return [t for t in (info or {}).get("subs") or [] if t.get("codec") in TEXT_CODECS]


def extract_vtt(video_path, index):
    """Extrai a faixa `index` do vídeo para .vtt (cache em data/subs). None se falhar."""
    key = hashlib.sha1(f"{video_path}:{os.path.getmtime(video_path)}:{index}".encode()).hexdigest()[:16]
    out = os.path.join(config.SUBS_DIR, f"emb_{key}.vtt")
    if os.path.exists(out):
        return out
    tmp = f"{out}.{uuid.uuid4().hex}.tmp.vtt"
    try:
        r = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", video_path, "-map", f"0:{index}", "-c:s", "webvtt", tmp],
            capture_output=True, timeout=300,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        if os.path.exists(tmp):
            os.remove(tmp)
        return None
    if r.returncode != 0 or not os.path.exists(tmp):
        if os.path.exists(tmp):
            os.remove(tmp)
        return None
    os.replace(tmp, out)
    return out


@bp.route("/stream/<kind>/<int:item_id>/subs")
@login_required
def subs_list(kind, item_id):
    path, info = get_item(kind, item_id)
    subs = external_subs(path)
    with get_db() as conn:  # 47.1: atraso salvo por legenda (s)
        saved = {r["sub_key"]: r["offset"] for r in conn.execute(
            "SELECT sub_key, offset FROM sub_offset WHERE item_type = ? AND item_id = ?", (kind, item_id))}
    return jsonify(
        external=[
            {"id": s["id"], "lang": s["lang"], "title": s["title"], "url": f"/stream/{kind}/{item_id}/subs/{s['id']}.vtt",
             "key": ext_key(s), "offset": saved.get(ext_key(s), 0)}
            for s in subs
        ],
        embedded=[
            {"index": t["index"], "lang": t.get("lang"), "title": t.get("title"),
             "url": f"/stream/{kind}/{item_id}/subs/emb/{t['index']}.vtt",
             "key": emb_key(t), "offset": saved.get(emb_key(t), 0)}
            for t in embedded_subs(info)
        ],
    )


OFFSET_MAX = 300.0  # atraso máximo da legenda, em segundos (para mais e para menos)


def ext_key(sub):
    """Chave estável da legenda externa: o nome do arquivo (o id muda quando entra outro .srt na pasta)."""
    return f"ext:{sub['title']}"


def emb_key(track):
    return f"emb:{track['index']}"


@bp.route("/stream/<kind>/<int:item_id>/subs/offset", methods=["POST"])
@login_required
def subs_offset(kind, item_id):
    """47.1: grava o atraso (s) de uma legenda do vídeo; vale para todos os perfis. 0 apaga o registro."""
    path, info = get_item(kind, item_id)
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    valid = {ext_key(s) for s in external_subs(path)} | {emb_key(t) for t in embedded_subs(info)}
    key = data.get("key")
    if not isinstance(key, str) or key not in valid:
        abort(404)
    raw = data.get("offset")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        abort(400)
    value = round(max(-OFFSET_MAX, min(OFFSET_MAX, float(raw))), 1)
    with get_db() as conn:
        if value == 0:
            conn.execute("DELETE FROM sub_offset WHERE item_type = ? AND item_id = ? AND sub_key = ?", (kind, item_id, key))
        else:
            conn.execute(
                "INSERT INTO sub_offset (item_type, item_id, sub_key, offset) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(item_type, item_id, sub_key) DO UPDATE SET offset = excluded.offset",
                (kind, item_id, key, value),
            )
    return jsonify(key=key, offset=value)


@bp.route("/stream/<kind>/<int:item_id>/subs/emb/<int:index>.vtt")
@login_required
def subs_embedded(kind, item_id, index):
    path, info = get_item(kind, item_id)
    if index not in [t["index"] for t in embedded_subs(info)]:
        abort(404)
    out = extract_vtt(path, index)
    if not out:
        abort(500)
    with open(out, encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/vtt", headers={"Cache-Control": "no-cache"})


@bp.route("/stream/<kind>/<int:item_id>/subs/<int:sid>.vtt")
@login_required
def subs_file(kind, item_id, sid):
    path, _ = get_item(kind, item_id)
    subs = external_subs(path)
    if sid >= len(subs):
        abort(404)
    with open(vtt_path(subs[sid]["file"]), encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/vtt", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- buscar legenda no SubDL (47.3, só admin)
def _json_error(msg, code=400):
    return jerr(msg, code)


@bp.route("/stream/<kind>/<int:item_id>/subs/search", methods=["POST"])
@login_required
def subs_search(kind, item_id):
    from server import subdl
    get_item(kind, item_id)
    d = request.get_json(silent=True)
    d = d if isinstance(d, dict) else {}
    lang = d.get("lang") if isinstance(d.get("lang"), str) and d.get("lang") in subdl.LANGS else config.SUBDL_LANG
    try:
        cands, tried, cached = subdl.search_manual(kind, item_id, lang, refresh=bool(d.get("refresh")))
    except ValueError as e:
        return _json_error(e)
    except subdl.Stop as e:
        return jerr(E("err.subdl_stop", reason=str(e)), 429)
    out = [{"id": c["id"], "release": c["release"], "author": c["author"], "hi": c["hi"], "forced": c["forced"],
            "pack": c["pack"], "downloads": c["downloads"] or None} for c in cands]
    path = get_item(kind, item_id)[0]
    have = [s["title"] for s in external_subs(path) if subdl.removable(path, s["title"])]
    return jsonify(lang=lang, langs=[{"code": k, "label": E(v)} for k, v in subdl.LANG_LABELS.items()], candidates=out,
                   cached=cached, budget=subdl.budget(), downloaded=have)


@bp.route("/stream/<kind>/<int:item_id>/subs/pick", methods=["POST"])
@login_required
def subs_pick(kind, item_id):
    from server import subdl
    get_item(kind, item_id)
    d = request.get_json(silent=True)
    d = d if isinstance(d, dict) else {}
    lang = d.get("lang")
    if lang not in subdl.LANGS:
        return _json_error(E("err.idioma_invalido"))
    try:
        fname = subdl.pick_manual(kind, item_id, lang, d.get("id"))
    except ValueError as e:
        return _json_error(e)
    except subdl.Stop as e:
        return _json_error(f"SubDL: {e}.", 429)
    return jsonify(ok=True, file=fname, key=f"ext:{fname}")


@bp.route("/stream/<kind>/<int:item_id>/subs/remove", methods=["POST"])
@admin_required
def subs_remove(kind, item_id):
    from server import subdl
    get_item(kind, item_id)
    d = request.get_json(silent=True)
    d = d if isinstance(d, dict) else {}
    try:
        subdl.remove_manual(kind, item_id, d.get("file"))
    except ValueError as e:
        return _json_error(e)
    with get_db() as conn:
        conn.execute("DELETE FROM sub_offset WHERE item_type = ? AND item_id = ? AND sub_key = ?", (kind, item_id, f"ext:{d.get('file')}"))
    return jsonify(ok=True)
