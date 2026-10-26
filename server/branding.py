"""59.1: identidade visual do site em Configurações → Servidor: logo (barra superior e telas de entrada), animação inicial
(trocar por imagem/GIF/SVG/vídeo ou desligar). Arquivos em data/branding/; chaves em `settings`: brand_logo, brand_intro (nome do
arquivo), brand_intro_on (padrão ligado) e brand_intro_sec (2–15 s, só imagem/GIF/SVG). O Android não é afetado."""
import os
import re
import time

from flask import Blueprint, abort, jsonify, make_response, request, send_file

import config
from server.auth import admin_required
from server.db import get_db
from server.libraries import get_setting
from server.i18n import jerr

bp = Blueprint("branding", __name__)

BRAND_DIR = os.path.join(config.DATA_DIR, "branding")
LOGO_MAX = 2 * 1024 * 1024
INTRO_MAX = 25 * 1024 * 1024
SEC_DEFAULT, SEC_MIN, SEC_MAX = 5, 2, 15
KINDS = {"logo": ("brand_logo", LOGO_MAX, {"png", "jpg", "webp", "svg", "gif"}),
         "intro": ("brand_intro", INTRO_MAX, {"png", "jpg", "webp", "svg", "gif", "mp4", "webm"})}
MIME = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "svg": "image/svg+xml", "gif": "image/gif",
        "mp4": "video/mp4", "webm": "video/webm"}
_BAD_SVG = re.compile(rb"<\s*(script|foreignobject|iframe|embed|object)|javascript:|\son\w+\s*=|(xlink:)?href\s*=\s*[\"']\s*(?!#|data:)", re.I)
_cache = {"t": 0.0, "v": None}


def _upsert(conn, key, value):
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def sniff(data):
    """Tipo pelo conteúdo (não pelo nome do arquivo); None se não for um formato aceito."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"GIF8":
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp":
        return "mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if b"<svg" in head and (head.startswith(b"<") ):
        return "svg"
    return None


def _file_ok(name):
    return bool(name) and os.path.isfile(os.path.join(BRAND_DIR, name))


def _state(conn):
    now = time.time()
    if _cache["v"] is not None and now - _cache["t"] < 30:
        return _cache["v"]
    out = {"on": get_setting(conn, "brand_intro_on", "1") != "0"}
    try:
        sec = int(get_setting(conn, "brand_intro_sec", str(SEC_DEFAULT)))
    except (TypeError, ValueError):
        sec = SEC_DEFAULT
    out["sec"] = min(SEC_MAX, max(SEC_MIN, sec))
    for kind, (key, _, _) in KINDS.items():
        name = get_setting(conn, key, "") or ""
        if _file_ok(name):
            ext = name.rsplit(".", 1)[-1]
            out[kind] = {"url": f"/brand/{kind}?v={int(os.path.getmtime(os.path.join(BRAND_DIR, name)))}",
                         "kind": "video" if ext in ("mp4", "webm") else "image"}
        else:
            out[kind] = None
    _cache.update(t=now, v=out)
    return out


def _reset():
    _cache["v"] = None


def admin_state(conn):
    s = _state(conn)
    return {"logo": s["logo"], "intro": s["intro"], "intro_on": s["on"], "sec": s["sec"]}


@bp.app_context_processor
def brand_context():
    """`brand` para qualquer template (inclusive login): logo, animação inicial ligada/desligada e arquivo escolhido."""
    try:
        with get_db() as conn:
            s = _state(conn)
        return {"brand": {"logo": s["logo"]["url"] if s["logo"] else None, "intro_on": s["on"], "intro": s["intro"], "sec": s["sec"]}}
    except Exception:
        return {"brand": {"logo": None, "intro_on": True, "intro": None, "sec": SEC_DEFAULT}}


@bp.route("/brand/<kind>")
def serve(kind):
    if kind not in KINDS:
        abort(404)
    with get_db() as conn:
        name = get_setting(conn, KINDS[kind][0], "") or ""
    if not _file_ok(name):
        abort(404)
    r = make_response(send_file(os.path.join(BRAND_DIR, name), mimetype=MIME[name.rsplit(".", 1)[-1]], conditional=True))
    r.headers["Cache-Control"] = "public, max-age=31536000, immutable" if request.args.get("v") else "no-cache"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; media-src 'self'"
    return r


@bp.route("/admin/server/brand")
@admin_required
def get_brand():
    with get_db() as conn:
        return jsonify(admin_state(conn))


@bp.route("/admin/server/brand/<kind>", methods=["POST"])
@admin_required
def upload(kind):
    if kind not in KINDS:
        abort(404)
    key, limit, allowed = KINDS[kind]
    f = request.files.get("file")
    if not f:
        return jerr("err.escolha_arquivo", 400)
    data = f.stream.read(limit + 1)
    if len(data) > limit:
        return jerr("err.arquivo_grande", 413, vars={"n": limit // (1024 * 1024)})
    ext = sniff(data)
    if ext not in allowed:
        return jerr("err.formato_nao_aceito", 400, vars={"list": ", ".join(x.upper() for x in sorted(allowed))})
    if ext == "svg" and _BAD_SVG.search(data):
        return jerr("err.svg_contem_scripts_ou_links", 400)
    os.makedirs(BRAND_DIR, exist_ok=True)
    name = f"{kind}-{int(time.time())}.{ext}"
    with open(os.path.join(BRAND_DIR, name), "wb") as fh:
        fh.write(data)
    with get_db() as conn:
        old = get_setting(conn, key, "") or ""
        _upsert(conn, key, name)
        conn.commit()
        _reset()
        out = admin_state(conn)
    _drop(old, name)
    return jsonify(out)


@bp.route("/admin/server/brand/<kind>/remove", methods=["POST"])
@admin_required
def remove(kind):
    if kind not in KINDS:
        abort(404)
    key = KINDS[kind][0]
    with get_db() as conn:
        old = get_setting(conn, key, "") or ""
        _upsert(conn, key, "")
        conn.commit()
        _reset()
        out = admin_state(conn)
    _drop(old, "")
    return jsonify(out)


@bp.route("/admin/server/brand/options", methods=["POST"])
@admin_required
def options():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jerr("err.dados_invalidos", 400)
    with get_db() as conn:
        if "intro_on" in d:
            if not isinstance(d["intro_on"], bool):
                return jerr("err.opcao_invalida", 400)
            _upsert(conn, "brand_intro_on", "1" if d["intro_on"] else "0")
        if "sec" in d:
            if not isinstance(d["sec"], int) or isinstance(d["sec"], bool) or not SEC_MIN <= d["sec"] <= SEC_MAX:
                return jerr("err.duracao_entre", 400, vars={"min": SEC_MIN, "max": SEC_MAX})
            _upsert(conn, "brand_intro_sec", str(d["sec"]))
        conn.commit()
        _reset()
        return jsonify(admin_state(conn))


def _drop(old, keep):
    if old and old != keep:
        try:
            os.remove(os.path.join(BRAND_DIR, os.path.basename(old)))
        except OSError:
            pass
